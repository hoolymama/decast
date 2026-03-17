#!/usr/bin/env python3
"""
decast — clean up raw screencasts for demo use.

Usage:
  python polish.py transcribe <video>                    # Step 1: transcribe
  python polish.py rewrite <transcript.json>             # Step 2: AI rewrite + cut list
  python polish.py render <video> <edit.json>            # Step 3: render cut video
  python polish.py render <video> <edit.json> --subs     # Step 3: render with burned-in subtitles
  python polish.py run <video>                           # Run steps 1+2 automatically
"""

import sys
import os
import json
import re
import subprocess
import argparse
import textwrap
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

WHISPER_MODEL   = "small"         # tiny | base | small | medium | large
WHISPER_LANGUAGE = "en"           # force language (set to None for auto-detect)
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"


# ──────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ──────────────────────────────────────────────────────────────────────────────

def _check_ffmpeg():
    if not shutil.which("ffmpeg"):
        sys.exit(
            "Error: ffmpeg not found on PATH.\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt install ffmpeg"
        )

def _check_ffprobe():
    if not shutil.which("ffprobe"):
        sys.exit(
            "Error: ffprobe not found on PATH.\n"
            "  It ships with ffmpeg — reinstall ffmpeg to get it."
        )

def _video_has_audio(video_path: str) -> bool:
    """Check whether a video file contains an audio stream."""
    _check_ffprobe()
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "json", str(video_path)],
        capture_output=True, text=True,
    )
    try:
        info = json.loads(result.stdout)
        return len(info.get("streams", [])) > 0
    except json.JSONDecodeError:
        return False

def _get_video_duration(video_path: str) -> float:
    """Get duration of a video in seconds."""
    _check_ffprobe()
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(video_path)],
        capture_output=True, text=True,
    )
    try:
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError):
        sys.exit(f"Error: could not determine duration of {video_path}")


def _srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


WORDS_PER_SECOND = 2.5   # ~150 wpm natural speaking pace
MAX_SPEEDUP      = 3.0   # never speed video beyond this

def _segment_speed(seg: dict) -> float:
    """
    Calculate the playback speed for a segment so the video duration
    matches the time it takes to speak the narration at a natural pace.
    Returns 1.0 (no change) if narration is empty or already fits.
    """
    narration = seg.get("narration", "").strip()
    if not narration:
        return 1.0
    word_count = len(narration.split())
    narration_secs = word_count / WORDS_PER_SECOND
    video_secs = seg["end"] - seg["start"]
    if narration_secs <= 0 or video_secs <= narration_secs:
        return 1.0
    return min(video_secs / narration_secs, MAX_SPEEDUP)


def _format_duration(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ──────────────────────────────────────────────────────────────────────────────
# STEP 1 — TRANSCRIBE
# ──────────────────────────────────────────────────────────────────────────────

def transcribe(video_path: str, out_path: str = None) -> tuple[dict, str]:
    """Run faster-whisper and return word-level transcript with timestamps."""
    from faster_whisper import WhisperModel

    video_path = Path(video_path)
    if not video_path.exists():
        sys.exit(f"Error: file not found — {video_path}")

    if not _video_has_audio(str(video_path)):
        sys.exit(
            f"Error: {video_path} has no audio track.\n"
            "  This tool needs spoken narration to transcribe.\n"
            "  If this is a silent screen recording, add a narration track first."
        )

    if out_path is None:
        out_path = str(video_path.with_suffix(".transcript.json"))

    print(f"[1/3] Transcribing with Whisper ({WHISPER_MODEL})…")
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        str(video_path), word_timestamps=True, language=WHISPER_LANGUAGE,
    )

    words = []
    full_text_parts = []
    for segment in segments:
        if segment.words:
            for w in segment.words:
                words.append({
                    "word":  w.word.strip(),
                    "start": round(w.start, 3),
                    "end":   round(w.end, 3),
                })
                full_text_parts.append(w.word.strip())

    transcript = {
        "video":    str(video_path),
        "duration": round(info.duration, 3),
        "language": info.language,
        "text":     " ".join(full_text_parts),
        "words":    words,
    }

    with open(out_path, "w") as f:
        json.dump(transcript, f, indent=2)

    print(f"    Transcript saved → {out_path}")
    print(f"    Duration: {info.duration:.1f}s  |  Words: {len(words)}  |  Language: {info.language}")
    return transcript, out_path


# ──────────────────────────────────────────────────────────────────────────────
# STEP 2 — REWRITE + CUT LIST  (with segment-to-narration mapping)
# ──────────────────────────────────────────────────────────────────────────────

REWRITE_SYSTEM = """\
You are an expert screencast editor and script writer. You receive a raw transcript
with word-level timestamps and must produce a polished edit plan.

## TONE AND STYLE

The rewritten narration should sound like a confident, knowledgeable person giving
a clear walkthrough. Natural and friendly, but never rambling or repetitive.

- **Second person.** Address the viewer as "you": "you can upload videos",
  "when you click this, the panel opens." This is a tutorial, not a paper.

- **Concise, not robotic.** Cut the filler and fluff but keep it human.
  BAD:  "You can upload multiple videos at once if you like."
  GOOD: "You can upload multiple videos at once."
  (Just drop the padding — "if you like" adds nothing.)

- **Don't repeat yourself.** If the presenter explained the same thing twice or
  circled back, write it once clearly.
  BAD:  "In your media library you can also bring in Vimeo and YouTube links, but
         you can't use those in your showreel - only videos that you upload can be used."
  GOOD: "Your media library supports Vimeo and YouTube links, but only uploaded
         videos can be used in a showreel."

- **Trim the rambling, keep the point.**
  BAD:  "Good, so let's go to the music tab. You can put some instrumental music or
         you can leave no soundtrack. If you put some music on, just be aware that
         recruiters are probably going to cut the music or turn the volume down."
  GOOD: "In the Music tab, you can choose a soundtrack. Worth noting that recruiters
         often mute the audio while reviewing."

- **Kill filler words.** No "so", "basically", "actually", "alright", "okay so",
  "let's go ahead and", "um", "uh", "you know", "like". Every sentence should start
  with substance.

- **Be specific about UI.** Name buttons, tabs, panels, and actions precisely.

## SEGMENTS

Produce an ordered list of video time ranges to KEEP from the original, each paired
with rewritten narration describing what is visible on screen during that segment.

Cut out:
- Long silences / dead air (>2 seconds of nothing happening)
- All filler, fumbling, repeated attempts, false starts
- Waiting time (loading, uploads, processing) beyond ~2 seconds
- Tangents, asides, or off-topic chatter
- Redundant explanations — write one clean version instead

Cut aggressively. A 20-minute raw recording should often become 5-10 minutes.
Keep only what is essential to understand the feature being demonstrated.

The renderer will speed up video segments to match the narration pace, so don't
pad segments with extra time. Trim segments to show only the essential action.

## OUTPUT FORMAT

Return ONLY valid JSON (no prose, no markdown fences):
{
  "segments": [
    {
      "start": 0.0,
      "end": 12.4,
      "narration": "Clear, concise narration for this segment.",
      "section": "Short section title",
      "cut_reason": null
    }
  ],
  "editor_notes": "Overall notes for the human editor."
}

## NARRATION PACING

- Each segment's narration should be readable in roughly the time the segment lasts
  (~2.5 words per second / ~150 words per minute)
- If a segment is very short (<3s), the narration should be one brief sentence or empty
- The gap between one segment's end and the next's start is what gets CUT

Do not list cut sections — only the kept segments."""

def rewrite(transcript_path: str, out_path: str = None) -> tuple[dict, str]:
    """Send transcript to Claude, get back aligned segments with narration."""
    import anthropic

    transcript_path = Path(transcript_path)
    with open(transcript_path) as f:
        transcript = json.load(f)

    if out_path is None:
        out_path = str(transcript_path.with_suffix("").with_suffix(".edit.json"))

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY environment variable not set.")

    word_lines = []
    for w in transcript["words"]:
        word_lines.append(f"[{w['start']:7.2f}s] {w['word']}")

    user_content = (
        f"Raw screencast transcript — total duration {transcript['duration']:.1f}s\n\n"
        f"TIMESTAMPED WORDS:\n{chr(10).join(word_lines)}\n\n"
        f"FULL TEXT (for readability):\n{transcript['text']}\n\n"
        "Please produce the aligned segments with rewritten narration."
    )

    print("[2/3] Sending to Claude for rewrite and cut list…")
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8192,
        system=REWRITE_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = message.content[0].text.strip()

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    try:
        edit = json.loads(raw)
    except json.JSONDecodeError as e:
        raw_path = str(out_path).replace(".edit.json", ".raw_response.txt")
        with open(raw_path, "w") as f:
            f.write(raw)
        sys.exit(f"Error: Claude response wasn't valid JSON. Raw saved to {raw_path}\n{e}")

    edit["_meta"] = {
        "source_video":     transcript["video"],
        "source_duration":  transcript["duration"],
        "transcript_path":  str(transcript_path),
    }

    with open(out_path, "w") as f:
        json.dump(edit, f, indent=2)

    print(f"    Edit file saved → {out_path}")
    _print_summary(edit)
    return edit, out_path


def _print_summary(edit: dict):
    segments = edit.get("segments", [])
    src_dur = edit.get("_meta", {}).get("source_duration", 0)
    total_kept = sum(s["end"] - s["start"] for s in segments)

    print()
    print("  ┌─ SEGMENTS ─────────────────────────────────────────────────")
    for i, s in enumerate(segments):
        duration = s["end"] - s["start"]
        print(f"  │  [{i+1}] {s['start']:.2f}s – {s['end']:.2f}s  ({duration:.1f}s)  [{s.get('section', '')}]")
        if s.get("narration"):
            wrapped = textwrap.fill(s["narration"], width=68,
                                    initial_indent="  │      ", subsequent_indent="  │      ")
            print(wrapped)
        print("  │")
    print(f"  ├─ SUMMARY: {len(segments)} segments, {total_kept:.1f}s kept")
    print(f"  │  Original: {src_dur:.1f}s  →  Cut to: {total_kept:.1f}s  "
          f"({100 * total_kept / src_dur:.0f}% of original)" if src_dur else "")
    if edit.get("editor_notes"):
        print(f"  ├─ EDITOR NOTES")
        wrapped = textwrap.fill(edit["editor_notes"], width=68,
                                initial_indent="  │  ", subsequent_indent="  │  ")
        print(wrapped)
    print("  └─────────────────────────────────────────────────────────────")
    print()
    print("  → Review/edit the .edit.json, then render:")
    print("    python polish.py render <video> <edit.json>")
    print("    python polish.py render <video> <edit.json> --subs   # with subtitles")
    print()


# ──────────────────────────────────────────────────────────────────────────────
# STEP 3 — RENDER  (with optional subtitle burn-in)
# ──────────────────────────────────────────────────────────────────────────────

def _generate_srt(segments: list[dict], srt_path: str):
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
        speed = _segment_speed(seg)
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
            srt_lines.append(f"{_srt_timestamp(start_t)} --> {_srt_timestamp(end_t)}")
            srt_lines.append(sentence)
            srt_lines.append("")
            counter += 1
            elapsed += sentence_duration

    with open(srt_path, "w") as f:
        f.write("\n".join(srt_lines))

    return srt_path


def render(video_path: str, edit_path: str, out_path: str = None,
           burn_subs: bool = False):
    """Cut, speed-match, and concatenate video segments, optionally burning in subtitles."""
    _check_ffmpeg()
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

    has_audio = _video_has_audio(str(video_path))

    # Calculate per-segment speeds
    speeds = [_segment_speed(seg) for seg in segments]

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
    print(f"    Total: {_format_duration(total_input)} → {_format_duration(total_output)}")
    print()

    # Generate SRT (always — useful even without burn-in)
    srt_path = out_path.with_suffix(".srt")
    _generate_srt(segments, str(srt_path))
    print(f"    Subtitles saved → {srt_path}")

    # Build FFmpeg filter_complex with per-segment speedup
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
            if speed <= 1.01:
                atempo_chain = "atempo=1.0"
            elif speed <= 2.0:
                atempo_chain = f"atempo={speed}"
            else:
                atempo_chain = f"atempo=2.0,atempo={speed / 2.0}"
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
        cmd_cut.extend([
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        ])
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
        cmd.extend([
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        ])
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

    # Write narration script with output timecodes (accounting for speedup)
    script_path = out_path.with_suffix(".script.txt")
    with open(script_path, "w") as f:
        f.write("NARRATION SCRIPT\n")
        f.write("=" * 60 + "\n\n")
        elapsed = 0.0
        for s, speed in zip(segments, speeds):
            out_dur = (s["end"] - s["start"]) / speed
            ts = _srt_timestamp(elapsed)
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


# ──────────────────────────────────────────────────────────────────────────────
# ENTRYPOINT
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="decast",
        description="Screencast Polish — clean up raw screencasts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Examples:
          python polish.py auto demo.mp4
              Full pipeline: transcribe → rewrite → render with subtitles.
              Output: demo.polished.mp4 (with burned-in subs) + .srt + .script.txt

          python polish.py run demo.mp4
              Transcribe + rewrite in one go. Review demo.edit.json, then render.

          python polish.py transcribe demo.mp4
              Just transcribe. Output: demo.transcript.json

          python polish.py rewrite demo.transcript.json
              Rewrite + cut list from existing transcript. Output: demo.edit.json

          python polish.py render demo.mp4 demo.edit.json
              Render the cut video. Output: demo.polished.mp4 + .srt + .script.txt

          python polish.py render demo.mp4 demo.edit.json --subs
              Render with subtitles burned into the video.

        Environment variables:
          ANTHROPIC_API_KEY   Required for the rewrite step.
        """)
    )

    sub = parser.add_subparsers(dest="command")

    p_auto = sub.add_parser("auto", help="Full pipeline: transcribe → rewrite → render with subs")
    p_auto.add_argument("video")

    p_run = sub.add_parser("run", help="Transcribe + rewrite (steps 1 & 2)")
    p_run.add_argument("video")

    p_t = sub.add_parser("transcribe", help="Transcribe video to JSON")
    p_t.add_argument("video")
    p_t.add_argument("--out", default=None)

    p_r = sub.add_parser("rewrite", help="Rewrite transcript with Claude")
    p_r.add_argument("transcript")
    p_r.add_argument("--out", default=None)

    p_rn = sub.add_parser("render", help="Render cut video with FFmpeg")
    p_rn.add_argument("video")
    p_rn.add_argument("edit")
    p_rn.add_argument("--out", default=None)
    p_rn.add_argument("--subs", action="store_true",
                       help="Burn subtitles into the video")

    args = parser.parse_args()

    if args.command == "auto":
        _, t_path = transcribe(args.video)
        _, e_path = rewrite(t_path)
        render(args.video, e_path, burn_subs=True)

    elif args.command == "run":
        _, t_path = transcribe(args.video)
        rewrite(t_path)

    elif args.command == "transcribe":
        transcribe(args.video, args.out)

    elif args.command == "rewrite":
        rewrite(args.transcript, args.out)

    elif args.command == "render":
        render(args.video, args.edit, args.out, burn_subs=args.subs)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
