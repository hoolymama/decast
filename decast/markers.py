from .config import DECAST_PATTERNS, RECAST_PATTERNS


def classify_word(word: str) -> str | None:
    """Return 'decast', 'recast', or None for a transcribed word/phrase."""
    if DECAST_PATTERNS.search(word):
        return "decast"
    if RECAST_PATTERNS.search(word):
        return "recast"
    return None


def detect_markers(words: list[dict]) -> list[dict]:
    """
    Scan transcript words for DECAST/RECAST markers.

    Markers can span 1-2 words (e.g. "decast" or "dee cast").
    Returns a list of {"type": "decast"|"recast", "start": float, "end": float, "word_indices": [int]}.
    """
    markers = []
    i = 0
    while i < len(words):
        w = words[i]["word"]
        kind = classify_word(w)
        if kind:
            markers.append({
                "type": kind,
                "start": words[i]["start"],
                "end": words[i]["end"],
                "word_indices": [i],
            })
            i += 1
            continue
        if i + 1 < len(words):
            combo = w + " " + words[i + 1]["word"]
            kind = classify_word(combo)
            if kind:
                markers.append({
                    "type": kind,
                    "start": words[i]["start"],
                    "end": words[i + 1]["end"],
                    "word_indices": [i, i + 1],
                })
                i += 2
                continue
        i += 1
    return markers


def build_marker_segments(words: list[dict], markers: list[dict],
                          video_duration: float) -> list[dict]:
    """
    Build segments from marker positions.

    The transcript is split into regions:
    - NARRATED: words spoken between markers (or before the first / after the last)
    - DECAST: cut entirely (from marker to next speech)
    - RECAST: kept but silent (from marker to next speech)

    Returns a list of segment dicts ready for Claude to rewrite the narration.
    """
    marker_word_indices = set()
    for m in markers:
        marker_word_indices.update(m["word_indices"])

    if not markers:
        if words:
            return [{
                "type": "narrated",
                "start": max(0, words[0]["start"] - 0.5),
                "end": min(video_duration, words[-1]["end"] + 0.5),
                "raw_text": " ".join(w["word"] for w in words),
                "narration": "",
                "section": "",
            }]
        return []

    regions = []
    current_narrated_words = []

    for i, w in enumerate(words):
        if i in marker_word_indices:
            if current_narrated_words:
                regions.append({
                    "type": "narrated",
                    "words": list(current_narrated_words),
                })
                current_narrated_words = []
            for m in markers:
                if i == m["word_indices"][0]:
                    regions.append({
                        "type": m["type"],
                        "marker_end": m["end"],
                    })
                    break
        else:
            current_narrated_words.append(w)

    if current_narrated_words:
        regions.append({
            "type": "narrated",
            "words": list(current_narrated_words),
        })

    segments = []
    for idx, region in enumerate(regions):
        if region["type"] == "narrated":
            rwords = region["words"]
            start = max(0, rwords[0]["start"] - 0.3)
            end = min(video_duration, rwords[-1]["end"] + 0.3)

            segments.append({
                "type": "narrated",
                "start": round(start, 3),
                "end": round(end, 3),
                "raw_text": " ".join(w["word"] for w in rwords),
                "narration": "",
                "section": "",
            })
        elif region["type"] in ("decast", "recast"):
            region_start = region["marker_end"]
            region_end = None

            for future in regions[idx + 1:]:
                if future["type"] == "narrated" and future["words"]:
                    region_end = future["words"][0]["start"] - 0.3
                    break

            if region_end is None:
                region_end = video_duration

            region_start = max(0, round(region_start, 3))
            region_end = min(video_duration, round(region_end, 3))

            if region_end > region_start + 0.1 and region["type"] == "recast":
                segments.append({
                    "type": "recast",
                    "start": region_start,
                    "end": region_end,
                    "raw_text": "",
                    "narration": "",
                    "section": "(fast-forward)",
                })

    return segments
