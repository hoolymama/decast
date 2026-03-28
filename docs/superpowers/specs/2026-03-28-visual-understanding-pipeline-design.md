# Visual Understanding Pipeline — Design Spec

Replace the DECAST/RECAST voice marker system with a Gemini-powered visual understanding step. The system watches the video, understands what's happening on screen, and uses Claude to editorially condense the recording into a tight screencast with rewritten narration.

## Core Principle

The script is the source of truth. The video conforms to the script, not the other way around.

## Pipeline

Four discrete steps, each producing a cached intermediate file:

```
Raw screencast (.mp4)
     │
[1]  transcribe   → .transcript.json    (faster-whisper, local)
[2]  understand   → .scenes.json        (Gemini 2.5 Flash, remote)
[3]  rewrite      → .edit.json          (Claude, remote)
[4]  render       → .polished.mp4 + .srt + .script.txt  (FFmpeg, local)
```

Convenience commands:
- `auto` — all 4 steps
- `run` — steps 1-3 (stop before render for review)

Each step can be run individually. Expensive/slow steps (transcribe, understand) produce cached files so downstream steps can be re-run cheaply.

## CLI Interface

### Subcommands

| Command | Arguments | Description |
|---|---|---|
| `auto <video>` | `[--subs]` | Full pipeline |
| `run <video>` | | Steps 1-3 |
| `transcribe <video>` | `[--out]` | Whisper transcription |
| `understand <video> <transcript>` | `[--out]` | Gemini visual understanding |
| `rewrite <transcript> <scenes>` | `[--out]` | Claude editorial |
| `render <video> <edit>` | `[--out] [--subs]` | FFmpeg render |

### Configuration Flags

All flags have env var equivalents. Priority: CLI flag > env var > .env file > default.

| Setting | CLI flag | Env var | Default |
|---|---|---|---|
| Reading pace | `--wpm` | `DECAST_WPM` | `150` |
| Max speedup | `--max-speed` | `DECAST_MAX_SPEED` | `3.0` |
| Whisper model | `--whisper-model` | `DECAST_WHISPER_MODEL` | `small` |
| Gemini model | `--gemini-model` | `DECAST_GEMINI_MODEL` | `gemini-2.5-flash` |
| Claude model | `--claude-model` | `DECAST_CLAUDE_MODEL` | `claude-sonnet-4-20250514` |
| GCS bucket | `--gcs-bucket` | `DECAST_GCS_BUCKET` | None (use Gemini File API) |

API keys are env-var only (no CLI flags for secrets):
- `GEMINI_API_KEY` — required for `understand` step
- `ANTHROPIC_API_KEY` — required for `rewrite` step

## Step 1: Transcribe (`decast/transcribe.py`)

Unchanged in core function. Runs faster-whisper with word-level timestamps.

**Changes from current:**
- Remove all marker detection logic (no more `detect_markers` import/calls)
- Remove marker summary printing
- Just transcribe and return

**Output:** `.transcript.json` (same format as current)

## Step 2: Understand (`decast/understand.py`) — NEW

Uploads video to Gemini and produces an event-based scene description with key moments.

### Flow

1. Validate `GEMINI_API_KEY` is set
2. Upload video:
   - Default: Gemini File API (temporary, auto-deleted after 48h)
   - If `--gcs-bucket` set: upload to `gs://<bucket>/decast/<filename>`, pass URI to Gemini
3. Send prompt to Gemini with uploaded video + transcript text
4. Parse structured JSON response
5. Save to `.scenes.json`

### Gemini Prompt

Asks for event-based output:
- Timestamped UI events (clicks, page transitions, dialogs, content loading)
- A `key_moment` timestamp within each event — the exact moment the meaningful action occurs
- Correlation with narration — which events the speaker is describing

### Output Format: `.scenes.json`

```json
{
  "video": "demo.mp4",
  "duration": 1203.5,
  "events": [
    {
      "start": 2.1,
      "end": 5.8,
      "key_moment": 3.4,
      "description": "User clicks the Upload button in the top toolbar",
      "ui_context": "Main dashboard, media library tab"
    },
    {
      "start": 5.8,
      "end": 18.2,
      "key_moment": 17.5,
      "description": "File browser opens, user selects a video file, upload progress bar fills",
      "ui_context": "File upload dialog → progress overlay"
    }
  ]
}
```

### GCS Upload Path

When `--gcs-bucket` is provided, video is uploaded to `gs://<bucket>/decast/<filename>`. This persists the file for multi-day iteration — re-run `understand` without re-uploading. Requires `google-cloud-storage` SDK and appropriate GCP credentials.

### SDK

Uses `google-genai` Python SDK (the unified SDK).

## Step 3: Rewrite (`decast/rewrite.py`)

Claude receives both the transcript and scene descriptions, and produces the edit plan.

### Changes from Current

- Remove both existing system prompts (`REWRITE_SYSTEM_AUTO` and `REWRITE_SYSTEM_MARKER`)
- Replace with a single system prompt that references both transcript and visual scene data
- Remove all marker-related logic (`_prepare_marker_segments`, marker imports)
- Accept scenes file as a second input argument
- Remove `cut_mode` parameter

### What Claude Receives

- Full transcript text (what the user said)
- Scene events with key moments (what was happening visually)
- Configured WPM value for narration pacing calibration
- System prompt instructing editorial decisions

### What Claude Decides

- Which segments of the original video to keep (start/end times)
- Rewritten narration for each kept segment
- Section titles
- For segments where video duration would exceed 3x narration reading time: tighten start/end around the `key_moment` from scenes data instead of excessive speedup

### System Prompt Design

Single prompt that instructs Claude to:
- Use scene events to understand what's visually important
- Use transcript to understand user intent
- Cut aggressively: dead air, filler, fumbling, repeated attempts, redundant explanations
- Rewrite narration: second person, concise, kill filler words, be specific about UI
- Respect the speedup cap: if a segment would need >3x to match narration pace, trim the segment to center around the key moment instead
- Target narration pace at the configured WPM

### Output Format: `.edit.json`

```json
{
  "segments": [
    {
      "start": 2.1,
      "end": 5.8,
      "narration": "Click Upload in the toolbar to add your video.",
      "section": "Uploading media",
      "type": "narrated"
    }
  ],
  "editor_notes": "Overall observations about the recording.",
  "_meta": {
    "source_video": "demo.mp4",
    "source_duration": 1203.5,
    "transcript_path": "demo.transcript.json",
    "scenes_path": "demo.scenes.json"
  }
}
```

Only `"narrated"` type. No more `"recast"`.

## Step 4: Render (`decast/render.py`)

Mostly unchanged. Cuts, speed-matches, and concatenates segments with FFmpeg.

### Changes from Current

- Remove `"recast"` type handling
- All segments use the same speed calculation: narration word count vs video duration, capped at max speedup
- Subtitles: SRT sidecar always generated. Burned-in subs only with `--subs` flag.

## Module Changes Summary

| Module | Action |
|---|---|
| `decast/config.py` | Remove marker regex patterns, `RECAST_SPEEDUP`. Add `GEMINI_MODEL`. Remaining constants become fallback defaults. |
| `decast/markers.py` | **Delete entirely.** |
| `decast/transcribe.py` | Remove marker detection imports and logic. |
| `decast/understand.py` | **New.** Gemini video understanding. |
| `decast/rewrite.py` | New single system prompt. Accept scenes input. Remove marker logic and `cut_mode`. |
| `decast/render.py` | Remove recast type handling. |
| `decast/utils.py` | Remove `RECAST_SPEEDUP` import and recast branch in `segment_speed`. |
| `polish.py` | New CLI structure: remove `--cut`, add config flags, add `understand` subcommand, update argument signatures. |
| `requirements.txt` | Add `google-genai`. Note `google-cloud-storage` as optional install for GCS (`pip install google-cloud-storage`). |
| `.env.example` | Add `GEMINI_API_KEY=...` |

## Configuration Resolution

Config is resolved once at startup in `polish.py`:

1. Parse CLI args
2. For each setting: CLI flag → env var → `.env` file → default from `config.py`
3. Produce a config dict passed to each step function

No global mutable state. Each step function receives the config values it needs as parameters.

## Error Handling

- **Gemini upload failure:** Error out with clear message. No retry. If GCS, suggest checking credentials.
- **Bad JSON from Gemini or Claude:** Save raw response to `.raw_response.txt`, exit with error.
- **Video too long for Gemini:** Error if exceeding ~1 hour limit, suggest trimming.
- **No speech detected:** Error out — speech is required.
- **Stale intermediate files:** Overwrite on re-run (latest wins).
- **Missing API keys:** Fail early at the start of the step that needs them.

## Dependencies

**New:**
- `google-genai` — Gemini API SDK
- `google-cloud-storage` — optional, only needed if using `--gcs-bucket`

**Existing (unchanged):**
- `faster-whisper` — local transcription
- `anthropic` — Claude API
- `python-dotenv` — env file loading
- FFmpeg/ffprobe — external, must be on PATH

## Gemini API Key Setup

Obtain a dedicated API key for decast (separate from any existing keys for billing isolation):

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Click "Get API Key" in the left sidebar
3. Create a new key in an existing Google Cloud project, or create a new project named "decast"
4. Copy the key and add to `.env`: `GEMINI_API_KEY=<your-key>`

Using a separate project ensures decast API usage is tracked independently in Google Cloud billing.
