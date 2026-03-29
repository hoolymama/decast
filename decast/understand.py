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
{{
  "events": [
    {{
      "start": 0.0,
      "end": 5.8,
      "key_moment": 3.4,
      "description": "Short description of what happens on screen",
      "ui_context": "Which screen/panel/dialog is visible"
    }}
  ]
}}

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
