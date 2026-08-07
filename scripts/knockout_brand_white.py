#!/usr/bin/env python3
"""Make near-white opaque pixels transparent in brand source PNGs, then leave
sync_brand_assets.sh to copy into static.

Only touches canonical source files in logos_signaplan/ (not *_con_fondo).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pil_util import require_pil  # noqa: E402

Image = require_pil("knockout_brand_white.py")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "logos_signaplan"
# Threshold: pixels this bright (and opaque) become transparent.
WHITE_MIN = 245
# Soft edge: fade alpha for near-white
SOFT_MIN = 230

CANONICAL = [
    "Logo.png",
    "Logo + Nombre.png",
    "Nombre.png",
]


def knock_out_white(im: Image.Image) -> Image.Image:
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    changed = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            # Already transparent-ish
            brightness = min(r, g, b)
            # Near-white / light gray backgrounds only (not green check / dark bars)
            if r >= SOFT_MIN and g >= SOFT_MIN and b >= SOFT_MIN:
                if r >= WHITE_MIN and g >= WHITE_MIN and b >= WHITE_MIN:
                    px[x, y] = (r, g, b, 0)
                    changed += 1
                else:
                    # Soft fade for off-white fringe
                    t = (min(r, g, b) - SOFT_MIN) / float(WHITE_MIN - SOFT_MIN)
                    new_a = max(0, min(255, int(a * (1.0 - t))))
                    if new_a != a:
                        px[x, y] = (r, g, b, new_a)
                        changed += 1
    return rgba, changed


def main() -> int:
    if not SRC.is_dir():
        print(f"Missing {SRC}", file=sys.stderr)
        return 1
    for name in CANONICAL:
        path = SRC / name
        if not path.exists():
            print(f"skip missing {name}")
            continue
        im = Image.open(path)
        out, changed = knock_out_white(im)
        # Always rewrite as PNG with alpha
        out.save(path, format="PNG", optimize=True)
        print(f"{name}: knocked {changed} near-white pixels -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
