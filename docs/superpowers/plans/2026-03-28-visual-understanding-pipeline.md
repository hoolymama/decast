# Visual Understanding Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace DECAST/RECAST voice markers with a Gemini-powered visual understanding step so the system automatically identifies what to cut/keep and conforms the video to the rewritten script.

**Architecture:** Four-step pipeline (transcribe → understand → rewrite → render). Gemini 2.5 Flash analyzes the video for event-based scene descriptions with key moments. Claude receives both the transcript and scene data to make editorial decisions and rewrite narration. Config is resolved once at CLI startup from flags/env/defaults and passed as a dict.

**Tech Stack:** Python 3.13, faster-whisper, google-genai SDK, anthropic SDK, FFmpeg, python-dotenv

**Spec:** `docs/superpowers/specs/2026-03-28-visual-understanding-pipeline-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `decast/config.py` | Modify | Default constants (remove markers, add Gemini) |
| `decast/markers.py` | Delete | No longer needed |
| `decast/transcribe.py` | Modify | Remove marker detection |
| `decast/understand.py` | Create | Gemini video understanding |
| `decast/rewrite.py` | Rewrite | New single system prompt, accept scenes input |
| `decast/render.py` | Modify | Remove recast handling |
| `decast/utils.py` | Modify | Remove recast speed logic |
| `polish.py` | Rewrite | New CLI structure with config resolution |
| `requirements.txt` | Modify | Add google-genai |
| `.env.example` | Modify | Add GEMINI_API_KEY |
| `CLAUDE.md` | Modify | Update for new pipeline |
| `.gitignore` | Modify | Add *.scenes.json |

---

## Pre-requisite: Gemini API Key Setup

Before starting implementation, you need a `GEMINI_API_KEY`:

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Click **"Get API Key"** in the left sidebar
3. Click **"Create API key"** → select or create a GCP project named **"decast"** (separate from VFX Spotlight for billing isolation)
4. Copy the key
5. Add to your `.env` file: `GEMINI_API_KEY=<your-key>`

---

### Task 1: Strip Marker System

Remove all DECAST/RECAST marker logic from the codebase. This clears the way for the new pipeline.

**Files:**
- Delete: `decast/markers.py`
- Modify: `decast/config.py`
- Modify: `decast/transcribe.py`
- Modify: `decast/utils.py`
- Modify: `decast/render.py`

- [ ] **Step 1: Delete `decast/markers.py`**

```bash
rm decast/markers.py
```

- [ ] **Step 2: Clean up `decast/config.py`**

Remove the `import re` statement, `DECAST_PATTERNS`, `RECAST_PATTERNS`, and `RECAST_SPEEDUP`. Add `GEMINI_MODEL`. The file should become:

```python
WHISPER_MODEL    = "small"
WHISPER_LANGUAGE = "en"
ANTHROPIC_MODEL  = "claude-sonnet-4-20250514"
GEMINI_MODEL     = "gemini-2.5-flash"

WORDS_PER_SECOND = 2.5   # ~150 wpm natural speaking pace
MAX_SPEEDUP      = 3.0   # max speedup for narrated segments
```

- [ ] **Step 3: Clean up `decast/transcribe.py`**

Remove the `from .markers import detect_markers` import. Remove all marker detection and printing at the end of the `transcribe()` function (lines 60-68 in current file). Keep everything else — the function should end after printing the duration/words/language line, then return.

The end of the function should be:

```python
    print(f"    Transcript saved → {out_path}")
    print(f"    Duration: {info.duration:.1f}s  |  Words: {len(words)}  |  Language: {info.language}")

    return transcript, out_path
```

- [ ] **Step 4: Clean up `decast/utils.py`**

Remove the `RECAST_SPEEDUP` import from the config import line. Remove the recast branch in `segment_speed()`. The function should become:

```python
def segment_speed(seg: dict, max_speedup: float = MAX_SPEEDUP) -> float:
    """
    Calculate the playback speed for a segment so the video duration
    matches the time it takes to speak the narration at a natural pace.
    """
    narration = seg.get("narration", "").strip()
    if not narration:
        return 1.0
    word_count = len(narration.split())
    narration_secs = word_count / WORDS_PER_SECOND
    video_secs = seg["end"] - seg["start"]
    if narration_secs <= 0 or video_secs <= narration_secs:
        return 1.0
    return min(video_secs / narration_secs, max_speedup)
```

Note: `max_speedup` is now a parameter (with default from config) so it can be overridden by CLI config.

- [ ] **Step 5: Clean up `decast/render.py`**

In the `render()` function, remove the recast-specific print formatting. In the segment loop (around line 116), remove the `type_tag` logic that checks for `"recast"`. The print line becomes:

```python
        speed_str = f"{speed:.1f}x" if speed > 1.01 else "1x"
        print(f"    Segment {i+1:2d}:  {src_dur:5.1f}s → {out_dur:5.1f}s ({speed_str})  "
              f"[{seg.get('section', '')}]")
```

Also in `_generate_srt()`, remove the comment about RECAST segments (line 20) — all segments are narrated now.

- [ ] **Step 6: Update `decast/__init__.py`**

The current file exports `from .config import *`. This is fine — no change needed since config still exists. Just verify it doesn't import markers anywhere.

- [ ] **Step 7: Verify nothing imports markers**

```bash
grep -r "markers" decast/ polish.py
```

Should return no results.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Remove DECAST/RECAST marker system

Delete markers.py and strip all marker-related code from config,
transcribe, utils, and render modules."
```

---

### Task 2: Config Resolution & CLI Restructure

Build the config resolution system and restructure the CLI for the new 4-step pipeline.

**Files:**
- Modify: `polish.py`
- Modify: `decast/config.py`
- Modify: `requirements.txt`
- Modify: `.env.example`

- [ ] **Step 1: Update `.env.example`**

```
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...
```

- [ ] **Step 2: Update `requirements.txt`**

```
faster-whisper>=1.0.0
anthropic>=0.39.0
python-dotenv>=1.0.0
google-genai>=1.0.0
```

- [ ] **Step 3: Install new dependency**

```bash
source .venv/bin/activate && pip install -r requirements.txt
```

- [ ] **Step 4: Add `resolve_config()` to `decast/config.py`**

Add a function that resolves config from CLI args → env vars → defaults. Append this below the existing constants:

```python
import os


def resolve_config(args) -> dict:
    """Resolve configuration from CLI args > env vars > defaults."""
    def _get(cli_val, env_key, default):
        if cli_val is not None:
            return cli_val
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return type(default)(env_val) if default is not None else env_val
        return default

    return {
        "wpm": int(_get(getattr(args, "wpm", None), "DECAST_WPM", 150)),
        "max_speed": float(_get(getattr(args, "max_speed", None), "DECAST_MAX_SPEED", MAX_SPEEDUP)),
        "whisper_model": _get(getattr(args, "whisper_model", None), "DECAST_WHISPER_MODEL", WHISPER_MODEL),
        "gemini_model": _get(getattr(args, "gemini_model", None), "DECAST_GEMINI_MODEL", GEMINI_MODEL),
        "claude_model": _get(getattr(args, "claude_model", None), "DECAST_CLAUDE_MODEL", ANTHROPIC_MODEL),
        "gcs_bucket": _get(getattr(args, "gcs_bucket", None), "DECAST_GCS_BUCKET", None),
    }
```

- [ ] **Step 5: Rewrite `polish.py`**

Replace the entire file with the new CLI structure:

```python
#!/usr/bin/env python3
"""
decast — clean up raw screencasts for demo use.

Usage:
  python polish.py auto <video>                              # Full pipeline
  python polish.py auto <video> --subs                       # Full pipeline with burned-in subs
  python polish.py transcribe <video>                        # Step 1: transcribe
  python polish.py understand <video> <transcript.json>      # Step 2: visual understanding
  python polish.py rewrite <transcript.json> <scenes.json>   # Step 3: AI editorial
  python polish.py render <video> <edit.json>                # Step 4: render
  python polish.py run <video>                               # Steps 1-3 (review before render)
"""

import argparse
import textwrap

from dotenv import load_dotenv

load_dotenv()

from decast.config import resolve_config
from decast.transcribe import transcribe
from decast.rewrite import rewrite
from decast.render import render


def _add_config_args(parser):
    """Add shared config flags to a subparser."""
    parser.add_argument("--wpm", type=int, default=None,
                        help="Reading pace in words per minute (default: 150, env: DECAST_WPM)")
    parser.add_argument("--max-speed", type=float, default=None,
                        help="Max video speedup factor (default: 3.0, env: DECAST_MAX_SPEED)")
    parser.add_argument("--whisper-model", default=None,
                        help="Whisper model size (default: small, env: DECAST_WHISPER_MODEL)")
    parser.add_argument("--gemini-model", default=None,
                        help="Gemini model name (default: gemini-2.5-flash, env: DECAST_GEMINI_MODEL)")
    parser.add_argument("--claude-model", default=None,
                        help="Claude model name (default: claude-sonnet-4-20250514, env: DECAST_CLAUDE_MODEL)")
    parser.add_argument("--gcs-bucket", default=None,
                        help="GCS bucket for persistent video storage (env: DECAST_GCS_BUCKET)")


def main():
    parser = argparse.ArgumentParser(
        prog="decast",
        description="Screencast Polish — clean up raw screencasts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Examples:
          python polish.py auto demo.mp4
              Full pipeline: transcribe → understand → rewrite → render.

          python polish.py auto demo.mp4 --subs
              Full pipeline with burned-in subtitles.

          python polish.py run demo.mp4
              Transcribe + understand + rewrite. Review demo.edit.json, then render.

          python polish.py transcribe demo.mp4
              Just transcribe. Output: demo.transcript.json

          python polish.py understand demo.mp4 demo.transcript.json
              Visual understanding. Output: demo.scenes.json

          python polish.py rewrite demo.transcript.json demo.scenes.json
              Editorial rewrite. Output: demo.edit.json

          python polish.py render demo.mp4 demo.edit.json --subs
              Render with subtitles burned into the video.

        Configuration:
          All settings can be set via CLI flags, environment variables, or .env file.
          Priority: CLI flag > env var > .env > default.

        Environment variables:
          ANTHROPIC_API_KEY       Required for the rewrite step.
          GEMINI_API_KEY          Required for the understand step.
          DECAST_WPM              Reading pace (default: 150)
          DECAST_MAX_SPEED        Max speedup (default: 3.0)
          DECAST_WHISPER_MODEL    Whisper model (default: small)
          DECAST_GEMINI_MODEL     Gemini model (default: gemini-2.5-flash)
          DECAST_CLAUDE_MODEL     Claude model (default: claude-sonnet-4-20250514)
          DECAST_GCS_BUCKET       GCS bucket for video storage (optional)
        """)
    )

    sub = parser.add_subparsers(dest="command")

    # auto: full pipeline
    p_auto = sub.add_parser("auto", help="Full pipeline: transcribe ��� understand → rewrite → render")
    p_auto.add_argument("video")
    p_auto.add_argument("--subs", action="store_true", help="Burn subtitles into the video")
    _add_config_args(p_auto)

    # run: steps 1-3
    p_run = sub.add_parser("run", help="Transcribe + understand + rewrite (steps 1-3)")
    p_run.add_argument("video")
    _add_config_args(p_run)

    # transcribe
    p_t = sub.add_parser("transcribe", help="Transcribe video to JSON")
    p_t.add_argument("video")
    p_t.add_argument("--out", default=None)
    _add_config_args(p_t)

    # understand
    p_u = sub.add_parser("understand", help="Visual understanding with Gemini")
    p_u.add_argument("video")
    p_u.add_argument("transcript")
    p_u.add_argument("--out", default=None)
    _add_config_args(p_u)

    # rewrite
    p_r = sub.add_parser("rewrite", help="Editorial rewrite with Claude")
    p_r.add_argument("transcript")
    p_r.add_argument("scenes")
    p_r.add_argument("--out", default=None)
    _add_config_args(p_r)

    # render
    p_rn = sub.add_parser("render", help="Render cut video with FFmpeg")
    p_rn.add_argument("video")
    p_rn.add_argument("edit")
    p_rn.add_argument("--out", default=None)
    p_rn.add_argument("--subs", action="store_true", help="Burn subtitles into the video")
    _add_config_args(p_rn)

    args = parser.parse_args()
    cfg = resolve_config(args)

    if args.command == "auto":
        _, t_path = transcribe(args.video, whisper_model=cfg["whisper_model"])
        # understand import deferred to Task 3
        from decast.understand import understand
        _, s_path = understand(args.video, t_path,
                               gemini_model=cfg["gemini_model"],
                               gcs_bucket=cfg["gcs_bucket"])
        _, e_path = rewrite(t_path, s_path,
                            claude_model=cfg["claude_model"],
                            wpm=cfg["wpm"],
                            max_speed=cfg["max_speed"])
        render(args.video, e_path, burn_subs=args.subs,
               max_speed=cfg["max_speed"], wpm=cfg["wpm"])

    elif args.command == "run":
        _, t_path = transcribe(args.video, whisper_model=cfg["whisper_model"])
        from decast.understand import understand
        _, s_path = understand(args.video, t_path,
                               gemini_model=cfg["gemini_model"],
                               gcs_bucket=cfg["gcs_bucket"])
        rewrite(t_path, s_path,
                claude_model=cfg["claude_model"],
                wpm=cfg["wpm"],
                max_speed=cfg["max_speed"])

    elif args.command == "transcribe":
        transcribe(args.video, args.out, whisper_model=cfg["whisper_model"])

    elif args.command == "understand":
        from decast.understand import understand
        understand(args.video, args.transcript, args.out,
                   gemini_model=cfg["gemini_model"],
                   gcs_bucket=cfg["gcs_bucket"])

    elif args.command == "rewrite":
        rewrite(args.transcript, args.scenes, args.out,
                claude_model=cfg["claude_model"],
                wpm=cfg["wpm"],
                max_speed=cfg["max_speed"])

    elif args.command == "render":
        render(args.video, args.edit, args.out, burn_subs=args.subs,
               max_speed=cfg["max_speed"], wpm=cfg["wpm"])

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Update function signatures**

The step functions need updated signatures to accept config values. For now, just update `transcribe()` — it needs to accept `whisper_model` as a parameter.

In `decast/transcribe.py`, change the function signature and model loading:

```python
def transcribe(video_path: str, out_path: str = None,
               whisper_model: str = None) -> tuple[dict, str]:
    """Run faster-whisper and return word-level transcript with timestamps."""
    from faster_whisper import WhisperModel

    if whisper_model is None:
        from .config import WHISPER_MODEL
        whisper_model = WHISPER_MODEL
```

Replace the hardcoded `WHISPER_MODEL` reference in the print statement (line 28) and model loading (line 29):

```python
    print(f"[1/3] Transcribing with Whisper ({whisper_model})…")
    model = WhisperModel(whisper_model, device="cpu", compute_type="int8")
```

Remove the top-level `from .config import WHISPER_MODEL, WHISPER_LANGUAGE` import. Keep `WHISPER_LANGUAGE` as a local import or move it inline:

```python
from .config import WHISPER_LANGUAGE
```

- [ ] **Step 7: Verify CLI parses correctly**

```bash
python polish.py --help
python polish.py auto --help
python polish.py understand --help
```

Each should print help text without errors.

- [ ] **Step 8: Commit**

```bash
git add polish.py decast/config.py decast/transcribe.py requirements.txt .env.example
git commit -m "Restructure CLI for 4-step pipeline with config resolution

Add understand subcommand, config flags (--wpm, --max-speed,
--whisper-model, --gemini-model, --claude-model, --gcs-bucket),
and resolve_config() for CLI > env > default priority."
```

---

### Task 3: Implement `understand` Step (Gemini Visual Understanding)

Build the new module that uploads video to Gemini and produces `.scenes.json`.

**Files:**
- Create: `decast/understand.py`

- [ ] **Step 1: Create `decast/understand.py`**

```python
import sys
import os
import json
from pathlib import Path

from google import genai


UNDERSTAND_PROMPT = """\
You are analyzing a screencast recording. You have access to both the video and
a transcript of what the presenter said.

Your job is to identify the key UI events that happen on screen — clicks, page
transitions, dialogs opening/closing, content loading, typing, scrolling, etc.

## OUTPUT FORMAT

Return ONLY valid JSON (no prose, no markdown fences):
{
  "events": [
    {
      "start": 0.0,
      "end": 5.8,
      "key_moment": 3.4,
      "description": "Short description of what happens on screen",
      "ui_context": "Which screen/panel/dialog is visible"
    }
  ]
}

## RULES

- **Timestamps** are in seconds from the start of the video.
- **start/end** define the time range of the event.
- **key_moment** is the single most important instant within the event — the exact
  moment the meaningful action occurs (e.g., the click itself, the moment a dialog
  appears, the instant a page finishes loading). This is used for trimming.
- **description** should be factual and specific: name buttons, tabs, menus, fields.
- **ui_context** gives the broader screen context (which page, which panel).
- Events should be contiguous — no gaps. The first event starts at 0.0, the last
  event ends at the video duration.
- Focus on UI events that are meaningful to the user flow. Group minor sub-actions
  (e.g., cursor moving then clicking) into single events.
- Correlate with the transcript: if the speaker says "now I'll click Upload", the
  event around that timestamp should describe the upload action.
- Do NOT describe what the speaker is saying — only what is visually happening.

## TRANSCRIPT

{transcript_text}
"""


def understand(video_path: str, transcript_path: str, out_path: str = None,
               gemini_model: str = None, gcs_bucket: str = None) -> tuple[dict, str]:
    """Upload video to Gemini and produce event-based scene descriptions."""
    if gemini_model is None:
        from .config import GEMINI_MODEL
        gemini_model = GEMINI_MODEL

    video_path = Path(video_path)
    transcript_path = Path(transcript_path)

    if not video_path.exists():
        sys.exit(f"Error: video not found — {video_path}")
    if not transcript_path.exists():
        sys.exit(f"Error: transcript not found — {transcript_path}")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("Error: GEMINI_API_KEY environment variable not set.")

    with open(transcript_path) as f:
        transcript = json.load(f)

    if out_path is None:
        out_path = str(video_path.with_suffix(".scenes.json"))

    client = genai.Client(api_key=api_key)

    # Upload video
    print(f"[2/4] Uploading video to Gemini…")
    if gcs_bucket:
        video_uri = _upload_to_gcs(video_path, gcs_bucket)
        video_part = genai.types.Part.from_uri(file_uri=video_uri, mime_type="video/mp4")
        print(f"    Using GCS: {video_uri}")
    else:
        uploaded = client.files.upload(file=video_path)
        # Wait for processing
        import time
        while uploaded.state.name == "PROCESSING":
            print("    Processing video…")
            time.sleep(5)
            uploaded = client.files.get(name=uploaded.name)
        if uploaded.state.name == "FAILED":
            sys.exit(f"Error: Gemini failed to process video — {uploaded.state.name}")
        video_part = genai.types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type)
        print(f"    Uploaded via File API (expires in 48h)")

    # Build prompt
    prompt_text = UNDERSTAND_PROMPT.format(transcript_text=transcript["text"])

    print(f"    Analyzing with {gemini_model}…")
    response = client.models.generate_content(
        model=gemini_model,
        contents=[video_part, prompt_text],
    )

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    try:
        scenes = json.loads(raw)
    except json.JSONDecodeError as e:
        raw_path = str(out_path).replace(".scenes.json", ".scenes.raw_response.txt")
        with open(raw_path, "w") as f:
            f.write(raw)
        sys.exit(f"Error: Gemini response wasn't valid JSON. Raw saved to {raw_path}\n{e}")

    scenes["video"] = str(video_path)
    scenes["duration"] = transcript["duration"]

    with open(out_path, "w") as f:
        json.dump(scenes, f, indent=2)

    event_count = len(scenes.get("events", []))
    print(f"    Scenes saved → {out_path}")
    print(f"    Events identified: {event_count}")

    return scenes, out_path


def _upload_to_gcs(video_path: Path, bucket_name: str) -> str:
    """Upload video to GCS and return gs:// URI."""
    try:
        from google.cloud import storage
    except ImportError:
        sys.exit(
            "Error: google-cloud-storage is required for GCS uploads.\n"
            "  Install it: pip install google-cloud-storage"
        )

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob_name = f"decast/{video_path.name}"
    blob = bucket.blob(blob_name)

    print(f"    Uploading to gs://{bucket_name}/{blob_name}…")
    blob.upload_from_filename(str(video_path))

    return f"gs://{bucket_name}/{blob_name}"
```

- [ ] **Step 2: Verify the module imports**

```bash
python -c "from decast.understand import understand; print('OK')"
```

Should print `OK` (assuming google-genai is installed).

- [ ] **Step 3: Commit**

```bash
git add decast/understand.py
git commit -m "Add Gemini visual understanding step

New understand() function uploads video to Gemini (File API or GCS),
sends it with the transcript, and produces a .scenes.json with
timestamped UI events and key moments."
```

---

### Task 4: Rewrite the `rewrite` Step (Claude Editorial)

Replace the marker-based rewrite with the new system that consumes both transcript and scenes.

**Files:**
- Modify: `decast/rewrite.py`

- [ ] **Step 1: Rewrite `decast/rewrite.py`**

Replace the entire file:

```python
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
```

- [ ] **Step 2: Verify the module imports**

```bash
python -c "from decast.rewrite import rewrite; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add decast/rewrite.py
git commit -m "Rewrite editorial step to use transcript + scenes

Single system prompt instructs Claude to use both transcript and
Gemini scene data. Includes speedup constraint with key_moment
trimming. Removes all marker logic and cut_mode parameter."
```

---

### Task 5: Update Render Step

Update render to accept config parameters and remove recast handling.

**Files:**
- Modify: `decast/render.py`
- Modify: `decast/utils.py`

- [ ] **Step 1: Update `render()` function signature**

In `decast/render.py`, update the function signature to accept config parameters:

```python
def render(video_path: str, edit_path: str, out_path: str = None,
           burn_subs: bool = False, max_speed: float = None, wpm: int = None):
    """Cut, speed-match, and concatenate video segments, optionally burning in subtitles."""
```

At the top of the function body, resolve defaults:

```python
    from .config import MAX_SPEEDUP, WORDS_PER_SECOND
    if max_speed is None:
        max_speed = MAX_SPEEDUP
    if wpm is not None:
        words_per_second = wpm / 60.0
    else:
        words_per_second = WORDS_PER_SECOND
```

Update the `speeds` calculation to pass `max_speed`:

```python
    speeds = [segment_speed(seg, max_speedup=max_speed, words_per_second=words_per_second) for seg in segments]
```

- [ ] **Step 2: Update `segment_speed()` in `decast/utils.py`**

Make it accept `words_per_second` as a parameter too:

```python
def segment_speed(seg: dict, max_speedup: float = MAX_SPEEDUP,
                  words_per_second: float = WORDS_PER_SECOND) -> float:
    """
    Calculate the playback speed for a segment so the video duration
    matches the time it takes to speak the narration at a natural pace.
    """
    narration = seg.get("narration", "").strip()
    if not narration:
        return 1.0
    word_count = len(narration.split())
    narration_secs = word_count / words_per_second
    video_secs = seg["end"] - seg["start"]
    if narration_secs <= 0 or video_secs <= narration_secs:
        return 1.0
    return min(video_secs / narration_secs, max_speedup)
```

- [ ] **Step 3: Update `_generate_srt()` to accept `words_per_second`**

In `decast/render.py`, update `_generate_srt` signature and its call site:

```python
def _generate_srt(segments: list[dict], srt_path: str,
                  max_speed: float = None, words_per_second: float = None):
```

And update the call in `render()`:

```python
    _generate_srt(segments, str(srt_path), max_speed=max_speed, words_per_second=words_per_second)
```

Inside `_generate_srt`, use the same `segment_speed` with the passed parameters:

```python
        speed = segment_speed(seg, max_speedup=max_speed, words_per_second=words_per_second)
```

- [ ] **Step 4: Update the script writing section in `render()`**

In the narration script section at the end of `render()`, pass the parameters to `segment_speed`:

```python
        for s, speed in zip(segments, speeds):
```

This already uses the pre-calculated `speeds` list, so no change needed here.

- [ ] **Step 5: Remove recast-specific code from `render()`**

In the segment printing loop, simplify:

```python
    for i, (seg, speed) in enumerate(zip(segments, speeds)):
        src_dur = seg["end"] - seg["start"]
        out_dur = src_dur / speed
        total_input += src_dur
        total_output += out_dur
        speed_str = f"{speed:.1f}x" if speed > 1.01 else "1x"
        print(f"    Segment {i+1:2d}:  {src_dur:5.1f}s → {out_dur:5.1f}s ({speed_str})  "
              f"[{seg.get('section', '')}]")
```

In the script file writer, simplify:

```python
            speed_note = f"  ({speed:.1f}x)" if speed > 1.01 else ""
            f.write(f"[{ts}] [{s.get('section', 'Untitled')}]{speed_note}\n")
```

- [ ] **Step 6: Verify render imports are clean**

```bash
python -c "from decast.render import render; print('OK')"
```

- [ ] **Step 7: Commit**

```bash
git add decast/render.py decast/utils.py
git commit -m "Update render step with configurable speed/wpm parameters

segment_speed() now accepts max_speedup and words_per_second.
render() accepts max_speed and wpm from CLI config.
Remove all recast-specific formatting."
```

---

### Task 6: Update CLAUDE.md and Final Cleanup

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

Replace the entire file to reflect the new pipeline:

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

decast is a CLI tool that cleans up raw screencasts for demo use. It transcribes audio (Whisper), analyzes the video visually (Gemini), rewrites narration (Claude), and renders a tightened video (FFmpeg) with aligned subtitles for voiceover recording.

## Commands

\`\`\`bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Requires: ffmpeg on PATH, ANTHROPIC_API_KEY and GEMINI_API_KEY in env or .env

# Full pipeline (transcribe → understand → rewrite → render)
python polish.py auto demo.mp4
python polish.py auto demo.mp4 --subs   # with burned-in subtitles

# Steps 1-3 (stop before render to review .edit.json)
python polish.py run demo.mp4

# Individual steps
python polish.py transcribe demo.mp4                          # → demo.transcript.json
python polish.py understand demo.mp4 demo.transcript.json     # → demo.scenes.json
python polish.py rewrite demo.transcript.json demo.scenes.json # → demo.edit.json
python polish.py render demo.mp4 demo.edit.json --subs
\`\`\`

No test suite exists. No linter is configured.

## Configuration

All settings configurable via CLI flags, env vars, or .env file. Priority: CLI > env > .env > default.

| Setting | CLI flag | Env var | Default |
|---|---|---|---|
| Reading pace | `--wpm` | `DECAST_WPM` | `150` |
| Max speedup | `--max-speed` | `DECAST_MAX_SPEED` | `3.0` |
| Whisper model | `--whisper-model` | `DECAST_WHISPER_MODEL` | `small` |
| Gemini model | `--gemini-model` | `DECAST_GEMINI_MODEL` | `gemini-2.5-flash` |
| Claude model | `--claude-model` | `DECAST_CLAUDE_MODEL` | `claude-sonnet-4-20250514` |
| GCS bucket | `--gcs-bucket` | `DECAST_GCS_BUCKET` | None |

API keys: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (env vars only).

## Architecture

**Entry point:** `polish.py` — argparse CLI dispatching to the `decast` package.

**Four-stage pipeline:**

1. **`decast/transcribe.py`** — Runs faster-whisper for word-level timestamps. Returns `(transcript_dict, output_path)`.

2. **`decast/understand.py`** — Uploads video to Gemini (File API or GCS). Gemini produces event-based scene descriptions with key moments (the exact instant of each meaningful UI action). Returns `(scenes_dict, output_path)`.

3. **`decast/rewrite.py`** — Sends transcript + scene data to Claude. Claude decides what to cut/keep, rewrites narration, and respects the speedup cap by trimming segments around key moments when needed. Returns `(edit_dict, output_path)`.

4. **`decast/render.py`** — FFmpeg `filter_complex` to cut, speed-match, and concatenate. Generates `.srt` and `.script.txt`. Optional burned-in subtitles via `--subs`.

**Supporting modules:**
- `decast/config.py` — Default constants and `resolve_config()` for CLI > env > default resolution.
- `decast/utils.py` — FFmpeg/ffprobe helpers, SRT formatting, segment speed calculation.

## Key Concepts

- **Script is source of truth** — video conforms to the rewritten script, not the reverse.
- **Segment speed matching** — video segments sped up so duration matches narration reading time. Capped at configurable max (default 3x).
- **Key moments** — Gemini identifies the exact instant of each meaningful action. When speedup would exceed the cap, Claude trims segments to center around the key moment.
- **Edit file (.edit.json)** — intermediate format between rewrite and render. User reviews/tweaks before rendering.
- **Cached intermediates** — each step produces a file (.transcript.json, .scenes.json, .edit.json) so expensive steps aren't re-run unnecessarily.

## Dependencies

- `faster-whisper` for transcription (runs on CPU with int8)
- `google-genai` for Gemini API (video understanding)
- `anthropic` for Claude API (editorial rewrite)
- `python-dotenv` for .env loading
- `google-cloud-storage` (optional, for `--gcs-bucket`)
- FFmpeg/ffprobe must be installed externally
```

- [ ] **Step 2: Update `.gitignore`**

Add `.scenes.json` to the outputs section:

```
# Outputs
*.transcript.json
*.scenes.json
*.edit.json
*.polished.mp4
*.polished.script.txt
*.raw_response.txt
*.srt
```

- [ ] **Step 3: Verify no stale references remain**

```bash
grep -r "marker\|DECAST\|RECAST\|recast\|cut_mode" decast/ polish.py --include="*.py"
```

Should return nothing (or only this grep command in shell history).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md .gitignore
git commit -m "Update CLAUDE.md and .gitignore for visual understanding pipeline

Reflect new 4-step pipeline, config system, Gemini integration,
and removal of marker system."
```

---

### Task 7: End-to-End Smoke Test

Test the full pipeline with a real video to verify everything works together.

**Files:** None (manual testing)

- [ ] **Step 1: Verify environment**

```bash
source .venv/bin/activate
python -c "import faster_whisper; print('whisper OK')"
python -c "from google import genai; print('genai OK')"
python -c "import anthropic; print('anthropic OK')"
ffmpeg -version | head -1
echo "GEMINI_API_KEY=${GEMINI_API_KEY:+set}"
echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:+set}"
```

All should report OK/set.

- [ ] **Step 2: Test transcribe step**

```bash
python polish.py transcribe examples/output_720p.mp4
```

Should produce `examples/output_720p.transcript.json`.

- [ ] **Step 3: Test understand step**

```bash
python polish.py understand examples/output_720p.mp4 examples/output_720p.transcript.json
```

Should produce `examples/output_720p.scenes.json`. Inspect it — verify events have start/end/key_moment/description fields.

- [ ] **Step 4: Test rewrite step**

```bash
python polish.py rewrite examples/output_720p.transcript.json examples/output_720p.scenes.json
```

Should produce `examples/output_720p.edit.json`. Inspect the segment summary printed to console.

- [ ] **Step 5: Test render step**

```bash
python polish.py render examples/output_720p.mp4 examples/output_720p.edit.json
```

Should produce a `.polished.mp4`, `.srt`, and `.script.txt`.

- [ ] **Step 6: Test auto command**

```bash
python polish.py auto examples/output_720p.mp4
```

Should run all 4 steps end-to-end.

- [ ] **Step 7: Test config flags**

```bash
python polish.py auto examples/output_720p.mp4 --wpm 130 --max-speed 2.5
```

Verify the output reflects different pacing.
