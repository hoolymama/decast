import sys
import os
import json
import textwrap
from pathlib import Path

from .config import ANTHROPIC_MODEL
from .markers import detect_markers, build_marker_segments


REWRITE_SYSTEM_AUTO = """\
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
      "type": "narrated"
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


REWRITE_SYSTEM_MARKER = """\
You are an expert screencast script writer. You receive a list of video segments with
raw narration text, and you must rewrite the narration to be clear and concise.

You do NOT decide what to cut or keep — the segments are already defined. Your only
job is to rewrite the narration for each segment.

## TONE AND STYLE

- **Second person.** Address the viewer as "you".
- **Concise, not robotic.** Cut filler and fluff but keep it human and natural.
- **Kill filler words.** No "so", "basically", "actually", "alright", "okay so",
  "let's go ahead and", "um", "uh", "you know", "like".
- **Don't repeat yourself.** If the raw text says the same thing twice, say it once.
- **Trim the rambling, keep the point.**
- **Be specific about UI.** Name buttons, tabs, panels, and actions precisely.
- Give each segment a short descriptive section title.

## INPUT/OUTPUT

You receive a JSON array of segments. Each has a "raw_text" field with the original
spoken words. Segments with type "recast" are silent fast-forward sections — leave
their narration empty.

Return ONLY valid JSON (no prose, no markdown fences):
{
  "segments": [
    {
      "start": 0.0,
      "end": 12.4,
      "narration": "Rewritten narration for this segment.",
      "section": "Short section title",
      "type": "narrated"
    },
    {
      "start": 12.4,
      "end": 45.0,
      "narration": "",
      "section": "(fast-forward)",
      "type": "recast"
    }
  ],
  "editor_notes": "Any notes for the human editor."
}

Preserve the start, end, and type fields exactly as given. Only change narration
and section. Do not add, remove, or reorder segments."""


def rewrite(transcript_path: str, out_path: str = None,
            cut_mode: str = "marker") -> tuple[dict, str]:
    """Send transcript to Claude for rewriting. In marker mode, segments are pre-built."""
    import anthropic

    transcript_path = Path(transcript_path)
    with open(transcript_path) as f:
        transcript = json.load(f)

    if out_path is None:
        out_path = str(transcript_path.with_suffix("").with_suffix(".edit.json"))

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY environment variable not set.")

    if cut_mode == "marker":
        system_prompt = REWRITE_SYSTEM_MARKER
        segments = _prepare_marker_segments(transcript)
        user_content = (
            f"Here are the pre-defined segments from a {transcript['duration']:.0f}s screencast.\n"
            f"Rewrite the narration for each segment.\n\n"
            f"{json.dumps(segments, indent=2)}"
        )
    else:
        system_prompt = REWRITE_SYSTEM_AUTO
        word_lines = []
        for w in transcript["words"]:
            word_lines.append(f"[{w['start']:7.2f}s] {w['word']}")
        user_content = (
            f"Raw screencast transcript — total duration {transcript['duration']:.1f}s\n\n"
            f"TIMESTAMPED WORDS:\n{chr(10).join(word_lines)}\n\n"
            f"FULL TEXT (for readability):\n{transcript['text']}\n\n"
            "Please produce the aligned segments with rewritten narration."
        )

    print(f"[2/3] Sending to Claude for rewrite ({cut_mode} mode)…")
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8192,
        system=system_prompt,
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
        "cut_mode":         cut_mode,
    }

    with open(out_path, "w") as f:
        json.dump(edit, f, indent=2)

    print(f"    Edit file saved → {out_path}")
    print_summary(edit)
    return edit, out_path


def _prepare_marker_segments(transcript: dict) -> list[dict]:
    """Build segments from markers in the transcript, for Claude to rewrite."""
    words = transcript["words"]
    markers = detect_markers(words)
    duration = transcript["duration"]

    segments = build_marker_segments(words, markers, duration)

    if not segments:
        print("    Warning: no segments produced (no speech detected?)")
        return []

    print(f"    Marker segmentation: {len(segments)} segments "
          f"({sum(1 for s in segments if s['type'] == 'narrated')} narrated, "
          f"{sum(1 for s in segments if s['type'] == 'recast')} recast)")
    for i, seg in enumerate(segments):
        dur = seg["end"] - seg["start"]
        if seg["type"] == "recast":
            print(f"      [{i+1}] RECAST  {seg['start']:.1f}s – {seg['end']:.1f}s  ({dur:.1f}s)")
        else:
            text_preview = seg["raw_text"][:60] + ("…" if len(seg["raw_text"]) > 60 else "")
            print(f"      [{i+1}] NARRATE {seg['start']:.1f}s – {seg['end']:.1f}s  ({dur:.1f}s)  \"{text_preview}\"")

    return segments


def print_summary(edit: dict):
    segments = edit.get("segments", [])
    src_dur = edit.get("_meta", {}).get("source_duration", 0)
    total_kept = sum(s["end"] - s["start"] for s in segments)

    print()
    print("  ┌─ SEGMENTS ─────────────────────────────────────────────────")
    for i, s in enumerate(segments):
        duration = s["end"] - s["start"]
        seg_type = s.get("type", "narrated")
        type_label = " [RECAST]" if seg_type == "recast" else ""
        print(f"  │  [{i+1}] {s['start']:.2f}s – {s['end']:.2f}s  ({duration:.1f}s)  "
              f"[{s.get('section', '')}]{type_label}")
        if s.get("narration"):
            wrapped = textwrap.fill(s["narration"], width=68,
                                    initial_indent="  │      ", subsequent_indent="  │      ")
            print(wrapped)
        print("  │")
    print(f"  ├─ SUMMARY: {len(segments)} segments, {total_kept:.1f}s kept")
    if src_dur:
        print(f"  │  Original: {src_dur:.1f}s  →  Cut to: {total_kept:.1f}s  "
              f"({100 * total_kept / src_dur:.0f}% of original)")
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
