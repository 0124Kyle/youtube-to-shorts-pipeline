"""Plan draft edits using a curated local clip catalog and offline narration.

This module never fetches media. Missing themes require catalog expansion or
manual review; provided whole-track audio has approximate caption timings.
Per-phrase Windows TTS gives exact phrase boundaries.
"""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from .external_media import azure_speech
from .live import render_live
from .video import _digest_file, _duration, _duration_video, _load_script, _phrases, _run, _windows_tts


def _catalog(path: Path) -> list[tuple[Path, list[str], float]]:
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read local footage catalog {path}: {exc}") from exc
    if not isinstance(source, dict) or not isinstance(source.get("clips"), list) or not source["clips"]:
        raise ValueError("Footage catalog needs a nonempty clips list")
    clips = []
    for item in source["clips"]:
        name = item.get("file") if isinstance(item, dict) else None
        tags = item.get("tags") if isinstance(item, dict) else None
        if not isinstance(name, str) or not isinstance(tags, list) or not tags or any(not isinstance(t, str) or not t for t in tags):
            raise ValueError("Every catalog entry needs a local file and nonempty string tags")
        file = (path.parent / name).resolve()
        if not file.is_relative_to(path.parent.resolve()) or not file.is_file():
            raise ValueError(f"Catalog clip must exist inside {path.parent}: {name}")
        clips.append((file, tags, _duration_video(file)))
    return clips


def _choose_clips(phrases: list[str], clips: list[tuple[Path, list[str], float]]) -> list[int]:
    """Prefer explicit phrase tags; carry the previous subject over neutral phrases."""
    selected = []
    matched = 0
    for phrase in phrases:
        scores = [sum(len(tag) for tag in tags if tag in phrase) for _, tags, _ in clips]
        best = max(scores)
        if best:
            matched += 1
            ties = [i for i, score in enumerate(scores) if score == best]
            selected.append(ties[len(selected) % len(ties)])
        else:
            selected.append(selected[-1] if selected else 0)
    if matched / len(phrases) < .5:
        raise ValueError(f"The local footage catalog matches only {matched}/{len(phrases)} script phrases; add relevant clips and tags before generating this topic")
    return selected


def _narration(script: dict, phrases: list[str], folder: Path, audio: Path | None, tts: bool,
               force: bool, azure_tts: bool = False, azure_voice: str = "zh-TW-HsiaoChenNeural") -> tuple[Path, list[float], str]:
    if audio:
        target = folder / f"narration{audio.suffix.lower()}"
        if target != audio:
            if force or not target.exists() or _digest_file(target) != _digest_file(audio):
                shutil.copy2(audio, target)
        length = _duration(target)
        weights = [max(len(re.sub(r"\W", "", phrase)), 5) for phrase in phrases]
        return target, [length * weight / sum(weights) for weight in weights], "estimated_from_character_length"
    if not tts and not azure_tts:
        raise ValueError("Provide narration audio, --tts, or --azure-tts")
    provider = "azure" if azure_tts else "windows"
    cache_key = hashlib.sha256(json.dumps({"phrases": phrases, "provider": provider, "voice": azure_voice if azure_tts else "system-zh"},
                                          ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    target = folder / "narration.wav"
    lengths_file = folder / "narration.timings.json"
    if not force and target.is_file() and lengths_file.is_file():
        saved = json.loads(lengths_file.read_text(encoding="utf-8"))
        if saved.get("key") == cache_key:
            return target, saved["lengths"], f"phrase_tts_{provider}"
    with tempfile.TemporaryDirectory(prefix="tts-", dir=folder) as temp:
        work = Path(temp)
        segments = []
        lengths = []
        cache = folder / "phrase-cache"
        cache.mkdir(exist_ok=True)
        for i, phrase in enumerate(phrases):
            segment = work / f"phrase_{i:03}.wav"
            if azure_tts:
                phrase_key = hashlib.sha256(f"{azure_voice}\n{phrase}".encode()).hexdigest()
                mp3 = cache / f"{phrase_key}.mp3"
                if not mp3.is_file():
                    azure_speech(phrase, mp3, os.environ["AZURE_SPEECH_KEY"],
                                 os.environ["AZURE_SPEECH_REGION"], azure_voice)
                _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3),
                      "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(segment)])
            else:
                _windows_tts(phrase, segment, work)
            segments.append(segment)
            lengths.append(_duration_video(segment))
        listing = work / "phrases.ffconcat"
        listing.write_text("ffconcat version 1.0\n" + "\n".join(f"file '{segment.name}'" for segment in segments) + "\n", encoding="utf-8")
        assembled = work / "joined.wav"
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
              "-i", str(listing), "-c:a", "pcm_s16le", str(assembled)])
        shutil.copy2(assembled, target)
    lengths_file.write_text(json.dumps({"key": cache_key, "lengths": lengths}), encoding="utf-8")
    return target, lengths, f"phrase_tts_{provider}"


def _plan(script: dict, clips: list[tuple[Path, list[str], float]], folder: Path,
          audio: Path | None, tts: bool, speed: float, force: bool,
          azure_tts: bool = False, azure_voice: str = "zh-TW-HsiaoChenNeural",
          selection_override: list[int] | None = None, silent: bool = False) -> Path:
    if not .8 <= speed <= 1.5:
        raise ValueError("--speed must be between 0.8 and 1.5")
    folder.mkdir(parents=True, exist_ok=True)
    phrases = _phrases(script["narration"])
    if any(len(phrase) > 70 for phrase in phrases):
        raise ValueError("A narration phrase is too long to place in a readable caption")
    selection = _choose_clips(phrases, clips) if selection_override is None else selection_override
    if len(selection) != len(phrases) or any(index < 0 or index >= len(clips) for index in selection):
        raise ValueError("The storyboard needs one valid video clip per narration phrase")
    if silent:
        narration = None
        lengths = [max(2.5, len(re.sub(r"\s", "", phrase)) / 4.2) for phrase in phrases]
        timing_method = "estimated_reading_time"
    else:
        narration, lengths, timing_method = _narration(script, phrases, folder, audio, tts, force, azure_tts, azure_voice)
        if _duration(narration) < len(phrases) * .7:
            raise ValueError("Narration is too short for its script")
    shots, cues = [], []
    clock = 0.0
    for i, (phrase, clip_index, length) in enumerate(zip(phrases, selection, lengths)):
        source, _, available = clips[clip_index]
        target = folder / f"clip_{clip_index:02}.mp4"
        if force or not target.is_file() or _digest_file(target) != _digest_file(source):
            shutil.copy2(source, target)
        # A short video can repeat at a different in-point if narration runs longer.
        remaining = length
        while remaining > .0001:
            take = min(remaining, max(.1, available - .5), 6.0)
            if take <= 0 or available < take:
                raise ValueError(f"Footage is too short: {source.name}")
            start = 0.0 if available <= take + .1 else min(2.0 + (i % 3) * .3, available - take)
            shots.append({"file": target.name, "start": round(start, 4), "duration": round(take, 6)})
            remaining -= take
        cues.append({"start": round(clock, 6), "end": round(clock + length, 6), "text": phrase})
        clock += length
    plan = {"candidate_id": script["candidate_id"], "audio": narration.name if narration else None, "audio_speed": speed,
            "timing_method": timing_method,
            "selection_method": "ordered_script_visual_plan" if selection_override is not None else "local_keyword_tags",
            "shots": shots, "captions": cues}
    path = folder / "storyboard.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def render_planned(script_path: Path, footage: list[Path], work_dir: Path,
                   output_dir: Path, voice: str, speed: float, narrate: bool = False) -> tuple[Path, bool]:
    """Render the generated script with clips in the model's visual-plan order."""
    if not footage:
        raise ValueError("No footage was found for this script")
    if narrate and not all(os.environ.get(key) for key in ("AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION")):
        raise ValueError("Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION in .env")
    script = _load_script(script_path)
    clips = [(path, [], _duration_video(path)) for path in footage]
    phrases = _phrases(script["narration"])
    selection = [min(len(clips) - 1, i * len(clips) // len(phrases)) for i in range(len(phrases))]
    plan = _plan(script, clips, work_dir / script["video_id"] / script["candidate_id"], None, False,
                 speed, False, narrate, voice, selection, silent=not narrate)
    suffix = "_preview" if script["review_status"] != "approved" else ""
    destination = output_dir / script["video_id"] / f"{script['candidate_id']}{suffix}.mp4"
    return render_live(script, destination, plan)


def render_auto(scripts: Path, catalog: Path, work_dir: Path, output_dir: Path,
                audio_dir: Path | None, tts: bool, speed: float = 1.,
                force: bool = False, azure_tts: bool = False,
                azure_voice: str = "zh-TW-HsiaoChenNeural") -> list[tuple[Path, bool]]:
    paths = sorted(scripts.glob("script_*.json")) if scripts.is_dir() else [scripts] if scripts.is_file() else []
    if not paths:
        raise ValueError(f"No script JSON files found: {scripts}")
    if audio_dir is not None and not audio_dir.is_dir():
        raise ValueError(f"Narration folder not found: {audio_dir}")
    if sum((audio_dir is not None, tts, azure_tts)) != 1:
        raise ValueError("Select exactly one of --audio-dir, --tts or --azure-tts")
    if tts and sys.platform != "win32":
        raise RuntimeError("Local Chinese System.Speech TTS needs Windows; on this system provide narration files with --audio-dir")
    if azure_tts and not all(os.environ.get(name) for name in ("AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION")):
        raise ValueError("Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION for --azure-tts")
    clips = _catalog(catalog)
    loaded = [_load_script(path) for path in paths]
    if len({script["candidate_id"] for script in loaded}) != len(loaded):
        raise ValueError("Script folder contains duplicate candidate IDs")
    results = []
    for script in loaded:
        key = script["candidate_id"]
        audio = None
        if audio_dir:
            matches = [audio_dir / f"{key}.{ext}" for ext in ("wav", "mp3", "m4a") if (audio_dir / f"{key}.{ext}").is_file()]
            if len(matches) != 1:
                raise ValueError(f"Expected exactly one {key}.wav/.mp3/.m4a in {audio_dir}")
            audio = matches[0]
        plan = _plan(script, clips, work_dir / key, audio, tts, speed, force, azure_tts, azure_voice)
        suffix = "_preview" if script["review_status"] != "approved" else ""
        destination = output_dir / script["video_id"] / f"{key}{suffix}.mp4"
        results.append(render_live(script, destination, plan, force))
    return results
