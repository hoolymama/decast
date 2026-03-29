import sys
import os
import json
import textwrap
from pathlib import Path


REWRITE_SYSTEM = """\
You are an expert screencast editor and script writer. You receive:
1. A raw transcript of what the presenter said (with timestamps)
2. A scene description of what was happening on screen (UI events with key moments)

Your job is to produce a polished edit plan: which segments of the original video
to keep, and rewritten narration for each.

## CORE PRINCIPLE

The script is the source of truth. You decide the narration first, then choose
video segments that show the corresponding action. The video will be sped up or
trimmed to match the narration duration.

## TONE AND STYLE

- **Second person.** Address the viewer as "you".
- **Concise, not robotic.** Cut filler and fluff but keep it human and natural.
- **Kill filler words.** No "so", "basically", "actually", "alright", "okay so",
  "let's go ahead and", "um", "uh", "you know", "like".
- **Don't repeat yourself.** If the raw transcript says the same thing twice, say it once.
- **Trim the rambling, keep the point.**
- **Be specific about UI.** Name buttons, tabs, panels, and actions precisely.
  Use the scene descriptions to get exact UI element names.

## CUTTING RULES

Cut aggressively. A 20-minute raw recording should often become 3-5 minutes.

Cut out:
- Long silences / dead air (>2 seconds of nothing happening)
- All filler, fumbling, repeated attempts, false starts
- Waiting time (loading, uploads, processing) beyond ~2 seconds
- Tangents, asides, or off-topic chatter
- Redundant explanations — write one clean version instead
- Duplicate demonstrations of the same feature

Keep only what is essential to understand the feature being demonstrated.

## SPEEDUP CONSTRAINT

Target narration pace: {wpm} words per minute.
Maximum video speedup: {max_speed}x.

If a segment's video duration would need more than {max_speed}x speedup to match
the narration reading time, you MUST tighten the segment's start/end times.
Use the key_moment timestamps from the scene data to center the segment around
the most important action. For example, if the key moment is at 14.2s within a
12.0-24.0s event, trim to something like 13.0-16.0s rather than keeping all 12
seconds at 5x speed.

## OUTPUT FORMAT

Return ONLY valid JSON (no prose, no markdown fences):
{{
  "segments": [
    {{
      "start": 0.0,
      "end": 12.4,
      "narration": "Clear, concise narration for this segment.",
      "section": "Short section title",
      "type": "narrated"
    }}
  ],
  "editor_notes": "Overall notes for the human editor."
}}

## RULES

- Segments are ordered by start time. Gaps between segments are what gets cut.
- Each segment's narration describes what is visible on screen during that time range.
- The type field is always "narrated".
- Do not list cut sections — only the kept segments.
- editor_notes: brief overall observations about the recording quality and your
  editorial choices.
"""


def rewrite(transcript_path: str, scenes_path: str, out_path: str = None,
            claude_model: str = None, wpm: int = 150,
            max_speed: float = None) -> tuple[dict, str]:
    """Send transcript + scenes to Claude for editorial rewrite."""
    import anthropic

    if claude_model is None:
        from .config import ANTHROPIC_MODEL
        claude_model = ANTHROPIC_MODEL

    if max_speed is None:
        from .config import MAX_SPEEDUP
        max_speed = MAX_SPEEDUP

    transcript_path = Path(transcript_path)
    scenes_path = Path(scenes_path)

    with open(transcript_path) as f:
        transcript = json.load(f)
    with open(scenes_path) as f:
        scenes = json.load(f)

    if out_path is None:
        out_path = str(transcript_path.with_suffix("").with_suffix(".edit.json"))

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY environment variable not set.")

    # Build user message with both transcript and scene data
    word_lines = []
    for w in transcript["words"]:
        word_lines.append(f"[{w['start']:7.2f}s] {w['word']}")

    scene_lines = []
    for e in scenes.get("events", []):
        scene_lines.append(
            f"[{e['start']:7.1f}s – {e['end']:7.1f}s] "
            f"(key: {e['key_moment']:.1f}s) {e['description']} "
            f"[{e.get('ui_context', '')}]"
        )

    user_content = (
        f"Raw screencast — total duration {transcript['duration']:.1f}s\n\n"
        f"## TRANSCRIPT (timestamped words)\n\n{chr(10).join(word_lines)}\n\n"
        f"## FULL TEXT\n\n{transcript['text']}\n\n"
        f"## SCENE EVENTS\n\n{chr(10).join(scene_lines)}\n\n"
        "Produce the edit plan with rewritten narration."
    )

    system_prompt = REWRITE_SYSTEM.format(wpm=wpm, max_speed=max_speed)

    print(f"[3/4] Sending to Claude for editorial rewrite…")
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=claude_model,
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
        "scenes_path":      str(scenes_path),
    }

    with open(out_path, "w") as f:
        json.dump(edit, f, indent=2)

    print(f"    Edit file saved → {out_path}")
    _print_summary(edit)
    return edit, out_path


def _print_summary(edit: dict):
    """Print a formatted summary of the edit plan."""
    segments = edit.get("segments", [])
    src_dur = edit.get("_meta", {}).get("source_duration", 0)
    total_kept = sum(s["end"] - s["start"] for s in segments)

    print()
    print("  ┌─ SEGMENTS ─────────────────────────────────────────────────")
    for i, s in enumerate(segments):
        duration = s["end"] - s["start"]
        print(f"  │  [{i+1}] {s['start']:.2f}s – {s['end']:.2f}s  ({duration:.1f}s)  "
              f"[{s.get('section', '')}]")
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
