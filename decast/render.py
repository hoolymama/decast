import sys
import re
import json
import subprocess
from pathlib import Path

from .utils import (
    check_ffmpeg, video_has_audio, segment_speed,
    srt_timestamp, format_duration,
)


def _generate_srt(segments: list[dict], srt_path: str,
                  max_speed: float = None, words_per_second: float = None):
    """
    Generate an SRT subtitle file from the segment narrations.

    Timecodes are relative to the OUTPUT video (after cuts and speedup).
    Each sentence in the narration becomes one subtitle entry — never split
    mid-sentence.
    """
    srt_lines = []
    counter = 1
    elapsed = 0.0

    for seg in segments:
        narration = seg.get("narration", "").strip()
        speed = segment_speed(seg, max_speedup=max_speed, words_per_second=words_per_second)
        output_duration = (seg["end"] - seg["start"]) / speed

        if not narration:
            elapsed += output_duration
            continue

        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', narration) if s.strip()]
        if not sentences:
            elapsed += output_duration
            continue

        total_words = len(narration.split())
        if total_words == 0:
            elapsed += output_duration
            continue

        for sentence in sentences:
            sentence_words = len(sentence.split())
            sentence_duration = output_duration * (sentence_words / total_words)
            start_t = elapsed
            end_t = elapsed + sentence_duration
            srt_lines.append(str(counter))
            srt_lines.append(f"{srt_timestamp(start_t)} --> {srt_timestamp(end_t)}")
            srt_lines.append(sentence)
            srt_lines.append("")
            counter += 1
            elapsed += sentence_duration

    with open(srt_path, "w") as f:
        f.write("\n".join(srt_lines))

    return srt_path


def _build_atempo_chain(speed: float) -> str:
    """
    Build an FFmpeg atempo filter chain for the given speed.
    atempo is limited to 0.5-100.0 per instance, but values >2.0
    need chaining for quality.
    """
    if speed <= 1.01:
        return "atempo=1.0"
    parts = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    parts.append(f"atempo={remaining:.4f}")
    return ",".join(parts)


def render(video_path: str, edit_path: str, out_path: str = None,
           burn_subs: bool = False, max_speed: float = None, wpm: int = None):
    """Cut, speed-match, and concatenate video segments, optionally burning in subtitles."""
    from .config import MAX_SPEEDUP, WORDS_PER_SECOND
    if max_speed is None:
        max_speed = MAX_SPEEDUP
    if wpm is not None:
        words_per_second = wpm / 60.0
    else:
        words_per_second = WORDS_PER_SECOND

    check_ffmpeg()
    video_path = Path(video_path)
    edit_path  = Path(edit_path)

    if not video_path.exists():
        sys.exit(f"Error: video not found — {video_path}")
    if not edit_path.exists():
        sys.exit(f"Error: edit file not found — {edit_path}")

    with open(edit_path) as f:
        edit = json.load(f)

    segments = edit.get("segments", [])
    if not segments:
        sys.exit("Error: no segments found in edit file.")

    if out_path is None:
        out_path = Path(video_path.stem + ".polished.mp4")
    else:
        out_path = Path(out_path)

    has_audio = video_has_audio(str(video_path))

    speeds = [segment_speed(seg, max_speedup=max_speed, words_per_second=words_per_second) for seg in segments]

    print(f"[3/3] Rendering {len(segments)} segment(s) with FFmpeg…")
    total_input = 0.0
    total_output = 0.0
    for i, (seg, speed) in enumerate(zip(segments, speeds)):
        src_dur = seg["end"] - seg["start"]
        out_dur = src_dur / speed
        total_input += src_dur
        total_output += out_dur
        speed_str = f"{speed:.1f}x" if speed > 1.01 else "1x"
        print(f"    Segment {i+1:2d}:  {src_dur:5.1f}s → {out_dur:5.1f}s ({speed_str})  "
              f"[{seg.get('section', '')}]")
    print(f"    Total: {format_duration(total_input)} → {format_duration(total_output)}")
    print()

    srt_path = out_path.with_suffix(".srt")
    _generate_srt(segments, str(srt_path), max_speed=max_speed, words_per_second=words_per_second)
    print(f"    Subtitles saved → {srt_path}")

    # Build FFmpeg filter_complex
    filter_parts = []
    concat_v_inputs = []
    concat_a_inputs = []

    for i, (seg, speed) in enumerate(zip(segments, speeds)):
        start = seg["start"]
        end   = seg["end"]

        if speed > 1.01:
            setpts = f"(PTS-STARTPTS)/{speed}"
        else:
            setpts = "PTS-STARTPTS"
        filter_parts.append(
            f"[0:v]trim=start={start}:end={end},setpts={setpts}[v{i}]"
        )
        concat_v_inputs.append(f"[v{i}]")

        if has_audio:
            atempo_chain = _build_atempo_chain(speed)
            filter_parts.append(
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
                f"{atempo_chain}[a{i}]"
            )
            concat_a_inputs.append(f"[a{i}]")

    n = len(segments)

    if has_audio:
        concat_str = (
            "".join(f"{concat_v_inputs[i]}{concat_a_inputs[i]}" for i in range(n))
            + f"concat=n={n}:v=1:a=1[outv][outa]"
        )
    else:
        concat_str = (
            "".join(concat_v_inputs)
            + f"concat=n={n}:v=1:a=0[outv]"
        )

    filter_complex = ";".join(filter_parts) + ";" + concat_str

    if burn_subs:
        temp_path = out_path.with_suffix(".tmp.mp4")
        cmd_cut = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-filter_complex", filter_complex,
            "-map", "[outv]",
        ]
        if has_audio:
            cmd_cut.extend(["-map", "[outa]"])
        cmd_cut.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "18"])
        if has_audio:
            cmd_cut.extend(["-c:a", "aac", "-b:a", "192k"])
        cmd_cut.append(str(temp_path))

        result = subprocess.run(cmd_cut, capture_output=True, text=True)
        if result.returncode != 0:
            print("FFmpeg error (cut pass):")
            print(result.stderr[-2000:])
            sys.exit(1)

        srt_escaped = str(srt_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        sub_filter = (
            f"subtitles='{srt_escaped}':"
            "force_style='FontSize=24,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,Outline=2,Shadow=1,"
            "MarginV=40,Alignment=2'"
        )

        cmd_subs = [
            "ffmpeg", "-y", "-i", str(temp_path),
            "-vf", sub_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        ]
        if has_audio:
            cmd_subs.extend(["-c:a", "copy"])
        cmd_subs.append(str(out_path))

        result = subprocess.run(cmd_subs, capture_output=True, text=True)
        temp_path.unlink(missing_ok=True)
        if result.returncode != 0:
            print("FFmpeg error (subtitle pass):")
            print(result.stderr[-2000:])
            sys.exit(1)
    else:
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-filter_complex", filter_complex,
            "-map", "[outv]",
        ]
        if has_audio:
            cmd.extend(["-map", "[outa]"])
        cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "18"])
        if has_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        cmd.append(str(out_path))

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("FFmpeg error:")
            print(result.stderr[-2000:])
            sys.exit(1)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"    Rendered → {out_path}  ({size_mb:.1f} MB)")

    # Write narration script with output timecodes
    script_path = out_path.with_suffix(".script.txt")
    with open(script_path, "w") as f:
        f.write("NARRATION SCRIPT\n")
        f.write("=" * 60 + "\n\n")
        elapsed = 0.0
        for s, speed in zip(segments, speeds):
            out_dur = (s["end"] - s["start"]) / speed
            ts = srt_timestamp(elapsed)
            speed_note = f"  ({speed:.1f}x)" if speed > 1.01 else ""
            f.write(f"[{ts}] [{s.get('section', 'Untitled')}]{speed_note}\n")
            if s.get("narration"):
                f.write(s["narration"] + "\n")
            f.write("\n")
            elapsed += out_dur
        if edit.get("editor_notes"):
            f.write("EDITOR NOTES\n")
            f.write("-" * 40 + "\n")
            f.write(edit["editor_notes"] + "\n")
    print(f"    Script saved → {script_path}")

    print()
    print("  Next steps:")
    if burn_subs:
        print("  1. Watch the polished video with subtitles.")
        print("  2. Record your voiceover reading the subtitles on screen.")
    else:
        print("  1. Watch the polished video alongside the .script.txt.")
        print("  2. Record your voiceover narration against the cut video.")
        print("     Or re-render with --subs to get on-screen subtitles:")
        print(f"       python polish.py render {video_path} {edit_path} --subs")
    print("  3. Drop the voiceover onto the video in your editor of choice.")
    print(f"  4. SRT file available at {srt_path} for soft subtitles too.")
    print()
