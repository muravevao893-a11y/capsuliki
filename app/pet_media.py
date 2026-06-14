from __future__ import annotations

from pathlib import Path

PET_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "pets"
SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def find_pet_image(image_key: str | None) -> str | None:
    if not image_key:
        return None
    for extension in SUPPORTED_EXTENSIONS:
        candidate = PET_ASSETS_DIR / f"{image_key}{extension}"
        if candidate.exists():
            return str(candidate)
    return None
