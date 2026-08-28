"""Curated-avatar resolution.

There is no image-generation API: the wizard's "יצירת תמונה" button picks the
best curated asset for the chosen spec. The lookup degrades so the art library
can grow without a code change — ship the ~10 `{style}/{ethnicity}` bases first,
add `{style}/{ethnicity}_{hair_color}` variants later and they light up on their
own.
"""

from __future__ import annotations

from pathlib import Path

MEDIA_ROOT = Path(__file__).resolve().parent.parent / "media"
AVATAR_DIR = MEDIA_ROOT / "avatars"
AVATAR_URL_ROOT = "/media/avatars"

_EXTENSIONS = (".webp", ".png", ".jpg")


def _first_existing(style: str, stems: list[str]) -> str | None:
    for stem in stems:
        for ext in _EXTENSIONS:
            if (AVATAR_DIR / style / f"{stem}{ext}").is_file():
                return f"{AVATAR_URL_ROOT}/{style}/{stem}{ext}"
    return None


def resolve_avatar(spec: object) -> str | None:
    """Best curated avatar URL for a PersonaSpec, or None if the library is bare."""
    style = str(getattr(spec, "style", "") or "realistic")
    ethnicity = str(getattr(spec, "ethnicity", "") or "")
    hair_color = str(getattr(spec, "hair_color", "") or "")

    candidates = [f"{ethnicity}_{hair_color}", ethnicity, "default"]
    found = _first_existing(style, candidates)
    if found is None and style != "realistic":
        found = _first_existing("realistic", candidates)
    return found
