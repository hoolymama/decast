WHISPER_MODEL    = "small"
WHISPER_LANGUAGE = "en"
ANTHROPIC_MODEL  = "claude-sonnet-4-20250514"
GEMINI_MODEL     = "gemini-2.5-flash"

WORDS_PER_SECOND = 2.5   # ~150 wpm natural speaking pace
MAX_SPEEDUP      = 3.0   # max speedup for narrated segments
PURPOSE          = "tutorial"  # tutorial | teaser | demo
PADDING          = 1.5         # seconds of breathing room each side of narration

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
        "purpose": _get(getattr(args, "purpose", None), "DECAST_PURPOSE", PURPOSE),
        "padding": float(_get(getattr(args, "padding", None), "DECAST_PADDING", PADDING)),
    }
