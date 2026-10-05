#!/usr/bin/env python3
"""Trim empty margins from synced brand PNGs (transparent / near-white)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pil_util import (  # noqa: E402
    open_image_or_none,
    require_pil,
    save_image_or_warn,
    warn_bad_image,
)

SCRIPT = "trim_brand_margins.py"
Image = require_pil(SCRIPT)

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "app" / "static" / "img" / "brand"

FILES = [
    DEST / "logo-horizontal.png",
    DEST / "logo-mark.png",
    DEST / "logo-wordmark.png",
]

PAD = 4
WHITE_MIN = 245
ALPHA_MIN = 8


def _is_content(px, x: int, y: int) -> bool:
    r, g, b, a = px[x, y]
    if a < ALPHA_MIN:
        return False
    if r >= WHITE_MIN and g >= WHITE_MIN and b >= WHITE_MIN:
        return False
    return True


def _has_content_neighbor(px, x: int, y: int, w: int, h: int) -> bool:
    """Ignore isolated speck pixels that inflate the bbox."""
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and _is_content(px, nx, ny):
                return True
    return False


def content_bbox(im: Image.Image) -> tuple[int, int, int, int] | None:
    rgba = im.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if not _is_content(px, x, y):
                continue
            if not _has_content_neighbor(px, x, y, w, h):
                continue
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y
    if max_x < 0:
        return None
    return (
        max(0, min_x - PAD),
        max(0, min_y - PAD),
        min(w, max_x + 1 + PAD),
        min(h, max_y + 1 + PAD),
    )


def trim_file(path: Path) -> None:
    if not path.exists():
        print(f"skip missing {path.name}")
        return
    im = open_image_or_none(SCRIPT, path)
    if im is None:
        return
    try:
        box = content_bbox(im)
        if not box:
            print(f"no content {path.name}")
            return
        before = im.size
        cropped = im.convert("RGBA").crop(box)
    except Exception as e:
        warn_bad_image(SCRIPT, path, e)
        return
    if save_image_or_warn(SCRIPT, cropped, path, format="PNG", optimize=True):
        print(f"trimmed {path.name}: {before} -> {cropped.size}")


def main() -> int:
    for path in FILES:
        trim_file(path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"AVISO: {SCRIPT}: {e}", file=sys.stderr)
        raise SystemExit(0)
