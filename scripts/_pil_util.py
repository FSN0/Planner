#!/usr/bin/env python3
"""Shared Pillow helpers: optional import, one-line stderr warnings, no tracebacks."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage

# Re-exported after require_pil()
Image: type[PILImage] | None = None


def require_pil(script_name: str):
    try:
        from PIL import Image as _Image
        from PIL import UnidentifiedImageError  # noqa: F401

        global Image
        Image = _Image
        return _Image
    except ImportError:
        print(
            f"AVISO: {script_name}: Pillow no está instalado en este Python "
            f"({sys.executable}). Se omite el procesado de imágenes "
            "(en Docker se aplica en el build).",
            file=sys.stderr,
        )
        raise SystemExit(0)


def _pil_error_types():
    from PIL import UnidentifiedImageError

    return (OSError, UnidentifiedImageError)


def warn_bad_image(script_name: str, path: Path | str, err: BaseException) -> None:
    p = Path(path)
    print(f"AVISO: {script_name}: imagen no válida, se omite {p}: {err}", file=sys.stderr)


def open_image_or_none(script_name: str, path: Path):
    """Open PNG/image; on failure print one line to stderr and return None."""
    Image = require_pil(script_name)
    try:
        im = Image.open(path)
        im.load()
        return im
    except Exception as e:
        warn_bad_image(script_name, path, e)
        return None


def save_image_or_warn(script_name: str, im, path: Path, **kwargs) -> bool:
    try:
        im.save(path, **kwargs)
        return True
    except Exception as e:
        warn_bad_image(script_name, path, e)
        return False


def verify_png_or_warn(script_name: str, path: Path) -> bool:
    if not path.is_file():
        return False
    Image = require_pil(script_name)
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im.load()
        return True
    except Exception as e:
        warn_bad_image(script_name, path, e)
        return False


def check_brand_destinations(script_name: str, dest_dir: Path, names: list[str]) -> None:
    """Warn (stderr) for each expected brand PNG that cannot be read."""
    for name in names:
        verify_png_or_warn(script_name, dest_dir / name)
