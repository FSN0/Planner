#!/usr/bin/env python3
"""Generate favicons from logo-mark.png (transparent, no white plate)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pil_util import open_image_or_none, require_pil, save_image_or_warn, warn_bad_image  # noqa: E402

SCRIPT = "generate_favicons.py"
Image = require_pil(SCRIPT)

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
        return 0
    im = open_image_or_none(SCRIPT, SRC)
    if im is None:
        return 0
    for name, size in (
        ("favicon-48.png", 48),
        ("favicon-192.png", 192),
        ("apple-touch-icon.png", 180),
    ):
        try:
            out = fit_square_transparent(im, size)
        except Exception as e:
            warn_bad_image(SCRIPT, SRC, e)
            continue
        if save_image_or_warn(SCRIPT, out, DEST / name, format="PNG", optimize=True):
            print(f"wrote {name} ({size}x{size}, transparent)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"AVISO: {SCRIPT}: {e}", file=sys.stderr)
        raise SystemExit(0)
