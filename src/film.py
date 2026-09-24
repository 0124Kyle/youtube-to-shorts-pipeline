"""Photographic, illustrative B-roll with lower-third captions.

The bundled stills are AI-generated illustrations of generic situations. They
must never be represented as original reporting footage or real interviews.
"""

import bisect
import re
from pathlib import Path

from .promo import FPS, H, W, _mixed_caption
from .video import _phrases, _stamp

SHOTS = {
    "c05": ("urban", "apartment", "calendar", "budget", "apartment", "calendar", "budget", "urban"),
    "c10": ("harbor", "construction", "apartment", "harbor", "construction", "budget", "apartment", "harbor"),
    "c15": ("urban", "construction", "urban", "apartment", "construction", "budget", "urban", "construction"),
}
DEFAULT_SHOTS = ("urban", "apartment", "construction", "budget", "urban", "apartment", "budget", "urban")


def required_assets(script):
    return set(SHOTS.get(script["candidate_id"], DEFAULT_SHOTS))


def _photo_sources(script, assets_dir):
    from PIL import Image, ImageOps

    assets = {}
    for name in required_assets(script):
        path = assets_dir / f"{name}.png"
        if not path.is_file():
            raise ValueError(f"Missing film asset: {path}. Restore assets/film from the project package or use --style promo.")
        with Image.open(path) as image:
            # Oversize once; each frame only crops and resizes the small region.
            assets[name] = ImageOps.fit(image.convert("RGB"), (658, 1170), method=Image.Resampling.LANCZOS)
    return assets


def _camera(image, local_progress, shot_index):
    from PIL import Image

    # A restrained move; generated stills are not claimed to be video footage.
    zoom = 1.035 + .055 * local_progress
    crop_w, crop_h = round(W / zoom), round(H / zoom)
    horizontal = local_progress if shot_index % 2 else 1 - local_progress
    vertical = .38 + .24 * local_progress if shot_index % 3 else .62 - .24 * local_progress
    x = round((image.width - crop_w) * horizontal)
    y = round((image.height - crop_h) * vertical)
    return image.crop((x, y, x + crop_w, y + crop_h)).resize((W, H), Image.Resampling.BILINEAR)


def _shade_bottom(image):
    from PIL import Image, ImageDraw

    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(shade)
    for y in range(0, 100):
        draw.line((0, y, W, y), fill=(4, 13, 22, round(105 * (1 - y / 100))))
    for y in range(655, H):
        opacity = round(18 + 197 * ((y - 655) / (H - 655)) ** 1.15)
        draw.line((0, y, W, y), fill=(4, 13, 22, opacity))
    return Image.alpha_composite(image.convert("RGBA"), shade)


def _overlay(script, caption, closing=False):
    import fitz
    from PIL import Image

    doc = fitz.open()
    try:
        page = doc.new_page(width=W, height=H)
        white, soft = (.98, .98, .97), (.85, .9, .93)
        page.insert_text((32, 62), "資料來源", fontsize=15, fontname="china-t", color=white)
        font = "hebo" if script["source_channel"].isascii() else "china-t"
        page.insert_text((115, 62), script["source_channel"], fontsize=16, fontname=font, color=white)
        page.insert_text((420, 62), "AI", fontsize=14, fontname="hebo", color=white)
        page.insert_text((447, 62), "示意", fontsize=14, fontname="china-t", color=white)
        if closing:
            page.insert_textbox(fitz.Rect(35, 273, 505, 424), script["title"], fontsize=38,
                                fontname="china-t", color=white, lineheight=1.2)
            interval = script["source_interval"]
            times = _stamp(interval["start"]) + " - " + _stamp(interval["end"])
            page.insert_text((37, 577), "原片位置", fontsize=22, fontname="china-t", color=white)
            page.insert_text((187, 577), times, fontsize=22, fontname="hebo", color=white)
            page.insert_textbox(fitz.Rect(37, 625, 505, 699), script["source_url"], fontsize=15,
                                fontname="helv", color=soft)
            page.insert_text((37, 785), "原創示意畫面・非原片影像", fontsize=18, fontname="china-t", color=white)
            if script["review_status"] != "approved":
                page.insert_text((37, 831), "腳本草稿，內容與署名待核對", fontsize=16, fontname="china-t", color=soft)
        elif caption:
            _mixed_caption(page, caption, white)
        pix = page.get_pixmap(alpha=True)
        return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def film_frames(script, spoken, end_seconds, assets_dir: Path):
    from PIL import Image, ImageDraw

    assets = _photo_sources(script, assets_dir)
    shots = SHOTS.get(script["candidate_id"], DEFAULT_SHOTS)
    phrases = _phrases(script["narration"])
    weights = [max(len(re.sub(r"\W", "", phrase)), 5) for phrase in phrases]
    starts = [0.0]
    for weight in weights:
        starts.append(starts[-1] + spoken * weight / sum(weights))
    overlays = {}
    shot_duration = spoken / len(shots)
    for frame_index in range(round((spoken + end_seconds) * FPS)):
        now = frame_index / FPS
        if now < spoken:
            shot = min(len(shots) - 1, int(now / shot_duration))
            local = min(1, (now - shot * shot_duration) / shot_duration)
            image = _camera(assets[shots[shot]], local, shot)
            # Crossfade at cuts, keeping the footage-like pacing gentle.
            transition = .34 / shot_duration
            if shot and local < transition:
                previous = _camera(assets[shots[shot - 1]], 1, shot - 1)
                image = Image.blend(previous, image, local / transition)
            image = _shade_bottom(image)
            phrase_idx = min(len(phrases) - 1, max(0, bisect.bisect_right(starts, now) - 1))
            if phrase_idx not in overlays:
                overlays[phrase_idx] = _overlay(script, phrases[phrase_idx])
            layer = overlays[phrase_idx]
            fade = min(1, (now - starts[phrase_idx]) / .22)
            if fade < 1:
                layer = layer.copy()
                layer.putalpha(layer.getchannel("A").point(lambda v: int(v * fade)))
            image = Image.alpha_composite(image, layer)
        else:
            image = _camera(assets[shots[-1]], 1, len(shots) - 1).convert("RGBA")
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, W, H), fill=(5, 17, 29, 217))
            if "closing" not in overlays:
                overlays["closing"] = _overlay(script, "", closing=True)
            image = Image.alpha_composite(image, overlays["closing"])
        yield image.convert("RGB").tobytes()
