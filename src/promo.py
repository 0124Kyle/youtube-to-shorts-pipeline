"""Procedural, footage-free motion scenes for a vertical editorial promo."""

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .pipeline import save_json
from .video import _digest_file, _duration, _duration_video, _phrases, _require_ffmpeg, _run, _stamp, _windows_tts

W, H, FPS = 540, 960, 15
VERSION = "promo-v1"
PALETTES = {
    "c05": ((9, 19, 40), (35, 105, 127), (234, 186, 99)),
    "c10": ((11, 32, 48), (33, 105, 113), (245, 176, 122)),
    "c15": ((14, 25, 49), (61, 82, 136), (137, 217, 206)),
}
MOTIFS = {
    "c05": ("city", "home", "calendar", "budget"),
    "c10": ("harbor", "crane", "home", "budget"),
    "c15": ("city", "crane", "city", "budget"),
}
LABELS = {
    "c05": ("入住想像", "長期房貸", "寬限期", "生活預算"),
    "c10": ("安平港灣", "新案供給", "換屋需求", "每月負擔"),
    "c15": ("城市變化", "推案觀察", "區域差異", "每月負擔"),
}


def _blend(a, b, amount):
    return tuple(round(x * (1 - amount) + y * amount) for x, y in zip(a, b))


def _background(dark, mid):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(image)
    for y in range(H):
        k = y / H
        color = _blend(dark, mid, .14 + .58 * k)
        draw.line((0, y, W, y), fill=color)
    return image


def _city(draw, t, accent, low=False):
    offset = t * (9 if low else 15)
    horizon = 560 if not low else 615
    draw.ellipse((-145 + 8 * math.sin(t / 3), 75, 310, 530), fill=(38, 83, 112))
    draw.ellipse((-85, 125, 235, 440), fill=(58, 118, 134))
    for i in range(-1, 11):
        x = int(i * 73 - offset % 73)
        top = horizon - (130 + ((i * 41 + 31) % 180))
        color = (20, 52, 79) if i % 2 else (25, 60, 85)
        draw.rectangle((x, top, x + 55, H), fill=color)
        for wy in range(top + 23, H, 24):
            for wx in range(x + 10, x + 53, 18):
                if (i + wx // 18 + wy // 24) % 4:
                    draw.rounded_rectangle((wx, wy, wx + 7, wy + 10), radius=2,
                                           fill=_blend(color, accent, .42))
    draw.polygon([(0, 790), (W, 755), (W, H), (0, H)], fill=(8, 28, 48))
    for j in range(8):
        x = ((j * 93 + t * 38) % (W + 100)) - 100
        draw.line((x, 860, x + 35, 850), fill=_blend(accent, (15, 38, 57), .48), width=3)


def _home(draw, t, accent):
    # A small physical house, trees and warm windows, rather than a text panel.
    draw.ellipse((-110, 505, 660, 1070), fill=(25, 69, 84))
    draw.ellipse((-75, 650, 620, 1100), fill=(18, 57, 71))
    draw.polygon([(77, 573), (266, 440 + 5 * math.sin(t)), (455, 573)], fill=(44, 89, 103))
    draw.line([(77, 573), (266, 440 + 5 * math.sin(t)), (455, 573)], fill=accent, width=10, joint="curve")
    draw.rounded_rectangle((112, 569, 422, 816), radius=7, fill=(35, 76, 87))
    draw.rectangle((240, 680, 318, 816), fill=(12, 42, 62))
    draw.ellipse((300, 744, 309, 753), fill=accent)
    for x in (148, 341):
        draw.rounded_rectangle((x, 631, x + 49, 683), radius=4, fill=_blend(accent, (255, 243, 192), .32))
        draw.line((x + 25, 631, x + 25, 684), fill=(37, 79, 91), width=4)
    for x, y, size in ((54, 684, 61), (460, 660, 74)):
        draw.rectangle((x - 4, y, x + 5, 870), fill=(39, 73, 72))
        draw.ellipse((x - size, y - size, x + size, y + size), fill=(33, 104, 98))
    # Moving beams act as a soft light sweep on the house.
    glow = int(12 + 8 * math.sin(t * 1.4))
    draw.ellipse((168, 655, 177, 665), fill=_blend(accent, (255, 255, 255), glow / 40))


def _calendar(draw, t, accent):
    draw.ellipse((-130, 120, 540, 800), outline=_blend(accent, (37, 81, 110), .58), width=3)
    draw.ellipse((-80, 180, 480, 750), outline=_blend(accent, (37, 81, 110), .76), width=2)
    draw.rounded_rectangle((80, 252, 461, 710), radius=25, fill=(38, 77, 101), outline=accent, width=4)
    draw.rounded_rectangle((80, 252, 461, 339), radius=18, fill=_blend(accent, (255, 255, 255), .07))
    for x in (145, 395):
        draw.line((x, 226, x, 278), fill=(239, 226, 193), width=13)
    progress = min(1, max(0, t / 8))
    for row in range(4):
        for col in range(4):
            x, y = 119 + col * 86, 376 + row * 74
            fill = _blend((54, 104, 122), accent, .8) if (row * 4 + col) / 15 <= progress else (67, 112, 128)
            draw.rounded_rectangle((x, y, x + 56, y + 45), radius=6, fill=fill)
    draw.arc((104, 167, 434, 497), 205, 205 + 210 * progress, fill=accent, width=9)


def _harbor(draw, t, accent):
    draw.ellipse((120, 140, 465, 485), fill=(96, 159, 164))
    for i in range(10):
        x = int(i * 68 - (t * 8) % 68)
        y = 520 - (i % 3) * 45
        draw.rectangle((x, y - 85, x + 48, 590), fill=(40, 87, 100))
        for wx in range(x + 10, x + 42, 19):
            draw.rectangle((wx, y - 65, wx + 7, y - 52), fill=(145, 195, 181))
    draw.rectangle((0, 590, W, H), fill=(22, 79, 96))
    for j in range(6):
        y = 630 + j * 48
        phase = int(25 * math.sin(t * 1.1 + j))
        for x in range(-80, W + 80, 125):
            draw.arc((x + phase, y, x + phase + 110, y + 20), 180, 340,
                     fill=_blend(accent, (43, 119, 132), .65), width=3)
    bx = 190 + 20 * math.sin(t / 2)
    draw.polygon([(bx - 65, 680), (bx + 82, 680), (bx + 47, 710), (bx - 35, 710)], fill=(211, 166, 120))
    draw.polygon([(bx, 669), (bx, 566), (bx + 68, 660)], fill=(238, 218, 174))


def _crane(draw, t, accent):
    draw.ellipse((-115, 85, 450, 650), fill=(42, 87, 111))
    for x, top, width in ((35, 485, 135), (213, 365, 150), (405, 555, 95)):
        draw.rectangle((x, top, x + width, 870), fill=(27, 63, 85))
        for wy in range(top + 20, 820, 33):
            for wx in range(x + 18, x + width - 15, 29):
                draw.rectangle((wx, wy, wx + 10, wy + 15), fill=(57, 113, 122))
    draw.line((270, 197, 270, 716), fill=accent, width=10)
    draw.line((101, 224, 510, 224), fill=accent, width=10)
    draw.line((270, 197, 105, 224), fill=(232, 205, 162), width=3)
    hook_x = 405 + 15 * math.sin(t / 2)
    hook_y = 402 + 19 * math.sin(t * 1.2)
    draw.line((hook_x, 224, hook_x, hook_y), fill=(231, 204, 155), width=3)
    draw.arc((hook_x - 14, hook_y - 3, hook_x + 13, hook_y + 24), 345, 175, fill=accent, width=5)


def _budget(draw, t, accent):
    draw.ellipse((-160, 145, 480, 785), outline=(53, 106, 129), width=3)
    draw.ellipse((-95, 215, 420, 730), outline=(50, 96, 118), width=2)
    draw.rounded_rectangle((105, 408, 472, 705), radius=24, fill=(33, 81, 99), outline=(91, 152, 155), width=3)
    draw.rounded_rectangle((122, 470, 459, 675), radius=18, fill=(46, 99, 111))
    draw.rounded_rectangle((288, 523, 484, 617), radius=15, fill=(20, 63, 79), outline=accent, width=4)
    draw.ellipse((381, 550, 419, 588), fill=accent)
    for i in range(4):
        x = 147 + i * 68
        y = 455 - i * 29 + 6 * math.sin(t * 1.7 + i)
        draw.ellipse((x, y - 28, x + 64, y + 14), fill=_blend(accent, (215, 238, 220), i / 8))
        draw.line((x + 11, y - 7, x + 54, y - 7), fill=(83, 120, 123), width=3)
    draw.line((94, 732, 495, 732), fill=accent, width=3)


def _text_layer(title, label, caption, source, preview, closing=False):
    import fitz
    from PIL import Image

    doc = fitz.open()
    try:
        page = doc.new_page(width=W, height=H)
        gold = (0.95, 0.78, 0.53)
        white = (0.96, 0.97, 0.98)
        page.draw_rect(fitz.Rect(29, 58, 66, 62), color=gold, fill=gold)
        page.insert_text((77, 67), "FIELD NOTES  /  HOUSING", fontsize=13, fontname="hebo", color=white)
        if preview:
            page.insert_text((390, 67), "草稿預覽", fontsize=15, fontname="china-t", color=gold)
        if closing:
            page.insert_textbox(fitz.Rect(37, 182, 505, 370), title, fontsize=42, fontname="china-t", color=white, lineheight=1.22)
            page.insert_text((39, 469), "上架頻道", fontsize=25, fontname="china-t", color=gold)
            font = "hebo" if source[0].isascii() else "china-t"
            page.insert_textbox(fitz.Rect(40, 495, 490, 560), source[0], fontsize=28, fontname=font, color=white)
            page.insert_text((40, 607), "原片位置", fontsize=21, fontname="china-t", color=gold)
            page.insert_text((183, 607), source[2], fontsize=21, fontname="hebo", color=white)
            page.insert_textbox(fitz.Rect(40, 634, 500, 719), source[1], fontsize=14, fontname="helv", color=white)
            page.insert_text((40, 777), "以原創動畫呈現；資料與署名待審核", fontsize=17, fontname="china-t", color=white)
        else:
            page.insert_text((39, 158), label, fontsize=26, fontname="china-t", color=gold)
            if title:
                page.insert_textbox(fitz.Rect(39, 205, 500, 328), title, fontsize=36, fontname="china-t", color=white, lineheight=1.22)
            # A caption at the bottom leaves most of each frame for the visual.
            if caption:
                _mixed_caption(page, caption, white)
            page.insert_text((40, 922), "來源：", fontsize=15, fontname="china-t", color=white)
            font = "hebo" if source[0].isascii() else "china-t"
            page.insert_text((103, 922), source[0], fontsize=15, fontname=font, color=white)
        pix = page.get_pixmap(alpha=True)
        return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def _mixed_caption(page, caption, color):
    """Draw Latin runs in a Latin font; the built-in CJK font spaces them out."""
    import fitz

    x, y = 40.0, 802.0
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9 .:/-]*|[^A-Za-z0-9 .:/-]| +|.", caption):
        if token == " ":
            x += 8
            continue
        font = "hebo" if token.isascii() else "china-t"
        size = 25 if token.isascii() else 27
        # Split a long Latin token only if it would exceed the safe area.
        units = list(token) if fitz.get_text_length(token, fontname=font, fontsize=size) > 455 else [token]
        for part in units:
            width = fitz.get_text_length(part, fontname=font, fontsize=size)
            if x + width > 500:
                x, y = 40.0, y + 41
            if y > 884:
                raise ValueError(f"Promo caption does not fit: {caption}")
            page.insert_text((x, y), part, fontsize=size, fontname=font, color=color)
            x += width


def _scene_frame(base, motif, t, accent):
    from PIL import ImageDraw

    image = base.copy()
    draw = ImageDraw.Draw(image)
    {"city": _city, "home": _home, "calendar": _calendar,
     "harbor": _harbor, "crane": _crane, "budget": _budget}[motif](draw, t, accent)
    # A low, translucent band keeps dynamic captions legible on every scene.
    draw.rectangle((0, 739, W, H), fill=_blend((9, 22, 39), (27, 59, 74), .26))
    return image


def _video_frames(script, spoken, end_seconds):
    from PIL import ImageDraw

    key = script["candidate_id"]
    dark, mid, accent = PALETTES.get(key, PALETTES["c05"])
    motifs = MOTIFS.get(key, ("city", "crane", "home", "budget"))
    labels = LABELS.get(key, ("城市觀察", "現場變化", "居住選擇", "生活預算"))
    phrases = _phrases(script["narration"])
    weights = [max(len(re.sub(r"\W", "", p)), 5) for p in phrases]
    starts = [0]
    for w in weights:
        starts.append(starts[-1] + spoken * w / sum(weights))
    source = (script["source_channel"], script["source_url"],
              _stamp(script["source_interval"]["start"]) + "–" + _stamp(script["source_interval"]["end"]))
    preview = script["review_status"] != "approved"
    base = _background(dark, mid)
    overlays = {}
    frame_count = round((spoken + end_seconds) * FPS)
    for frame_idx in range(frame_count):
        now = frame_idx / FPS
        scene = min(3, int(now / (spoken / 4))) if now < spoken else 4
        local = now - scene * (spoken / 4)
        if scene < 4:
            motif = motifs[scene]
            image = _scene_frame(base, motif, local, accent)
            phrase_idx = next((i for i in range(len(phrases)) if starts[i] <= now < starts[i + 1]), len(phrases) - 1)
            show_title = script["title"] if now < min(3.8, spoken / 4) else ""
            key = (scene, phrase_idx, bool(show_title))
            if key not in overlays:
                overlays[key] = _text_layer(show_title, labels[scene], phrases[phrase_idx], source, preview)
            overlay = overlays[key]
            slide = min(1, (now - starts[phrase_idx]) / .25)
            if slide < 1:
                overlay = overlay.copy()
                overlay.putalpha(overlay.getchannel("A").point(lambda x: int(x * slide)))
            image.paste(overlay, (0, 0), overlay)
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((39, 935, 39 + (W - 78) * now / (spoken + end_seconds), 940), radius=2, fill=accent)
        else:
            image = _scene_frame(base, "city", now, accent)
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((15, 115, W - 15, 827), radius=18, fill=(11, 31, 48))
            if "closing" not in overlays:
                overlays["closing"] = _text_layer(script["title"], "", "", source, preview, closing=True)
            image.paste(overlays["closing"], (0, 0), overlays["closing"])
        yield image.tobytes()


def render_promo(script, output: Path, audio: Path | None, tts: bool, seconds: int,
                 force: bool, music: Path | None = None, style: str = "promo",
                 assets_dir: Path = Path("assets/film")):
    _require_ffmpeg()
    try:
        import PIL  # noqa: F401
        import fitz  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install -r requirements.txt") from exc
    if music and not music.is_file():
        raise ValueError(f"Music file does not exist: {music}")
    if style not in ("promo", "film"):
        raise ValueError("Unknown promotional style")
    asset_digests = {}
    if style == "film":
        from .film import required_assets
        for asset_name in sorted(required_assets(script)):
            asset = assets_dir / f"{asset_name}.png"
            if not asset.is_file():
                raise ValueError(f"Missing film asset: {asset}. Restore assets/film from the project package.")
            asset_digests[asset_name] = _digest_file(asset)
    mode = "tts" if tts else "provided" if audio else "silent"
    key = hashlib.sha256(json.dumps({"script": script, "renderer": VERSION + "/" + style,
                                     "asset_digests": asset_digests, "audio_mode": mode,
                                     "audio_sha256": _digest_file(audio) if audio else None,
                                     "music_sha256": _digest_file(music) if music else None,
                                     "seconds": seconds}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    meta = output.with_suffix(".render.json")
    if not force and output.is_file() and meta.is_file():
        try:
            if json.loads(meta.read_text(encoding="utf-8")).get("cache_key") == key:
                return output, True
        except ValueError:
            pass
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="promo-render-", dir=output.parent) as tmp:
        work = Path(tmp)
        narration = audio
        if tts:
            narration = work / "narration.wav"
            _windows_tts(script["narration"], narration, work)
        spoken = _duration(narration) if narration else seconds - 3.5
        if spoken < len(_phrases(script["narration"])) * .7:
            raise ValueError("Narration audio is too short for the amount of script text")
        total = (round((spoken + 3.5) * FPS) / FPS)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0"]
        if narration:
            cmd += ["-i", str(narration)]
        if music:
            cmd += ["-stream_loop", "-1", "-i", str(music)]
        if narration and music:
            cmd += ["-filter_complex", "[1:a]apad[n];[2:a]volume=0.16[m];[n][m]amix=inputs=2:duration=longest:normalize=0[a]", "-map", "[a]"]
        elif narration:
            cmd += ["-filter_complex", "[1:a]apad[a]", "-map", "[a]"]
        elif music:
            cmd += ["-filter_complex", "[1:a]volume=0.35[a]", "-map", "[a]"]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "1:a:0"]
        temp_output = work / "promo.mp4"
        cmd += ["-map", "0:v:0", "-vf", "scale=720:1280:flags=lanczos,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "112k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(temp_output)]
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            if style == "film":
                from .film import film_frames
                frames = film_frames(script, spoken, 3.5, assets_dir)
            else:
                frames = _video_frames(script, spoken, 3.5)
            for frame in frames:
                process.stdin.write(frame)
        except Exception:
            process.kill()
            process.communicate()
            raise
        finally:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        if process.wait() != 0:
            raise RuntimeError(f"FFmpeg failed: {stderr[-1000:]}")
        actual = _duration_video(temp_output)
        if abs(actual - total) > 1.5:
            raise RuntimeError(f"Unexpected output duration: expected {total:.1f}s, got {actual:.1f}s")
        os.replace(temp_output, output)
    save_json(meta, {"cache_key": key, "renderer": VERSION + "/" + style,
                     "source_url": script["source_url"],
                     "candidate_id": script["candidate_id"], "audio_mode": mode,
                     "music": bool(music), "video_duration_seconds": round(actual, 2),
                     "generation_api_cost_usd": 0, "review_status": script["review_status"]})
    return output, False
