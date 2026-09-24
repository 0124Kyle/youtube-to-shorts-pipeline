"""Optional Pexels video search/download and Azure Speech synthesis adapters.

No API request occurs unless the caller explicitly selects that provider.
Secrets are read from the environment and never written into cache files.
"""

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

PEXELS_SEARCH = "https://api.pexels.com/v1/videos/search"
MAX_VIDEO_BYTES = 80 * 1024 * 1024


def _open(request: urllib.request.Request, timeout: int = 30):
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Media provider returned HTTP {exc.code}; check its credentials, quota and request") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Media provider could not be reached: {exc.reason}") from exc


def pexels_search(query: str, api_key: str, cache_dir: Path, max_results: int = 10) -> list[dict]:
    """Cache the API response for a day; list portrait clips for human selection."""
    if not query.strip() or not 1 <= max_results <= 80:
        raise ValueError("Provide a search query and 1–80 results")
    if not api_key:
        raise ValueError("Set PEXELS_API_KEY before searching")
    cache_dir.mkdir(parents=True, exist_ok=True)
    parameters = {"query": query.strip(), "orientation": "portrait", "locale": "zh-TW", "per_page": max_results}
    key = hashlib.sha256(json.dumps(parameters, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    cached = cache_dir / f"pexels_search_{key}.json"
    if cached.is_file() and time.time() - cached.stat().st_mtime < 86400:
        result = json.loads(cached.read_text(encoding="utf-8"))
    else:
        address = PEXELS_SEARCH + "?" + urllib.parse.urlencode(parameters)
        request = urllib.request.Request(address, headers={"Authorization": api_key, "User-Agent": "original-shorts/1.0"})
        with _open(request) as response:
            result = json.load(response)
        if not isinstance(result, dict) or not isinstance(result.get("videos"), list):
            raise RuntimeError("Unexpected Pexels search response")
        cached.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result["videos"]


def pexels_download(video: dict, target: Path) -> dict:
    """Download one explicitly selected MP4 and return provenance for catalog use."""
    files = [item for item in video.get("video_files", [])
             if item.get("file_type") == "video/mp4" and isinstance(item.get("width"), int)
             and isinstance(item.get("height"), int) and item["height"] > item["width"]
             and isinstance(item.get("link"), str)]
    if not files:
        raise ValueError("Selected Pexels video has no portrait MP4 version")
    selected = max(files, key=lambda item: min(item["height"], 1920) * min(item["width"], 1080))
    address = selected["link"]
    parsed = urllib.parse.urlparse(address)
    allowed_host = parsed.hostname == "player.vimeo.com" or (parsed.hostname and parsed.hostname.endswith(".pexels.com"))
    if parsed.scheme != "https" or not allowed_host:
        raise ValueError("Pexels returned an unexpected media host")
    if target.suffix.lower() != ".mp4":
        raise ValueError("Pexels video download path must end in .mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".mp4.part")
    written = 0
    try:
        with _open(urllib.request.Request(address, headers={"User-Agent": "original-shorts/1.0"}), timeout=60) as response, temporary.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_VIDEO_BYTES:
                    raise ValueError("Video exceeds the 80 MiB download limit")
                stream.write(chunk)
        if not written:
            raise RuntimeError("Pexels returned an empty video")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"provider": "Pexels", "id": video.get("id"), "page": video.get("url"),
            "creator": video.get("user", {}).get("name"), "bytes": written}


def azure_speech(text: str, target: Path, api_key: str, region: str,
                 voice: str = "zh-TW-HsiaoChenNeural") -> None:
    """Synthesize one phrase to MP3 so caption boundaries use measured audio."""
    if not text.strip() or not api_key:
        raise ValueError("Azure Speech requires narration text and AZURE_SPEECH_KEY")
    if not re.fullmatch(r"[a-z0-9-]{2,30}", region):
        raise ValueError("Set a valid AZURE_SPEECH_REGION")
    if not re.fullmatch(r"zh-TW-[A-Za-z]+Neural", voice):
        raise ValueError("Select an Azure zh-TW neural voice")
    ssml = ("<speak version='1.0' xml:lang='zh-TW'>"
            f"<voice name='{voice}'>{escape(text)}</voice></speak>")
    request = urllib.request.Request(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        data=ssml.encode("utf-8"), method="POST",
        headers={"Ocp-Apim-Subscription-Key": api_key, "Content-Type": "application/ssml+xml",
                 "X-Microsoft-OutputFormat": "audio-24khz-160kbitrate-mono-mp3",
                 "User-Agent": "original-shorts/1.0"})
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".mp3.part")
    try:
        for attempt in range(3):
            try:
                with _open(request, timeout=60) as response:
                    data = response.read(8 * 1024 * 1024 + 1)
                break
            except RuntimeError as exc:
                if "HTTP 429" not in str(exc) or attempt == 2:
                    raise
                print("Azure Speech rate limit reached; retrying after 60 seconds...", flush=True)
                time.sleep(60)
        if not data or len(data) > 8 * 1024 * 1024:
            raise RuntimeError("Azure Speech returned empty or oversized audio")
        temporary.write_bytes(data)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
