#!/usr/bin/env python3
"""
decast — clean up raw screencasts for demo use.

Usage:
  python polish.py auto <video>                          # Full pipeline (marker mode, burned-in subs)
  python polish.py auto <video> --cut=auto               # Full pipeline (Claude decides cuts)
  python polish.py transcribe <video>                    # Step 1: transcribe
  python polish.py rewrite <transcript.json>             # Step 2: AI rewrite + cut list
  python polish.py render <video> <edit.json>            # Step 3: render cut video
  python polish.py render <video> <edit.json> --subs     # Step 3: render with burned-in subtitles
  python polish.py run <video>                           # Run steps 1+2 automatically
"""

import argparse
import textwrap

from dotenv import load_dotenv

load_dotenv()

from decast.transcribe import transcribe
from decast.rewrite import rewrite
from decast.render import render


def _add_cut_arg(parser):
    """Add the --cut flag to a subparser."""
    parser.add_argument(
        "--cut", choices=["marker", "auto"], default="marker",
        help="Cut mode: 'marker' (default) uses DECAST/RECAST voice markers; "
             "'auto' lets Claude decide all cuts"
    )


def main():
    parser = argparse.ArgumentParser(
        prog="decast",
        description="Screencast Polish — clean up raw screencasts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Cut modes:
          --cut=marker  (default) You control cuts with voice markers:
                        Say DECAST to cut a section, RECAST to fast-forward it.
          --cut=auto    Claude decides what to cut based on the transcript.

        Examples:
          python polish.py auto demo.mp4
              Full pipeline with marker mode (default).

          python polish.py auto demo.mp4 --cut=auto
              Full pipeline, Claude decides cuts.

          python polish.py run demo.mp4
              Transcribe + rewrite. Review demo.edit.json, then render.

          python polish.py transcribe demo.mp4
              Just transcribe. Output: demo.transcript.json

          python polish.py rewrite demo.transcript.json
              Rewrite transcript. Output: demo.edit.json

          python polish.py render demo.mp4 demo.edit.json --subs
              Render with subtitles burned into the video.

        Voice markers (--cut=marker):
          DECAST    Cut everything until you speak again.
          RECAST    Keep the video but fast-forward (10x) until you speak again.

        Environment variables:
          ANTHROPIC_API_KEY   Required for the rewrite step.
        """)
    )

    sub = parser.add_subparsers(dest="command")

    p_auto = sub.add_parser("auto", help="Full pipeline: transcribe → rewrite → render with subs")
    p_auto.add_argument("video")
    _add_cut_arg(p_auto)

    p_run = sub.add_parser("run", help="Transcribe + rewrite (steps 1 & 2)")
    p_run.add_argument("video")
    _add_cut_arg(p_run)

    p_t = sub.add_parser("transcribe", help="Transcribe video to JSON")
    p_t.add_argument("video")
    p_t.add_argument("--out", default=None)

    p_r = sub.add_parser("rewrite", help="Rewrite transcript with Claude")
    p_r.add_argument("transcript")
    p_r.add_argument("--out", default=None)
    _add_cut_arg(p_r)

    p_rn = sub.add_parser("render", help="Render cut video with FFmpeg")
    p_rn.add_argument("video")
    p_rn.add_argument("edit")
    p_rn.add_argument("--out", default=None)
    p_rn.add_argument("--subs", action="store_true",
                       help="Burn subtitles into the video")

    args = parser.parse_args()

    if args.command == "auto":
        _, t_path = transcribe(args.video)
        _, e_path = rewrite(t_path, cut_mode=args.cut)
        render(args.video, e_path, burn_subs=True)

    elif args.command == "run":
        _, t_path = transcribe(args.video)
        rewrite(t_path, cut_mode=args.cut)

    elif args.command == "transcribe":
        transcribe(args.video, args.out)

    elif args.command == "rewrite":
        rewrite(args.transcript, args.out, cut_mode=args.cut)

    elif args.command == "render":
        render(args.video, args.edit, args.out, burn_subs=args.subs)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
