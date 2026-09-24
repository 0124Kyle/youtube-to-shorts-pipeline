"""Validate a single YouTube video URL and download audio only."""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}


def parse_video_id(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("https", "http") or host not in DOMAINS or parsed.username or parsed.password or parsed.port:
        raise ValueError("Expected an http(s) YouTube video URL")
    parts = parsed.path.strip("/").split("/")
    if host.endswith("youtu.be"):
        video_id = parts[0] if len(parts) == 1 else ""
    elif parts[0] == "watch" and len(parts) == 1:
        ids = parse_qs(parsed.query).get("v", [])
        video_id = ids[0] if len(ids) == 1 else ""
    elif parts[0] in ("shorts", "live", "embed") and len(parts) == 2:
        video_id = parts[1]
    else:
        video_id = ""
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("URL must identify exactly one YouTube video")
    return video_id


def download_audio(video_id: str, directory: Path) -> tuple[Path, dict]:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install -r requirements.txt") from exc

    directory.mkdir(parents=True, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    options = {
        "format": "bestaudio/best",
        "outtmpl": str(directory / "audio.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "continuedl": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(f"YouTube download failed: {exc}") from exc
    if not isinstance(info, dict) or info.get("id") != video_id:
        raise RuntimeError("Downloader did not return the requested video")
    audio = find_audio(directory)
    if audio is None:
        raise RuntimeError("Download completed without an audio file")
    metadata = {
        "video_id": video_id,
        "source_url": url,
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "duration_seconds": info.get("duration"),
    }
    return audio, metadata


def find_audio(directory: Path) -> Path | None:
    files = [p for p in directory.glob("audio.*") if p.is_file() and p.stat().st_size > 0 and p.suffix not in (".part", ".ytdl", ".json")]
    return files[0] if len(files) == 1 else None
