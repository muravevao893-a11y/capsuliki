from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

CARD_DIR = Path(tempfile.gettempdir()) / "capsuliki_cards"
CARD_DIR.mkdir(parents=True, exist_ok=True)

RARITY_COLORS: dict[str, tuple[int, int, int]] = {
    "common": (165, 172, 185),
    "uncommon": (66, 190, 116),
    "rare": (70, 135, 255),
    "epic": (165, 88, 255),
    "legendary": (245, 188, 54),
    "mythic": (235, 64, 96),
}

RARITY_BG: dict[str, tuple[int, int, int]] = {
    "common": (35, 42, 55),
    "uncommon": (19, 61, 44),
    "rare": (16, 42, 87),
    "epic": (44, 21, 80),
    "legendary": (92, 59, 12),
    "mythic": (78, 15, 35),
}


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for item in candidates:
        try:
            return ImageFont.truetype(item, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    result = text
    while result and draw.textlength(result + "…", font=font) > max_width:
        result = result[:-1]
    return result + "…" if result else "…"


def build_pet_card(
    pet: dict[str, Any],
    image_path: str | None,
    owner_name: str | None = None,
    title: str = "Капсула открыта!",
    chance: str | None = None,
) -> str:
    key = f"{pet.get('id')}-{pet.get('xp')}-{pet.get('power')}-{title}-{owner_name}-{chance}-{image_path}"
    out = CARD_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".png")
    if out.exists():
        return str(out)

    rarity = str(pet.get("rarity") or "common")
    accent = RARITY_COLORS.get(rarity, RARITY_COLORS["common"])
    bg = RARITY_BG.get(rarity, RARITY_BG["common"])

    size = 900
    img = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(img)

    # Subtle vertical gradient.
    for y in range(size):
        k = y / size
        r = int(bg[0] * (1 - k) + 9 * k)
        g = int(bg[1] * (1 - k) + 12 * k)
        b = int(bg[2] * (1 - k) + 25 * k)
        draw.line((0, y, size, y), fill=(r, g, b))

    # Card frame.
    margin = 34
    draw.rounded_rectangle((margin, margin, size - margin, size - margin), radius=54, outline=accent, width=10)
    draw.rounded_rectangle((margin + 18, margin + 18, size - margin - 18, size - margin - 18), radius=40, outline=(255, 255, 255), width=2)

    # Header.
    title_font = _font(40, True)
    name_font = _font(64, True)
    body_font = _font(30)
    small_font = _font(24)
    white = (248, 250, 255)
    muted = (205, 214, 230)

    title = _fit_text(draw, str(title), title_font, 720)
    draw.text((size // 2, 76), title, fill=white, font=title_font, anchor="mm")

    # Pet image circle.
    circle_box = (165, 145, 735, 715)
    draw.ellipse(circle_box, fill=(255, 255, 255), outline=accent, width=8)
    if image_path and Path(image_path).exists():
        try:
            pet_img = Image.open(image_path).convert("RGBA")
            pet_img = ImageOps.fit(pet_img, (520, 520), method=Image.Resampling.LANCZOS, centering=(0.5, 0.48))
            mask = Image.new("L", (520, 520), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 520, 520), fill=255)
            img.paste(pet_img, (190, 170), mask)
        except Exception:
            draw.text((450, 420), str(pet.get("emoji") or "🐾"), font=_font(140), fill=accent, anchor="mm")
    else:
        draw.text((450, 420), str(pet.get("emoji") or "🐾"), font=_font(140), fill=accent, anchor="mm")

    # Footer panel.
    panel = (70, 650, 830, 835)
    draw.rounded_rectangle(panel, radius=34, fill=(8, 12, 25), outline=accent, width=4)

    pet_name = _fit_text(draw, f"{pet.get('emoji', '')} {pet.get('name') or pet.get('base_name') or 'Питомец'}", name_font, 690)
    draw.text((450, 702), pet_name, fill=white, font=name_font, anchor="mm")

    rarity_name = str(pet.get("rarity_name") or rarity)
    line = f"{rarity_name} · сила {pet.get('power', '?')} · ур. {pet.get('level', 1)}"
    draw.text((450, 760), _fit_text(draw, line, body_font, 690), fill=muted, font=body_font, anchor="mm")

    if chance:
        draw.text((120, 810), f"Шанс: {chance}", fill=muted, font=small_font, anchor="lm")
    if owner_name:
        draw.text((780, 810), _fit_text(draw, owner_name, small_font, 310), fill=muted, font=small_font, anchor="rm")

    img.save(out, "PNG", optimize=True)
    return str(out)
