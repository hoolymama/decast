# decast

Clean up raw screencasts for demo use. Removes filler words, condenses the
narration, cuts dead time, and produces a tightened video with aligned subtitles
you can read while recording a polished voiceover.

---

## How it works

```
Raw screencast (.mp4)
     │
     ▼
[1]  python polish.py transcribe demo.mp4
     └─ Whisper transcribes to word-level timestamps
        → demo.transcript.json

     ▼
[2]  python polish.py rewrite demo.transcript.json
     └─ Claude rewrites narration + builds aligned segment list
        → demo.edit.json   ← REVIEW AND EDIT THIS

     ▼
  (edit demo.edit.json if needed — adjust narration, tweak cut times)

     ▼
[3]  python polish.py render demo.mp4 demo.edit.json
     └─ FFmpeg cuts and joins video segments
        → demo.polished.mp4
        → demo.polished.srt          ← subtitle file (for soft subs or import)
        → demo.polished.script.txt   ← plain text script with timecodes

  Or with burned-in subtitles:
     python polish.py render demo.mp4 demo.edit.json --subs
        → subtitles rendered directly into the video

     ▼
  Watch the polished video (with subtitles if you used --subs).
  Record your voiceover narration reading the script.
  Drop the voiceover onto the video in any editor.
```

Or run steps 1+2 together:

```
python polish.py run demo.mp4
```

---

## Setup

### 1. Create a virtual environment

```bash
cd /path/to/decast
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Install FFmpeg

FFmpeg must be installed and on your PATH:

- macOS: `brew install ffmpeg`
- Ubuntu: `sudo apt install ffmpeg`

### 3. Set your API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Add this to your `~/.zshrc` or `~/.bashrc` to persist it.

---

## Commands

| Command | Description |
|---|---|
| `python polish.py run <video>` | Steps 1 + 2 together |
| `python polish.py transcribe <video>` | Transcribe only |
| `python polish.py rewrite <transcript.json>` | Rewrite only (uses existing transcript) |
| `python polish.py render <video> <edit.json>` | Render cut video |
| `python polish.py render <video> <edit.json> --subs` | Render with burned-in subtitles |

All commands accept `--out <path>` to override the default output path.

---

## The edit.json file

After the rewrite step you get a `.edit.json` file. This is the core of the system —
review and tweak it before rendering.

### `segments`

An ordered list of video time ranges to **keep**, each with aligned narration:

```json
{
  "start": 5.2,
  "end": 18.7,
  "narration": "Here I'll open the settings panel and enable dark mode.",
  "section": "Dark mode toggle",
  "cut_reason": null
}
```

- **`start` / `end`** — time range in the source video (seconds). Gaps between
  segments are what gets cut.
- **`narration`** — the rewritten script for this segment. This becomes the subtitle
  text and the voiceover script. **Edit freely.**
- **`section`** — short label for this part of the demo.

The narration is aligned to the video: each segment's text describes exactly what
is visible on screen during that time range. This means when you read the subtitles
during voiceover recording, you're describing what the viewer sees.

### `editor_notes`

Claude's overall observations about the raw recording.

---

## Subtitle options

The render step always generates a `.srt` file. You can use it in two ways:

1. **Burned-in** — use `--subs` to render subtitles directly into the video. Best
   for recording your voiceover: you see the script as you watch and speak.

2. **Soft subtitles** — import the `.srt` file into your video editor (DaVinci
   Resolve, ScreenFlow, etc.) as a separate track. This gives you full control
   over styling and can be toggled on/off.

---

## Whisper model sizes

Set `WHISPER_MODEL` at the top of `polish.py`:

| Model | Speed | Accuracy |
|---|---|---|
| `tiny` | Fastest | Lower |
| `base` | Fast | Good for clear speech |
| `small` | Medium | Better for accents |
| `medium` | Slow | High accuracy |
| `large` | Slowest | Best |

`base` is the default and works well for most screencasts recorded in a quiet room.

---

## Tips

- **Re-run rewrite without re-transcribing** — transcription is slow. If you want
  to tweak the Claude prompt or re-run the rewrite, just call `rewrite` again with
  the existing `.transcript.json`.

- **Adjusting cut times** — open the edit.json and nudge `start`/`end` values.
  A few tenths of a second either side can make a big difference to flow.

- **Voiceover workflow with subtitles** — render with `--subs`, play the video,
  and read the subtitles aloud as your voiceover. The subtitles are timed to match
  the on-screen action, so your narration will naturally sync.

- **Multiple takes** — if you recorded two attempts at one section, Claude will
  usually identify the redundant one. Check the segments to confirm.

- **Script file with timecodes** — the `.script.txt` includes timestamps relative
  to the output video, so you know exactly when each section starts.
