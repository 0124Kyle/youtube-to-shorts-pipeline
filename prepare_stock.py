"""Search Pexels portrait footage and download one reviewed video by ID."""

import argparse
import json
import os
import sys
from pathlib import Path

from src.external_media import pexels_download, pexels_search


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="A specific visual scene, e.g. hands using calculator")
    parser.add_argument("--video-id", type=int, help="Download this ID from the displayed candidates")
    parser.add_argument("--cache-dir", type=Path, default=Path("data/stock-cache"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/stock-reviewed"))
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv()
        candidates = pexels_search(args.query, os.environ.get("PEXELS_API_KEY", ""), args.cache_dir)
        print("Video source: https://www.pexels.com")
        for video in candidates:
            print(f"{video['id']}: {video.get('duration')}s | {video.get('user', {}).get('name')} | {video.get('url')}")
        if args.video_id is not None:
            selected = next((video for video in candidates if video.get("id") == args.video_id), None)
            if selected is None:
                raise ValueError("The selected video ID is not in this query's results")
            destination = args.output_dir / f"pexels_{args.video_id}.mp4"
            if destination.is_file():
                print(f"Existing file: {destination}")
            else:
                provenance = pexels_download(selected, destination)
                destination.with_suffix(".source.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"Downloaded: {destination}")
    except ImportError:
        print("Install dependencies: python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
