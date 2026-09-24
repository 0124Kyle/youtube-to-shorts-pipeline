"""Turn script JSONs into original 9:16 shorts with lower subtitles."""

import argparse
import sys
from pathlib import Path

from src.video import render_many


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts", type=Path, required=True, help="A script JSON or a directory of script_*.json files")
    parser.add_argument("--output-dir", type=Path, default=Path("data/shorts"))
    audio = parser.add_mutually_exclusive_group()
    audio.add_argument("--audio-dir", type=Path, help="Use <candidate_id>.wav/.mp3/.m4a in this folder as narration")
    audio.add_argument("--tts", action="store_true", help="Windows only: use a locally installed Chinese System.Speech voice")
    parser.add_argument("--seconds", type=int, default=48, help="Silent preview duration, 20–90 seconds (default: 48)")
    parser.add_argument("--style", choices=("live", "film", "promo", "cards"), default="film", help="Visual style (live uses moving footage; film uses illustrative stills)")
    parser.add_argument("--assets-dir", type=Path, default=Path("assets/film"), help="Folder with original photographic-style assets (default: assets/film)")
    parser.add_argument("--live-dir", type=Path, default=Path("assets/live"), help="Folder with <candidate_id>/storyboard.json and its local footage/audio")
    parser.add_argument("--music", type=Path, help="Optional licensed music file, looped and mixed quietly below narration")
    parser.add_argument("--force", action="store_true", help="Regenerate MP4s even if matching files are cached")
    args = parser.parse_args()
    try:
        outputs = render_many(args.scripts, args.output_dir, args.audio_dir, args.tts, args.seconds, args.force, args.style, args.music, args.assets_dir, args.live_dir)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for output, cached in outputs:
        print(f"{'Cached' if cached else 'Created'}: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
