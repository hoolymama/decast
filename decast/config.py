import re

WHISPER_MODEL   = "small"         # tiny | base | small | medium | large
WHISPER_LANGUAGE = "en"           # force language (set to None for auto-detect)
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"

WORDS_PER_SECOND = 2.5   # ~150 wpm natural speaking pace
MAX_SPEEDUP      = 3.0   # max speedup for narrated segments
RECAST_SPEEDUP   = 10.0  # speedup for RECAST (silent-but-kept) segments

DECAST_PATTERNS = re.compile(
    r'\b(decast|de-cast|d-cast|dee-cast|dee cast|the cast|de cast)\b', re.IGNORECASE
)
RECAST_PATTERNS = re.compile(
    r'\b(recast|re-cast|ree-cast|ree cast|re cast)\b', re.IGNORECASE
)
