"""Create short-video review drafts from one YouTube URL in a single command."""

import argparse
import importlib
import shutil
import sys

from src.automatic import run_pipeline
from src.rewrite import DEFAULT_MODEL


def check_environment() -> int:
    """Inspect this exact interpreter without using credentials or APIs."""
    print(f"Python interpreter: {sys.executable}")
    failures = []
    for module, package in (("dotenv", "python-dotenv"), ("yt_dlp", "yt-dlp"),
                            ("faster_whisper", "faster-whisper"), ("google.genai", "google-genai"),
                            ("pydantic", "pydantic"), ("fitz", "PyMuPDF"), ("PIL", "Pillow")):
        try:
            importlib.import_module(module)
            print(f"OK: {package}")
        except Exception as exc:
            failures.append(f"{package}: {type(exc).__name__}: {exc}")
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable):
            print(f"OK: {executable}")
        else:
            failures.append(f"{executable}: not found on PATH")
    for problem in failures:
        print(f"Missing: {problem}", file=sys.stderr)
    if failures:
        print("Use the Python interpreter shown above to install requirements.txt; install FFmpeg separately if needed.", file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Original YouTube video URL")
    parser.add_argument("--check", action="store_true", help="Check packages and FFmpeg without calling APIs")
    parser.add_argument("--count", type=int, default=2, help="Number of review drafts, 1–3 (default: 2)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model accessible to your API key")
    parser.add_argument("--voice", default="zh-TW-HsiaoChenNeural", help="Azure Speech zh-TW neural voice")
    parser.add_argument("--azure-tts", action="store_true", help="Add Azure Speech narration (requires its key and region)")
    parser.add_argument("--speed", type=float, default=1.12, help="Narration speed, 0.8–1.5")
    args = parser.parse_args()
    if args.check:
        return check_environment()
    if not args.url:
        parser.error("--url is required unless --check is used")
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        print(f"Error importing python-dotenv with {sys.executable}: {exc}", file=sys.stderr)
        return 1
    # Put your own GEMINI_API_KEY and PEXELS_API_KEY in a local .env; never commit API keys.
    load_dotenv()
    try:
        results = run_pipeline(args.url, count=args.count, model=args.model,
                               voice=args.voice, speed=args.speed, narrate=args.azure_tts)
    except ImportError as exc:
        print(f"Error importing a pipeline dependency with {sys.executable}: {exc}", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for path, cached in results:
        print(f"{'Cached' if cached else 'Created'}: {path}")
    print("Review the narration, footage and subtitles before sharing these drafts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
