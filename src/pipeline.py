"""Orchestrate audio acquisition, transcription, and resumable local caching."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .transcription import transcribe
from .youtube import download_audio, find_audio, parse_video_id


def save_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        return content if isinstance(content, dict) else None
    except (ValueError, OSError):
        return None


def run(url: str, output_dir: Path, model: str = "small", device: str = "cpu", compute_type: str = "int8", language: str | None = None, vad: bool = True, force: bool = False) -> tuple[Path, bool]:
    video_id = parse_video_id(url)
    directory = output_dir / video_id
    transcript_path = directory / "transcript.json"
    metadata_path = directory / "metadata.json"
    settings = {"model": model, "device": device, "compute_type": compute_type, "language": language, "vad_filter": vad}
    metadata = read_json(metadata_path)
    transcript = read_json(transcript_path)
    if not force and metadata and transcript and metadata.get("video_id") == video_id and metadata.get("settings") == settings and transcript.get("video_id") == video_id and isinstance(transcript.get("segments"), list):
        return transcript_path, True

    directory.mkdir(parents=True, exist_ok=True)
    audio = find_audio(directory)
    if audio is None:
        audio, source = download_audio(video_id, directory)
        save_json(metadata_path, source)
    else:
        source = read_json(metadata_path) or {"video_id": video_id, "source_url": f"https://www.youtube.com/watch?v={video_id}"}

    result = transcribe(audio, model, device, compute_type, language, vad)
    result.update({"video_id": video_id, "source_url": source["source_url"]})
    # Remove the old transcript before writing metadata, so either crash order
    # results in a cache miss on the next run.
    transcript_path.unlink(missing_ok=True)
    save_json(metadata_path, {
        **source,
        "audio_file": audio.name,
        "transcript_file": transcript_path.name,
        "settings": settings,
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        "transcription_api_cost_usd": 0,
    })
    save_json(transcript_path, result)
    return transcript_path, False
