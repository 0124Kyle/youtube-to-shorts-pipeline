"""Make draft live-footage shorts from selected scripts and a local video catalog."""

import argparse
import sys
from pathlib import Path

from src.auto_live import render_auto


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts", type=Path, required=True, help="A script JSON or directory of script_*.json files")
    parser.add_argument("--catalog", type=Path, default=Path("assets/live/catalog.json"))
    voice = parser.add_mutually_exclusive_group(required=True)
    voice.add_argument("--tts", action="store_true", help="Use an installed Chinese Windows System.Speech voice")
    voice.add_argument("--audio-dir", type=Path, help="Folder containing <candidate_id>.wav, .mp3 or .m4a")
    voice.add_argument("--azure-tts", action="store_true", help="Use Azure Speech API with env AZURE_SPEECH_KEY and AZURE_SPEECH_REGION")
    parser.add_argument("--azure-voice", default="zh-TW-HsiaoChenNeural", help="Azure zh-TW neural voice")
    parser.add_argument("--work-dir", type=Path, default=Path("data/auto-live"), help="Cache narration and planned storyboards")
    parser.add_argument("--output-dir", type=Path, default=Path("data/auto-shorts"))
    parser.add_argument("--speed", type=float, default=1.0, help="Narration playback speed, 0.8–1.5")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv()
        results = render_auto(args.scripts, args.catalog, args.work_dir, args.output_dir,
                              args.audio_dir, args.tts, args.speed, args.force, args.azure_tts, args.azure_voice)
    except ImportError:
        print("Install dependencies: python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for result, cached in results:
        print(f"{'Cached' if cached else 'Created'}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
