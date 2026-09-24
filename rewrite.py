"""Plan a few short-video topics locally, then optionally rewrite them with Gemini."""

import argparse
import sys
from pathlib import Path

from src.rewrite import DEFAULT_MODEL, plan_and_generate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", type=Path, required=True, help="Transcript JSON from main.py")
    parser.add_argument("--metadata", type=Path, required=True, help="Matching metadata.json")
    parser.add_argument("--output-dir", type=Path, default=None, help="Default: <transcript folder>/rewrite")
    parser.add_argument("--generate", action="store_true", help="Call Gemini for selected topics (requires GEMINI_API_KEY)")
    parser.add_argument("--select", default=None, help="Comma-separated candidate IDs, e.g. c02,c07")
    parser.add_argument("--top", type=int, default=3, help="Maximum scripts, 1 to 3 (default: 3)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    try:
        plan, scripts = plan_and_generate(
            args.transcript, args.metadata,
            args.output_dir or args.transcript.parent / "rewrite",
            args.generate, args.select, args.top, args.model,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Candidate plan: {plan}")
    for script in scripts:
        print(f"Draft script: {script}")
    if not args.generate:
        print("No API call made. Review candidates.json, then rerun with --generate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
