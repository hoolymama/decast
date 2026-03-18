import sys
import json
from pathlib import Path

from .config import WHISPER_MODEL, WHISPER_LANGUAGE
from .utils import video_has_audio
from .markers import detect_markers


def transcribe(video_path: str, out_path: str = None) -> tuple[dict, str]:
    """Run faster-whisper and return word-level transcript with timestamps."""
    from faster_whisper import WhisperModel

    video_path = Path(video_path)
    if not video_path.exists():
        sys.exit(f"Error: file not found — {video_path}")

    if not video_has_audio(str(video_path)):
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

    detected = detect_markers(words)
    if detected:
        print(f"    Markers found: {len(detected)}")
        for m in detected:
            marker_word = " ".join(words[i]["word"] for i in m["word_indices"])
            print(f"      {m['type'].upper()} at {m['start']:.1f}s (heard: \"{marker_word}\")")
    else:
        print("    Markers found: none")

    return transcript, out_path
