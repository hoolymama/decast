#!/usr/bin/env python3
"""
decast — clean up raw screencasts for demo use.

Usage:
  python polish.py auto <video>                              # Full pipeline
  python polish.py auto <video> --subs                       # Full pipeline with burned-in subs
  python polish.py transcribe <video>                        # Step 1: transcribe
  python polish.py understand <video> <transcript.json>      # Step 2: visual understanding
  python polish.py rewrite <transcript.json> <scenes.json>   # Step 3: AI editorial
  python polish.py render <video> <edit.json>                # Step 4: render
  python polish.py run <video>                               # Steps 1-3 (review before render)
"""

import argparse
import textwrap

from dotenv import load_dotenv

load_dotenv()

from decast.config import resolve_config
from decast.transcribe import transcribe
from decast.understand import understand
from decast.rewrite import rewrite
from decast.render import render


def _add_config_args(parser):
    """Add shared config flags to a subparser."""
    parser.add_argument("--wpm", type=int, default=None,
                        help="Reading pace in words per minute (default: 150, env: DECAST_WPM)")
    parser.add_argument("--max-speed", type=float, default=None,
                        help="Max video speedup factor (default: 3.0, env: DECAST_MAX_SPEED)")
    parser.add_argument("--whisper-model", default=None,
                        help="Whisper model size (default: small, env: DECAST_WHISPER_MODEL)")
    parser.add_argument("--gemini-model", default=None,
                        help="Gemini model name (default: gemini-2.5-flash, env: DECAST_GEMINI_MODEL)")
    parser.add_argument("--claude-model", default=None,
                        help="Claude model name (default: claude-sonnet-4-20250514, env: DECAST_CLAUDE_MODEL)")
    parser.add_argument("--gcs-bucket", default=None,
                        help="GCS bucket for persistent video storage (env: DECAST_GCS_BUCKET)")


def main():
    parser = argparse.ArgumentParser(
        prog="decast",
        description="Screencast Polish — clean up raw screencasts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Examples:
          python polish.py auto demo.mp4
              Full pipeline: transcribe → understand → rewrite → render.

          python polish.py auto demo.mp4 --subs
              Full pipeline with burned-in subtitles.

          python polish.py run demo.mp4
              Transcribe + understand + rewrite. Review demo.edit.json, then render.

          python polish.py transcribe demo.mp4
              Just transcribe. Output: demo.transcript.json

          python polish.py understand demo.mp4 demo.transcript.json
              Visual understanding. Output: demo.scenes.json

          python polish.py rewrite demo.transcript.json demo.scenes.json
              Editorial rewrite. Output: demo.edit.json

          python polish.py render demo.mp4 demo.edit.json --subs
              Render with subtitles burned into the video.

        Configuration:
          All settings can be set via CLI flags, environment variables, or .env file.
          Priority: CLI flag > env var > .env > default.

        Environment variables:
          ANTHROPIC_API_KEY       Required for the rewrite step.
          GEMINI_API_KEY          Required for the understand step.
          DECAST_WPM              Reading pace (default: 150)
          DECAST_MAX_SPEED        Max speedup (default: 3.0)
          DECAST_WHISPER_MODEL    Whisper model (default: small)
          DECAST_GEMINI_MODEL     Gemini model (default: gemini-2.5-flash)
          DECAST_CLAUDE_MODEL     Claude model (default: claude-sonnet-4-20250514)
          DECAST_GCS_BUCKET       GCS bucket for video storage (optional)
        """)
    )

    sub = parser.add_subparsers(dest="command")

    # auto: full pipeline
    p_auto = sub.add_parser("auto", help="Full pipeline: transcribe → understand → rewrite → render")
    p_auto.add_argument("video")
    p_auto.add_argument("--subs", action="store_true", help="Burn subtitles into the video")
    _add_config_args(p_auto)

    # run: steps 1-3
    p_run = sub.add_parser("run", help="Transcribe + understand + rewrite (steps 1-3)")
    p_run.add_argument("video")
    _add_config_args(p_run)

    # transcribe
    p_t = sub.add_parser("transcribe", help="Transcribe video to JSON")
    p_t.add_argument("video")
    p_t.add_argument("--out", default=None)
    _add_config_args(p_t)

    # understand
    p_u = sub.add_parser("understand", help="Visual understanding with Gemini")
    p_u.add_argument("video")
    p_u.add_argument("transcript")
    p_u.add_argument("--out", default=None)
    _add_config_args(p_u)

    # rewrite
    p_r = sub.add_parser("rewrite", help="Editorial rewrite with Claude")
    p_r.add_argument("transcript")
    p_r.add_argument("scenes")
    p_r.add_argument("--out", default=None)
    _add_config_args(p_r)

    # render
    p_rn = sub.add_parser("render", help="Render cut video with FFmpeg")
    p_rn.add_argument("video")
    p_rn.add_argument("edit")
    p_rn.add_argument("--out", default=None)
    p_rn.add_argument("--subs", action="store_true", help="Burn subtitles into the video")
    _add_config_args(p_rn)

    args = parser.parse_args()
    cfg = resolve_config(args)

    if args.command == "auto":
        _, t_path = transcribe(args.video, whisper_model=cfg["whisper_model"])
        _, s_path = understand(args.video, t_path,
                               gemini_model=cfg["gemini_model"],
                               gcs_bucket=cfg["gcs_bucket"])
        _, e_path = rewrite(t_path, s_path,
                            claude_model=cfg["claude_model"],
                            wpm=cfg["wpm"],
                            max_speed=cfg["max_speed"])
        render(args.video, e_path, burn_subs=args.subs,
               max_speed=cfg["max_speed"], wpm=cfg["wpm"])

    elif args.command == "run":
        _, t_path = transcribe(args.video, whisper_model=cfg["whisper_model"])
        _, s_path = understand(args.video, t_path,
                               gemini_model=cfg["gemini_model"],
                               gcs_bucket=cfg["gcs_bucket"])
        rewrite(t_path, s_path,
                claude_model=cfg["claude_model"],
                wpm=cfg["wpm"],
                max_speed=cfg["max_speed"])

    elif args.command == "transcribe":
        transcribe(args.video, args.out, whisper_model=cfg["whisper_model"])

    elif args.command == "understand":
        understand(args.video, args.transcript, args.out,
                   gemini_model=cfg["gemini_model"],
                   gcs_bucket=cfg["gcs_bucket"])

    elif args.command == "rewrite":
        rewrite(args.transcript, args.scenes, args.out,
                claude_model=cfg["claude_model"],
                wpm=cfg["wpm"],
                max_speed=cfg["max_speed"])

    elif args.command == "render":
        render(args.video, args.edit, args.out, burn_subs=args.subs,
               max_speed=cfg["max_speed"], wpm=cfg["wpm"])

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
