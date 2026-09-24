"""Phase 1 CLI: YouTube URL to timestamped transcript."""

import argparse
import sys
from pathlib import Path

from src.pipeline import run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="A single YouTube video URL")
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--model", default="small", help="faster-whisper model (default: small)")
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--compute-type", default="int8", help="CTranslate2 compute type")
    parser.add_argument("--language", default=None, help="Language code, e.g. en; default: detect")
    parser.add_argument("--no-vad", action="store_true", help="Disable voice activity filtering")
    parser.add_argument("--force", action="store_true", help="Regenerate transcript, reuse downloaded audio")
    args = parser.parse_args()
    try:
        result, cached = run(
            args.url, args.output_dir, args.model, args.device,
            args.compute_type, args.language, not args.no_vad, args.force,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{'Cached' if cached else 'Saved'} transcript: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
