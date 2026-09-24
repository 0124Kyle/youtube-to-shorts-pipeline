"""Register one reviewed local MP4 in the tagged moving-footage catalog."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from src.video import _digest_file, _duration_video


def register(file: Path, tags: list[str], catalog: Path) -> Path:
    if not file.is_file() or file.suffix.lower() != ".mp4":
        raise ValueError("--file must point to an existing MP4")
    if not tags or any(not tag.strip() for tag in tags):
        raise ValueError("Add nonempty comma-separated topic tags from the script")
    if _duration_video(file) < 2:
        raise ValueError("Footage must contain at least two seconds of video")
    try:
        item = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid footage catalog {catalog}: {exc}") from exc
    if not isinstance(item, dict) or not isinstance(item.get("clips"), list):
        raise ValueError("Catalog must contain a clips list")
    digest = _digest_file(file)[:16]
    relative = f"stock/{digest}.mp4"
    target = catalog.parent / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(file, target)
    provenance = file.with_suffix(".source.json")
    if provenance.is_file():
        shutil.copy2(provenance, target.with_suffix(".source.json"))
    record = next((clip for clip in item["clips"] if clip.get("file") == relative), None)
    if record is None:
        item["clips"].append({"file": relative, "tags": list(dict.fromkeys(tags))})
    else:
        record["tags"] = list(dict.fromkeys(record.get("tags", []) + tags))
    temporary = catalog.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(catalog)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True, help="A downloaded and visually reviewed MP4")
    parser.add_argument("--tags", required=True, help="Comma-separated words found in the script, e.g. 房貸,月付,預算")
    parser.add_argument("--catalog", type=Path, default=Path("assets/live/catalog.json"))
    args = parser.parse_args()
    try:
        target = register(args.file, [tag.strip() for tag in args.tags.split(",")], args.catalog)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Registered: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
