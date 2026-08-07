#!/usr/bin/env python3
"""Generate Google-friendly favicons from logo-mark.png."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow", "-q"])
    from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "static" / "img" / "brand" / "logo-mark.png"
DEST = ROOT / "app" / "static" / "img" / "brand"


def fit_square(im: Image.Image, size: int) -> Image.Image:
    rgba = im.convert("RGBA")
    # Trim transparent margins first
    bbox = rgba.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    # Pad to square on white (Google favicon reads better opaque)
    w, h = rgba.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    canvas.paste(rgba, ((side - w) // 2, (side - h) // 2), rgba)
    out = canvas.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
    return out


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
        fit_square(im, size).save(DEST / name, format="PNG", optimize=True)
        print(f"wrote {name} ({size}x{size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
