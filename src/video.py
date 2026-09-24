"""Cost-free, source-footage-free short rendering from script JSON files.

PyMuPDF's built-in CJK font paints original cards. FFmpeg encodes the cards
and either generated silence, supplied narration, or an optional OS voice.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .pipeline import save_json

WIDTH, HEIGHT = 720, 1280
VERSION = "motion-v1"
PALETTES = [
    ((0.055, 0.080, 0.15), (0.36, 0.86, 0.83)),
    ((0.085, 0.075, 0.17), (0.94, 0.64, 0.52)),
    ((0.055, 0.12, 0.16), (0.95, 0.79, 0.43)),
]


def _run(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, errors="replace")
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed: {result.stderr.strip()[-1200:] or result.stdout.strip()[-1200:]}")
    return result.stdout


def _require_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if not missing:
        return
    detail = ", ".join(missing)
    if sys.platform == "win32":
        raise RuntimeError(
            f"Missing executable(s): {detail}. pip requirements install Python packages, not FFmpeg. "
            "In PowerShell run: winget install --id Gyan.FFmpeg --exact --source winget; "
            "then reopen PowerShell and check: ffmpeg -version and ffprobe -version. "
            "If already installed, add the folder containing ffmpeg.exe and ffprobe.exe to PATH."
        )
    raise RuntimeError(
        f"Missing executable(s): {detail}. Install FFmpeg with your OS package manager "
        "and check that ffmpeg -version and ffprobe -version both work in this terminal."
    )


def _duration(media: Path) -> float:
    _require_ffmpeg()
    info = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(media)])
    try:
        seconds = float(info.strip())
    except ValueError as exc:
        raise ValueError(f"Cannot read audio duration: {media}") from exc
    if not 5 <= seconds <= 120:
        raise ValueError(f"Narration audio must be 5–120 seconds: {media} ({seconds:.1f}s)")
    return seconds


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_script(path: Path) -> dict:
    try:
        item = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid script JSON {path}: {exc}") from exc
    if not isinstance(item, dict):
        raise ValueError(f"Script must be a JSON object: {path}")
    for key in ("candidate_id", "title", "narration", "source_channel", "source_url", "video_id"):
        if not isinstance(item.get(key), str) or not item[key].strip():
            raise ValueError(f"{path}: missing {key}")
    interval = item.get("source_interval")
    if not isinstance(interval, dict) or not all(isinstance(interval.get(k), (int, float)) for k in ("start", "end")) or interval["start"] < 0 or interval["end"] <= interval["start"]:
        raise ValueError(f"{path}: invalid source_interval")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", item["candidate_id"]):
        raise ValueError(f"{path}: unsafe candidate_id")
    if len(item["narration"]) > 1200 or len(item["title"]) > 120:
        raise ValueError(f"{path}: script is too long for a Short")
    if item.get("review_status") not in ("approved", "needs_human_review"):
        raise ValueError(f"{path}: review_status must be approved or needs_human_review")
    if not item["source_url"].startswith(("https://", "http://")):
        raise ValueError(f"{path}: source_url must be an HTTP(S) URL")
    return item


def _phrases(narration: str) -> list[str]:
    # A card stays up for each short spoken phrase. Keep punctuation in captions.
    text = re.sub(r"\s+", " ", narration.strip())
    sections = [s.strip() for s in re.findall(r"[^，。！？；;!?]+[，。！？；;!?]?", text) if s.strip()]
    chunks = []
    for section in sections:
        while len(section) > 26:
            chunks.append(section[:22].strip())
            section = section[22:].strip()
        if section:
            chunks.append(section)
    return chunks or [text]


def _draw_original_scene(page, script: dict, accent: tuple[float, float, float]) -> None:
    """Decorative vector houses/cityscape, never source imagery or data charts."""
    import fitz

    # Keep the illustration faint behind captions so a longer sentence remains readable.
    ink = tuple(min(1, v * .55 + .24) for v in accent)
    if script["candidate_id"] == "c05":
        page.draw_line((472, 748), (550, 685), color=ink, width=8, stroke_opacity=.22)
        page.draw_line((550, 685), (636, 748), color=ink, width=8, stroke_opacity=.22)
        page.draw_rect(fitz.Rect(486, 746, 621, 903), color=ink, width=7, stroke_opacity=.22)
        page.draw_rect(fitz.Rect(541, 832, 575, 903), color=ink, width=6, stroke_opacity=.22)
    elif script["candidate_id"] == "c10":
        for x, top, wide in ((420, 768, 47), (481, 718, 55), (553, 802, 60)):
            page.draw_rect(fitz.Rect(x, top, x + wide, 902), color=ink, width=6, stroke_opacity=.22)
            for y in range(top + 29, 890, 33):
                page.draw_line((x + 13, y), (x + wide - 12, y), color=ink, width=4, stroke_opacity=.22)
        page.draw_line((395, 905), (638, 905), color=ink, width=5, stroke_opacity=.22)
    else:
        page.draw_rect(fitz.Rect(437, 813, 485, 904), color=ink, width=6, stroke_opacity=.22)
        page.draw_rect(fitz.Rect(499, 744, 557, 904), color=ink, width=6, stroke_opacity=.22)
        page.draw_rect(fitz.Rect(571, 785, 621, 904), color=ink, width=6, stroke_opacity=.22)
        page.draw_line((415, 907), (642, 907), color=ink, width=5, stroke_opacity=.22)


def _card(script: dict, caption: str, index: int, total: int, preview: bool, target: Path, closing: bool = False) -> None:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install -r requirements.txt") from exc
    bg, accent = PALETTES[(index // max(1, total // 3)) % len(PALETTES)]
    doc = fitz.open()
    try:
        page = doc.new_page(width=WIDTH, height=HEIGHT)
        page.draw_rect(page.rect, color=bg, fill=bg, overlay=False)
        page.draw_rect(fitz.Rect(62, 132, 72, 203), color=accent, fill=accent)
        page.draw_rect(fitz.Rect(60, 405, 660, 407), color=accent, fill=accent)
        page.draw_rect(fitz.Rect(60, 950, 660, 952), color=accent, fill=accent)
        page.draw_rect(fitz.Rect(60, 977, 60 + 600 * (index + 1) / max(total, 1), 983), color=accent, fill=accent)
        if not closing:
            _draw_original_scene(page, script, accent)
        page.insert_text((88, 175), "ORIGINAL SHORT", fontsize=21, fontname="hebo", color=accent)
        if preview:
            page.insert_textbox(fitz.Rect(420, 148, 665, 201), "草稿預覽・待核對", fontsize=20, fontname="china-t", color=(1, 0.79, 0.48))
        for size in (46, 41, 36):
            if page.insert_textbox(fitz.Rect(62, 234, 658, 397), script["title"], fontsize=size, fontname="china-t", color=(1, 1, 1), lineheight=1.26) >= 0:
                break
        else:
            raise ValueError("Short title does not fit on a card")
        if closing:
            page.insert_text((62, 515), "SOURCE", fontsize=28, fontname="hebo", color=accent)
            page.insert_text((230, 515), "原始資料", fontsize=28, fontname="china-t", color=accent)
            source_font = "hebo" if script["source_channel"].isascii() else "china-t"
            page.insert_textbox(fitz.Rect(62, 605, 655, 780), script["source_channel"], fontsize=48, fontname=source_font, color=(1, 1, 1))
            page.insert_text((62, 840), "片段位置：", fontsize=27, fontname="china-t", color=(0.83, 0.87, 0.94))
            page.insert_text((240, 840), _stamp(script["source_interval"]["start"]) + " - " + _stamp(script["source_interval"]["end"]), fontsize=27, fontname="hebo", color=(0.83, 0.87, 0.94))
        else:
            for size in (54, 48, 42):
                if page.insert_textbox(fitz.Rect(62, 505, 657, 925), caption, fontsize=size, fontname="china-t", color=(1, 1, 1), lineheight=1.33) >= 0:
                    break
            else:
                raise ValueError("A narration caption does not fit on a card")
        page.insert_text((62, 1035), "來源頻道 /", fontsize=25, fontname="china-t", color=(0.84, 0.88, 0.93))
        source_font = "hebo" if script["source_channel"].isascii() else "china-t"
        page.insert_text((270, 1035), script["source_channel"], fontsize=25, fontname=source_font, color=(0.84, 0.88, 0.93))
        page.insert_text((62, 1075), script["source_url"], fontsize=16, fontname="helv", color=(0.73, 0.79, 0.84))
        page.get_pixmap(alpha=False).save(str(target))
    finally:
        doc.close()


def _stamp(seconds: float) -> str:
    n = round(seconds)
    return f"{n // 60:02d}:{n % 60:02d}"


def _windows_tts(text: str, output: Path, temp: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("--tts currently supports Windows System.Speech. Use --audio-dir for narration, or omit --tts for a silent subtitle preview.")
    if not shutil.which("powershell.exe"):
        raise RuntimeError("Windows PowerShell was not found; use --audio-dir or a silent preview")
    (temp / "speech.json").write_text(json.dumps({"narration": text}, ensure_ascii=False), encoding="utf-8")
    program = """$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$text = (Get-Content -LiteralPath $args[0] -Raw -Encoding UTF8 | ConvertFrom-Json).narration
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $voice = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'zh-TW' -or $_.VoiceInfo.Culture.Name -eq 'zh-CN' } | Select-Object -First 1
  if (-not $voice) { throw 'No installed Chinese System.Speech voice. Install one, or use --audio-dir.' }
  $synth.SelectVoice($voice.VoiceInfo.Name)
  $synth.SetOutputToWaveFile($args[1])
  $synth.Speak([string]$text)
} finally { $synth.Dispose() }
"""
    script = temp / "speech.ps1"
    script.write_text(program, encoding="utf-8-sig")
    _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), str(temp / "speech.json"), str(output)])


def _render_one(script: dict, output: Path, audio: Path | None, tts: bool, seconds: int, force: bool) -> tuple[Path, bool]:
    _require_ffmpeg()
    mode = "tts" if tts else "provided" if audio else "silent"
    key = hashlib.sha256(json.dumps({"script": script, "version": VERSION, "audio_mode": mode,
                                      "audio_sha256": _digest_file(audio) if audio else None, "seconds": seconds},
                                     sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    meta = output.with_suffix(".render.json")
    if not force and output.is_file() and meta.is_file():
        try:
            if json.loads(meta.read_text(encoding="utf-8")).get("cache_key") == key:
                return output, True
        except ValueError:
            pass
    phrases = _phrases(script["narration"])
    output.parent.mkdir(parents=True, exist_ok=True)
    end_seconds = 3.5
    with tempfile.TemporaryDirectory(prefix="short-render-", dir=output.parent) as scratch:
        work = Path(scratch)
        narration = audio
        if tts:
            narration = work / "narration.wav"
            _windows_tts(script["narration"], narration, work)
        spoken = _duration(narration) if narration else seconds - end_seconds
        if spoken < len(phrases) * .7:
            raise ValueError("Narration audio is too short for the amount of script text")
        weights = [max(len(re.sub(r"\W", "", item)), 5) for item in phrases]
        timings = [spoken * weight / sum(weights) for weight in weights]
        timing_file = work / "frames.ffconcat"
        lines = ["ffconcat version 1.0"]
        preview = script["review_status"] != "approved"
        for index, (phrase, duration) in enumerate(zip(phrases, timings)):
            picture = f"card_{index:03d}.png"
            _card(script, phrase, index, len(phrases) + 1, preview, work / picture)
            lines.extend([f"file '{picture}'", f"duration {duration:.6f}"])
        closing = f"card_{len(phrases):03d}.png"
        _card(script, "", len(phrases), len(phrases) + 1, preview, work / closing, closing=True)
        lines.extend([f"file '{closing}'", f"duration {end_seconds:.6f}", f"file '{closing}'"])
        timing_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temp_output = work / "short.mp4"
        inputs = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-safe", "0", "-f", "concat", "-i", str(timing_file)]
        if narration:
            inputs += ["-i", str(narration), "-af", "apad"]
        else:
            inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        duration_total = spoken + end_seconds
        # Duplicate timed cards into video frames, then animate a gentle camera move.
        # Source credit remains inside a safe margin throughout the movement.
        motion = "fps=12,zoompan=z='1.04+0.015*sin(on/15)':d=1:x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':s=720x1280:fps=12"
        command = inputs + ["-map", "0:v:0", "-map", "1:a:0", "-vf", motion, "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
                            "-pix_fmt", "yuv420p", "-r", "12", "-c:a", "aac", "-b:a", "96k", "-t", f"{duration_total:.3f}",
                            "-movflags", "+faststart", str(temp_output)]
        _run(command, work)
        actual = _duration_video(temp_output)
        if abs(actual - duration_total) > 1.5:
            raise RuntimeError(f"Unexpected output duration: expected {duration_total:.1f}s, got {actual:.1f}s")
        os.replace(temp_output, output)
    save_json(meta, {"cache_key": key, "renderer": VERSION, "source_url": script["source_url"],
                     "candidate_id": script["candidate_id"], "audio_mode": mode,
                     "video_duration_seconds": round(actual, 2), "generation_api_cost_usd": 0,
                     "review_status": script["review_status"]})
    return output, False


def _duration_video(path: Path) -> float:
    return float(_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]).strip())


def render_many(scripts_path: Path, output_dir: Path, audio_dir: Path | None = None, tts: bool = False,
                seconds: int = 48, force: bool = False, style: str = "film",
                music: Path | None = None, assets_dir: Path = Path("assets/film"),
                live_dir: Path = Path("assets/live")) -> list[tuple[Path, bool]]:
    if not 20 <= seconds <= 90:
        raise ValueError("--seconds must be between 20 and 90")
    if scripts_path.is_dir():
        paths = sorted(scripts_path.glob("script_*.json"))
    elif scripts_path.is_file():
        paths = [scripts_path]
    else:
        paths = []
    if not paths:
        raise ValueError(f"No script JSON files found: {scripts_path}")
    if audio_dir is not None and not audio_dir.is_dir():
        raise ValueError(f"Audio folder does not exist: {audio_dir}")
    if style not in ("live", "film", "promo", "cards"):
        raise ValueError("--style must be live, film, promo or cards")
    if style == "live" and (audio_dir or tts or music):
        raise ValueError("Live narration and timing come from the storyboard; do not pass --audio-dir, --tts or --music")
    if music and style == "cards":
        raise ValueError("--music is supported only with --style film or promo")
    output_dir = output_dir.resolve()
    if audio_dir is not None:
        audio_dir = audio_dir.resolve()
    loaded = [_load_script(p) for p in paths]
    ids = [s["candidate_id"] for s in loaded]
    if len(ids) != len(set(ids)):
        raise ValueError("Script folder contains duplicate candidate IDs")
    results = []
    for item in loaded:
        key = item["candidate_id"]
        audio = None
        if audio_dir:
            matches = [audio_dir / f"{key}.{ext}" for ext in ("wav", "mp3", "m4a") if (audio_dir / f"{key}.{ext}").is_file()]
            if len(matches) != 1:
                raise ValueError(f"Expected one narration audio file named {key}.wav, .mp3 or .m4a in {audio_dir}")
            audio = matches[0]
        suffix = "_preview" if item["review_status"] != "approved" else ""
        destination = output_dir / item["video_id"] / f"{key}{suffix}.mp4"
        print(f"Rendering {destination.name} ({style}, {'narration audio' if audio or tts else 'subtitle preview'})...", flush=True)
        if style == "live":
            from .live import render_live
            results.append(render_live(item, destination, live_dir / key / "storyboard.json", force))
        elif style in ("film", "promo"):
            from .promo import render_promo
            results.append(render_promo(item, destination, audio, tts, seconds, force, music,
                                        style=style, assets_dir=assets_dir))
        else:
            results.append(_render_one(item, destination, audio, tts, seconds, force))
    return results
