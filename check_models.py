"""List text-generation models accessible to your Gemini API key (no generation call)."""

import os
import sys


def main() -> int:
    try:
        from dotenv import load_dotenv
        from google import genai
    except ImportError:
        print("Install dependencies: python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key == "replace_with_your_key":
        print("Set GEMINI_API_KEY in .env or your environment first.", file=sys.stderr)
        return 1
    try:
        with genai.Client(api_key=api_key) as client:
            available = sorted({
                model.name.removeprefix("models/")
                for model in client.models.list()
                if model.name and "generateContent" in (model.supported_actions or [])
            })
    except Exception as exc:
        print(f"Could not list models: {exc}", file=sys.stderr)
        return 1
    if not available:
        print("No generateContent models were returned for this API key.", file=sys.stderr)
        return 1
    print("Models available for generateContent (use one with --model):")
    for name in available:
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
