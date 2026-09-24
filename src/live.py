"""Render real moving footage with timed, centered subtitles and optional narration.

The storyboard stores timings against the original audio.  A single speed
factor is applied to both narration and all edit points without changing the
playback speed of the footage.  No still-photo camera movement is used.
"""

import hashlib
import json
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path

from .pipeline import save_json
from .video import _digest_file, _duration, _duration_video, _require_ffmpeg, _run

W, H, FPS = 720, 1280, 24
VERSION = "live-v3"


def _asset(folder: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError(f"Invalid storyboard asset name: {name}")
    path = (folder / name).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise ValueError(f"Storyboard asset not found inside {folder}: {name}")
    return path


def _storyboard(path: Path) -> tuple[dict, list[tuple[Path, float, float]], Path | None, float]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read live storyboard {path}: {exc}") from exc
    if not isinstance(plan, dict):
        raise ValueError("Live storyboard must be a JSON object")
    speed = plan.get("audio_speed", 1)
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not .8 <= speed <= 1.5:
        raise ValueError("audio_speed must be between 0.8 and 1.5")
    narration = _asset(path.parent, plan["audio"]) if plan.get("audio") is not None else None
    if not isinstance(plan.get("shots"), list) or not plan["shots"]:
        raise ValueError("Live storyboard needs at least one shot")
    shots = []
    for shot in plan["shots"]:
        if not isinstance(shot, dict):
            raise ValueError("Every shot must be an object")
        start, duration = shot.get("start"), shot.get("duration")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (start, duration)) or start < 0 or duration <= 0:
            raise ValueError("Shot start and duration must be valid positive seconds")
        shots.append((_asset(path.parent, shot.get("file")), float(start), float(duration)))
    timeline = sum(duration for _, _, duration in shots)
    cues = plan.get("captions")
    if not isinstance(cues, list) or not cues:
        raise ValueError("Live storyboard needs timed captions")
    previous = 0.0
    for cue in cues:
        if not isinstance(cue, dict) or not isinstance(cue.get("text"), str) or not cue["text"].strip():
            raise ValueError("Each caption needs nonempty text")
        start, end = cue.get("start"), cue.get("end")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (start, end)) or start < previous - .001 or end <= start:
            raise ValueError("Captions must be ordered without overlap")
        previous = end
    if abs(cues[0]["start"]) > .05 or abs(previous - timeline) > .05:
        raise ValueError("Captions must start at 0 and end with the last shot")
    return plan, shots, narration, float(speed)


def _save_overlay(page, path: Path) -> None:
    from PIL import Image

    pix = page.get_pixmap(alpha=True)
    Image.frombytes("RGBA", (pix.width, pix.height), pix.samples).save(path)


def _common_overlay(script: dict, path: Path) -> None:
    import fitz

    doc = fitz.open()
    try:
        page = doc.new_page(width=W, height=H)
        page.draw_rect(fitz.Rect(35, 53, 309, 96), color=None, fill=(.025, .045, .070), fill_opacity=.70)
        page.insert_text((51, 81), "資料來源", fontsize=19, fontname="china-t", color=(1, 1, 1))
        name = script["source_channel"]
        font = "helv" if name.isascii() else "china-t"
        size = min(20, 145 / max(1, fitz.get_text_length(name, fontname=font, fontsize=1)))
        page.insert_text((151, 82), name, fontsize=size, fontname=font, color=(1, 1, 1))
        page.insert_text((38, 1226), "情境畫面・非原片影像", fontsize=18, fontname="china-t", color=(.94, .94, .94))
        _save_overlay(page, path)
    finally:
        doc.close()


def _caption_layout(caption: str) -> tuple[list[str], int]:
    """Keep short captions on one line and balance longer ones across two or three."""
    import fitz

    paragraphs = caption.split("\n")
    if len(paragraphs) > 3 or any(not line.strip() for line in paragraphs):
        raise ValueError("Caption text must have one to three nonempty lines")
    closing = "，。？！：；、％）】」』,.!?;:%)]}"
    opening = "（【「『([{"

    def width(text: str, size: int) -> float:
        return sum(fitz.get_text_length(part, fontname="helv" if part.isascii() else "china-t", fontsize=size)
                   for part in re.findall(r"[\x00-\x7f]+|[^\x00-\x7f]+", text))

    for size in range(43, 31, -1):
        result = []
        for paragraph_index, paragraph in enumerate(paragraphs):
            paragraph = paragraph.strip()
            limit = 3 - len(result) - (len(paragraphs) - paragraph_index - 1)

            @lru_cache(None)
            def split(start: int, count: int) -> tuple[float, tuple[str, ...]] | None:
                if start == len(paragraph):
                    return (0, ()) if count == 0 else None
                if count == 0:
                    return None
                best = None
                for end in range(start + 1, len(paragraph) + 1):
                    part = paragraph[start:end].strip()
                    if not part or width(part, size) > 650:
                        continue
                    if end < len(paragraph) and (paragraph[end] in closing or paragraph[end - 1] in opening):
                        continue
                    if end < len(paragraph) and paragraph[end - 1].isascii() and paragraph[end].isascii() and paragraph[end - 1].isalnum() and paragraph[end].isalnum():
                        continue
                    tail = split(end, count - 1)
                    if tail is None:
                        continue
                    score = (650 - width(part, size)) ** 2 + tail[0]
                    if end < len(paragraph) and (part[-1] in "，、；：與和及而但" or paragraph[end] in "也又還更"):
                        score -= 35000  # Prefer a clause boundary over splitting a short Chinese word.
                    if best is None or score < best[0]:
                        best = score, (part, *tail[1])
                return best

            layout = next((found[1] for count in range(1, limit + 1)
                           if (found := split(0, count)) is not None), None)
            if layout is None:
                break
            result.extend(layout)
        else:
            return result, size
    raise ValueError(f"Caption cannot fit within three lines: {caption}")


def _caption_overlay(caption: str, path: Path) -> None:
    import fitz

    lines, size = _caption_layout(caption)
    doc = fitz.open()
    try:
        page = doc.new_page(width=W, height=H)
        # PyMuPDF's CJK font spaces out Latin text; measure and paint each run
        # in its own font while keeping the complete line centered.
        runs = [[(part, "helv" if part.isascii() else "china-t") for part in
                 re.findall(r"[\x00-\x7f]+|[^\x00-\x7f]+", line)] for line in lines]
        def paint(dx: int, dy: int, color: tuple[float, float, float]) -> None:
            for row, parts in enumerate(runs):
                width = sum(fitz.get_text_length(part, fontname=font, fontsize=size) for part, font in parts)
                x = (W - width) / 2 + dx
                y = 991 + 51 * row + dy
                for part, font in parts:
                    page.insert_text((x, y), part, fontsize=size, fontname=font, color=color)
                    x += fitz.get_text_length(part, fontname=font, fontsize=size)

        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, -2), (-2, 2), (2, 2)):
            paint(dx, dy, (.04, .05, .06))
        paint(0, 0, (1, 1, 1))
        _save_overlay(page, path)
    finally:
        doc.close()


def render_live(script: dict, output: Path, manifest: Path, force: bool = False) -> tuple[Path, bool]:
    _require_ffmpeg()
    try:
        import fitz  # noqa: F401
        import PIL  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install -r requirements.txt") from exc
    plan, shots, narration, speed = _storyboard(manifest)
    if plan.get("candidate_id") != script["candidate_id"]:
        raise ValueError("Storyboard candidate_id does not match script")
    expected = sum(duration for _, _, duration in shots) / speed
    if narration is not None:
        audio_duration = _duration(narration) / speed
        if abs(expected - audio_duration) > 1:
            raise ValueError(f"Shot timeline ({expected:.2f}s) must match narration ({audio_duration:.2f}s) within 1 second")
    for footage, start, duration in shots:
        source_duration = _duration_video(footage)
        if start + duration > source_duration + .05:
            raise ValueError(f"Shot exceeds available footage: {footage.name}")
    content_hash = hashlib.sha256(json.dumps({
        "script": script, "storyboard": plan, "renderer": VERSION,
        "source_hashes": [_digest_file(clip) for clip, _, _ in shots],
        "narration_hash": _digest_file(narration) if narration else None,
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    sidecar = output.with_suffix(".render.json")
    if not force and output.is_file() and sidecar.is_file():
        try:
            if json.loads(sidecar.read_text(encoding="utf-8")).get("cache_key") == content_hash:
                return output, True
        except ValueError:
            pass
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="live-render-", dir=output.parent) as temp:
        work = Path(temp)
        common = work / "common.png"
        _common_overlay(script, common)
        encoded = []
        for index, (footage, start, duration) in enumerate(shots):
            destination = work / f"shot_{index:02}.mp4"
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start),
                  "-i", str(footage), "-loop", "1", "-i", str(common),
                  "-filter_complex", "[0:v]scale=720:1280:force_original_aspect_ratio=increase,"
                  "crop=720:1280,fps=24,format=yuv420p[v];"
                  "[v][1:v]overlay=0:0:format=auto,format=yuv420p[out]",
                  "-map", "[out]", "-an", "-t", str(duration / speed), "-r", str(FPS),
                  "-c:v", "libx264", "-crf", "21", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(destination)])
            encoded.append(destination)
        concat = work / "shots.ffconcat"
        concat.write_text("ffconcat version 1.0\n" + "\n".join(f"file '{p.name}'" for p in encoded) + "\n", encoding="utf-8")
        base = work / "base.mp4"
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
              "-i", str(concat), "-c", "copy", str(base)])
        input_args = ["-i", str(base)]
        for index, cue in enumerate(plan["captions"]):
            caption = work / f"caption_{index:02}.png"
            _caption_overlay(cue["text"], caption)
            input_args += ["-loop", "1", "-i", str(caption)]
        if narration is not None:
            input_args += ["-i", str(narration)]
        chains = []
        for index, cue in enumerate(plan["captions"]):
            source = "[0:v]" if index == 0 else f"[v{index}]"
            chains.append(f"{source}[{index+1}:v]overlay=0:0:enable='gte(t,{cue['start']/speed})*"
                          f"lt(t,{cue['end']/speed})':format=auto[v{index+1}]")
        filters = ";".join(chains)
        audio_args = ["-an"]
        if narration is not None:
            audio_index = len(plan["captions"]) + 1
            filters += f";[{audio_index}:a]atempo={speed},loudnorm=I=-16:TP=-1.5:LRA=11,apad=pad_dur=1[a]"
            audio_args = ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
        finished = work / "short.mp4"
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *input_args,
              "-filter_complex", filters, "-map", f"[v{len(plan['captions'])}]", *audio_args,
              "-t", str(expected), "-r", str(FPS), "-c:v", "libx264", "-crf", "21",
              "-preset", "veryfast", "-pix_fmt", "yuv420p",
              "-movflags", "+faststart", str(finished)])
        actual = _duration_video(finished)
        if abs(actual - expected) > .15:
            raise RuntimeError(f"Unexpected live output length: expected {expected:.2f}s, got {actual:.2f}s")
        os.replace(finished, output)
    save_json(sidecar, {"cache_key": content_hash, "renderer": VERSION,
                        "candidate_id": script["candidate_id"], "source_url": script["source_url"],
                        "audio_speed": speed, "video_duration_seconds": round(actual, 2),
                        "generation_api_cost_usd": 0, "review_status": script["review_status"]})
    return output, False
