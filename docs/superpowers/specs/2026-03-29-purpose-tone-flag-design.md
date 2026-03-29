# Purpose/Tone Flag — Design Spec

Add a `--purpose` CLI flag that controls the narration tone in the Claude editorial rewrite step. Three presets: `tutorial`, `teaser`, `demo`.

## CLI

```
python polish.py auto demo.mp4 --purpose teaser
python polish.py auto demo.mp4 --purpose demo
python polish.py auto demo.mp4                    # defaults to tutorial
```

## Config

| Setting | CLI flag | Env var | Default |
|---|---|---|---|
| Purpose | `--purpose` | `DECAST_PURPOSE` | `tutorial` |

Same resolution priority as all other config: CLI flag > env var > .env > default.

## Prompt Changes (`decast/rewrite.py`)

### Purpose-Specific Tone Paragraphs

A `PURPOSE_TONES` dict maps each purpose to a paragraph that gets injected into the `REWRITE_SYSTEM` prompt. This paragraph is inserted at the top of the TONE AND STYLE section, before the existing base rules (kill filler, be specific about UI, etc.) which apply to all purposes.

**`tutorial`** (current default behavior):
> Write as a step-by-step walkthrough. Address the viewer directly with "you" and guide them through each action. Be thorough but concise — explain what each step does and why.

**`teaser`**:
> Write as a features teaser. Short, punchy sentences focused on benefits and capabilities. Don't explain how to do things step by step — show what's possible. Energetic but not hypey. The viewer should come away impressed, not instructed.

**`demo`**:
> Write as a professional product demo. Show the workflow without hand-holding. Assume the viewer is evaluating the product, not learning it for the first time. Narrate what's happening on screen factually and let the product speak for itself.

### Cutting Aggressiveness

The purpose also affects how aggressively Claude cuts:

- **`tutorial`**: Current behavior. Cut filler and dead air, but keep enough context for a learner to follow.
- **`teaser`**: Cut very aggressively. Only the most impactful moments. A 20-minute recording should become 1-2 minutes.
- **`demo`**: Moderate cuts. Keep the flow coherent but trim anything that doesn't advance the story.

This guidance is included in the purpose paragraph.

### Prompt Template

The `REWRITE_SYSTEM` prompt uses a new `{purpose_tone}` placeholder:

```
## TONE AND STYLE

{purpose_tone}

- **Concise, not robotic.** Cut filler and fluff but keep it human and natural.
- **Kill filler words.** ...
- **Be specific about UI.** ...
```

The `rewrite()` function looks up the purpose in `PURPOSE_TONES` and formats it into the prompt alongside `{wpm}` and `{max_speed}`.

## Function Signature Change

`rewrite()` gains a `purpose` parameter:

```python
def rewrite(transcript_path: str, scenes_path: str, out_path: str = None,
            claude_model: str = None, wpm: int = 150,
            max_speed: float = None, purpose: str = "tutorial") -> tuple[dict, str]:
```

## `_meta` Update

The `.edit.json` `_meta` section records the purpose:

```json
"_meta": {
    "source_video": "demo.mp4",
    "source_duration": 1203.5,
    "transcript_path": "demo.transcript.json",
    "scenes_path": "demo.scenes.json",
    "purpose": "teaser"
}
```

## Files Changed

| File | Change |
|---|---|
| `decast/rewrite.py` | Add `PURPOSE_TONES` dict, `{purpose_tone}` placeholder in prompt, `purpose` parameter |
| `decast/config.py` | Add `PURPOSE` default constant, add to `resolve_config()` |
| `polish.py` | Add `--purpose` flag to `_add_config_args()`, pass through to `rewrite()` |
| `CLAUDE.md` | Add `--purpose` to config table |
