from __future__ import annotations

import hashlib
import os
import tempfile
import unicodedata
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

TRANSLIT = str.maketrans({
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E", "Ж": "Zh", "З": "Z", "И": "I",
    "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T",
    "У": "U", "Ф": "F", "Х": "H", "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Sch", "Ъ": "", "Ы": "Y", "Ь": "",
    "Э": "E", "Ю": "Yu", "Я": "Ya",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
})


def _font_candidates(bold: bool) -> list[str]:
    env_font = os.getenv("CAPSULIKI_FONT_BOLD" if bold else "CAPSULIKI_FONT")
    candidates = []
    if env_font:
        candidates.append(env_font)

    # Linux/Docker/Railway paths.
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]

    # Windows/macOS dev paths.
    candidates += [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    return candidates


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for item in _font_candidates(bold):
        try:
            if item and Path(item).exists():
                return ImageFont.truetype(item, size=size)
        except Exception:
            continue
    # Last resort. It may not support Cyrillic, so text is sanitized before draw.
    return ImageFont.load_default()


def _can_render_cyrillic(font: ImageFont.ImageFont) -> bool:
    # PIL default font often renders Cyrillic as boxes. DejaVu/Arial returns a normal bbox/width.
    try:
        probe = "Капсулики"
        mask = font.getmask(probe)
        return mask.size[0] > 20 and mask.size[1] > 5
    except Exception:
        return False


def _strip_unrenderable_symbols(text: str) -> str:
    # DejaVu supports Cyrillic, but not colorful Telegram emoji. Removing emoji avoids □ boxes on cards.
    result = []
    for ch in str(text or ""):
        category = unicodedata.category(ch)
        if category == "So":
            continue
        result.append(ch)
    return " ".join("".join(result).split())


def _safe_text(text: str, font: ImageFont.ImageFont) -> str:
    text = unicodedata.normalize("NFC", str(text or ""))
    text = _strip_unrenderable_symbols(text)
    if _can_render_cyrillic(font):
        return text
    # If the deploy image has no Cyrillic fonts, avoid □□□ boxes.
    return text.translate(TRANSLIT)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    text = _safe_text(text, font)
    if draw.textlength(text, font=font) <= max_width:
        return text
    result = text
    while result and draw.textlength(result + "…", font=font) > max_width:
        result = result[:-1]
    return result + "…" if result else "…"


def _draw_center(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont, fill, max_width: int) -> None:
    draw.text(xy, _fit_text(draw, text, font, max_width), fill=fill, font=font, anchor="mm")


def _initials(text: str) -> str:
    clean = _strip_unrenderable_symbols(text)
    words = [part for part in clean.replace("-", " ").split() if part]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return "".join(word[0] for word in words[:2]).upper()


def build_pet_card(
    pet: dict[str, Any],
    image_path: str | None,
    owner_name: str | None = None,
    title: str = "Капсула открыта!",
    chance: str | None = None,
) -> str:
    # Add font version to cache key so old broken cards are not reused after update.
    key = f"v120-content-{pet.get('id')}-{pet.get('xp')}-{pet.get('power')}-{title}-{owner_name}-{chance}-{image_path}"
    out = CARD_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".png")
    if out.exists():
        return str(out)

    rarity = str(pet.get("rarity") or "common")
    accent = RARITY_COLORS.get(rarity, RARITY_COLORS["common"])
    bg = RARITY_BG.get(rarity, RARITY_BG["common"])

    size = 900
    img = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(img)

    for y in range(size):
        k = y / size
        r = int(bg[0] * (1 - k) + 9 * k)
        g = int(bg[1] * (1 - k) + 12 * k)
        b = int(bg[2] * (1 - k) + 25 * k)
        draw.line((0, y, size, y), fill=(r, g, b))

    margin = 34
    draw.rounded_rectangle((margin, margin, size - margin, size - margin), radius=54, outline=accent, width=10)
    draw.rounded_rectangle((margin + 18, margin + 18, size - margin - 18, size - margin - 18), radius=40, outline=(255, 255, 255), width=2)

    title_font = _font(42, True)
    name_font = _font(54, True)
    body_font = _font(30)
    small_font = _font(22)
    white = (248, 250, 255)
    muted = (205, 214, 230)

    _draw_center(draw, (size // 2, 72), str(title or "Капсула открыта!"), title_font, white, 730)

    circle_box = (165, 140, 735, 710)
    draw.ellipse(circle_box, fill=(255, 255, 255), outline=accent, width=8)
    if image_path and Path(image_path).exists():
        try:
            pet_img = Image.open(image_path).convert("RGBA")
            pet_img = ImageOps.fit(pet_img, (520, 520), method=Image.Resampling.LANCZOS, centering=(0.5, 0.48))
            mask = Image.new("L", (520, 520), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 520, 520), fill=255)
            img.paste(pet_img, (190, 165), mask)
        except Exception:
            draw.text((450, 390), _initials(str(pet.get("name") or pet.get("base_name") or "PET")), font=_font(96, True), fill=accent, anchor="mm")
            draw.text((450, 465), _fit_text(draw, str(pet.get("element") or ""), _font(28), 320), font=_font(28), fill=accent, anchor="mm")
    else:
        draw.text((450, 390), _initials(str(pet.get("name") or pet.get("base_name") or "PET")), font=_font(96, True), fill=accent, anchor="mm")
        draw.text((450, 465), _fit_text(draw, str(pet.get("element") or ""), _font(28), 320), font=_font(28), fill=accent, anchor="mm")

    # Lower panel moved slightly down; less text, more readable.
    panel = (70, 650, 830, 835)
    draw.rounded_rectangle(panel, radius=34, fill=(8, 12, 25), outline=accent, width=4)

    pet_name_raw = f"{pet.get('name') or pet.get('base_name') or 'Питомец'}".strip()
    _draw_center(draw, (450, 698), pet_name_raw, name_font, white, 690)

    rarity_name = str(pet.get("rarity_name") or rarity)
    line = f"{rarity_name} · сила {pet.get('power', '?')} · ур. {pet.get('level', 1)}"
    _draw_center(draw, (450, 756), line, body_font, muted, 700)

    if chance:
        draw.text((120, 810), _fit_text(draw, f"Шанс: {chance}", small_font, 260), fill=muted, font=small_font, anchor="lm")
    if owner_name:
        owner = owner_name if str(owner_name).startswith("@") else f"@{owner_name}"
        draw.text((780, 810), _fit_text(draw, owner, small_font, 310), fill=muted, font=small_font, anchor="rm")

    img.save(out, "PNG", optimize=True)
    return str(out)
