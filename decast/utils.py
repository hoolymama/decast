import sys
import json
import shutil
import subprocess

from .config import WORDS_PER_SECOND, MAX_SPEEDUP, RECAST_SPEEDUP


def check_ffmpeg():
    if not shutil.which("ffmpeg"):
        sys.exit(
            "Error: ffmpeg not found on PATH.\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt install ffmpeg"
        )

def check_ffprobe():
    if not shutil.which("ffprobe"):
        sys.exit(
            "Error: ffprobe not found on PATH.\n"
            "  It ships with ffmpeg — reinstall ffmpeg to get it."
        )

def video_has_audio(video_path: str) -> bool:
    """Check whether a video file contains an audio stream."""
    check_ffprobe()
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

def get_video_duration(video_path: str) -> float:
    """Get duration of a video in seconds."""
    check_ffprobe()
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


def srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segment_speed(seg: dict) -> float:
    """
    Calculate the playback speed for a segment so the video duration
    matches the time it takes to speak the narration at a natural pace.
    RECAST segments use a fixed fast speedup.
    """
    if seg.get("type") == "recast":
        return RECAST_SPEEDUP
    narration = seg.get("narration", "").strip()
    if not narration:
        return 1.0
    word_count = len(narration.split())
    narration_secs = word_count / WORDS_PER_SECOND
    video_secs = seg["end"] - seg["start"]
    if narration_secs <= 0 or video_secs <= narration_secs:
        return 1.0
    return min(video_secs / narration_secs, MAX_SPEEDUP)


def format_duration(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
