# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

decast is a CLI tool that cleans up raw screencasts for demo use. It transcribes audio (Whisper), analyzes the video visually (Gemini), rewrites narration (Claude), and renders a tightened video (FFmpeg) with aligned subtitles for voiceover recording.

## Commands

```bash
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
```

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
