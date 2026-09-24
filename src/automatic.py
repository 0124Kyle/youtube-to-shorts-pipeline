"""One-command pipeline: source video to attributed review drafts with moving footage."""

import json
import os
from pathlib import Path

from .auto_live import render_planned
from .external_media import pexels_download, pexels_search
from .pipeline import read_json, run as transcribe_video, save_json
from .rewrite import DEFAULT_MODEL, plan_and_generate
from .video import _duration_video
from .youtube import parse_video_id


def _ready_env(narrate: bool = False) -> None:
    required = ("GEMINI_API_KEY", "PEXELS_API_KEY") + (("AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION") if narrate else ())
    missing = [name for name in required
               if not os.environ.get(name) or os.environ[name].startswith("replace_with_")]
    if missing:
        raise ValueError("Set these values in .env before running the pipeline: " + ", ".join(missing))


def _select_video(candidates: list[dict], used: set[int]) -> dict | None:
    """Keep the API relevance ranking while requiring a usable portrait MP4."""
    for video in candidates:
        if not isinstance(video, dict) or not isinstance(video.get("id"), int) or video["id"] in used:
            continue
        if not isinstance(video.get("duration"), (int, float)) or video["duration"] < 4:
            continue
        if any(isinstance(item, dict) and item.get("file_type") == "video/mp4" and
               isinstance(item.get("width"), int) and isinstance(item.get("height"), int) and
               item["height"] > item["width"] and isinstance(item.get("link"), str)
               for item in video.get("video_files", [])):
            return video
    return None


def get_script_footage(script: dict, data_dir: Path) -> list[Path]:
    queries = script.get("stock_queries")
    if not isinstance(queries, list) or not 2 <= len(queries) <= 3 or not all(isinstance(q, str) and q.strip() for q in queries):
        raise ValueError("Script is missing 2–3 stock_queries; regenerate it with the current pipeline")
    review_path = data_dir / "auto-live" / script["video_id"] / script["candidate_id"] / "footage_sources.json"
    saved = read_json(review_path)
    if saved and saved.get("queries") == queries and isinstance(saved.get("clips"), list) and len(saved["clips"]) == len(queries):
        cached = [Path(item["file"]) for item in saved["clips"]
                  if isinstance(item, dict) and isinstance(item.get("file"), str)]
        stock_dir = (data_dir / "stock").resolve()
        if len(cached) == len(queries) and all(path.resolve().is_relative_to(stock_dir) and path.is_file() and
                                               path.stat().st_size > 0 and _duration_video(path) >= 3 for path in cached):
            print(f"Reusing {len(cached)} reviewed-source clips for {script['candidate_id']}", flush=True)
            return cached
    footage, sources, used = [], [], set()
    for query in queries:
        print(f"Searching moving footage: {query}", flush=True)
        chosen, matched_query = None, query
        shorter = " ".join(query.split()[:3])
        attempts = [query] + ([shorter] if shorter != query else [])
        for attempt in attempts:
            candidates = pexels_search(attempt, os.environ["PEXELS_API_KEY"], data_dir / "stock-cache", max_results=5)
            chosen = _select_video(candidates, used)
            if chosen is not None:
                matched_query = attempt
                break
        if chosen is None:
            raise ValueError(f"No distinct portrait footage of at least 4 seconds found for '{query}'. The generated search terms need review")
        video_id = chosen["id"]
        used.add(video_id)
        destination = data_dir / "stock" / f"pexels_{video_id}.mp4"
        provenance_path = destination.with_suffix(".source.json")
        if not destination.is_file() or destination.stat().st_size == 0:
            print(f"Downloading Pexels video {video_id}...", flush=True)
            provenance = pexels_download(chosen, destination)
            save_json(provenance_path, provenance)
        else:
            provenance = {"provider": "Pexels", "id": video_id,
                          "page": chosen.get("url"), "creator": chosen.get("user", {}).get("name")}
            if not provenance_path.is_file():
                save_json(provenance_path, provenance)
        if _duration_video(destination) < 3:
            raise ValueError(f"Downloaded footage is too short: {destination}")
        footage.append(destination)
        sources.append({"script_query": query, "search_query": matched_query,
                        "file": str(destination), "source": provenance})
    review_path.parent.mkdir(parents=True, exist_ok=True)
    save_json(review_path, {"video_id": script["video_id"], "candidate_id": script["candidate_id"],
                            "queries": queries,
                            "selection_method": "first_valid_pexels_result_per_script_scene",
                            "clips": sources, "review_status": "needs_human_review"})
    return footage


def run_pipeline(url: str, data_dir: Path = Path("data"), count: int = 2,
                 model: str = DEFAULT_MODEL, speed: float = 1.12,
                 voice: str = "zh-TW-HsiaoChenNeural", narrate: bool = False) -> list[tuple[Path, bool]]:
    if not 1 <= count <= 3 or not .8 <= speed <= 1.5:
        raise ValueError("--count must be 1–3 and --speed must be 0.8–1.5")
    video_id = parse_video_id(url)
    _ready_env(narrate)  # Fail before a long download or a paid model call.
    print("1/3 Downloading audio and transcribing (existing results are reused)...", flush=True)
    transcript, _ = transcribe_video(url, data_dir, language="zh")
    source_dir = data_dir / video_id
    print(f"2/3 Selecting and rewriting up to {count} short scripts...", flush=True)
    _, scripts = plan_and_generate(transcript, source_dir / "metadata.json",
                                   source_dir / "rewrite", generate=True, top=count, model=model)
    output = []
    print("3/3 Fetching footage and rendering drafts...", flush=True)
    for path in scripts:  # The exact returned paths avoid stale duplicate candidate IDs.
        script = json.loads(path.read_text(encoding="utf-8"))
        print(f"Draft {script['candidate_id']}: {script['title']}", flush=True)
        footage = get_script_footage(script, data_dir)
        output.append(render_planned(path, footage, data_dir / "auto-live",
                                     data_dir / "auto-shorts", voice, speed, narrate=narrate))
    return output
