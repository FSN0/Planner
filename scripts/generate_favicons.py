#!/usr/bin/env python3
"""Generate favicons from logo-mark.png (transparent, no white plate)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pil_util import require_pil  # noqa: E402

Image = require_pil("generate_favicons.py")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "static" / "img" / "brand" / "logo-mark.png"
DEST = ROOT / "app" / "static" / "img" / "brand"


def fit_square_transparent(im: Image.Image, size: int) -> Image.Image:
    rgba = im.convert("RGBA")
    bbox = rgba.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    w, h = rgba.size
    side = max(w, h)
    # Canvas transparente (sin pastilla blanca)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(rgba, ((side - w) // 2, (side - h) // 2), rgba)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main() -> int:
    if not SRC.exists():
        print(f"missing {SRC}", file=sys.stderr)
        return 1
    im = Image.open(SRC)
    for name, size in (
        ("favicon-48.png", 48),
        ("favicon-192.png", 192),
        ("apple-touch-icon.png", 180),
    ):
        fit_square_transparent(im, size).save(DEST / name, format="PNG", optimize=True)
        print(f"wrote {name} ({size}x{size}, transparent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
