#!/usr/bin/env python3
"""Shared: import Pillow or exit 0 with a clear warning (never pip-install on deploy hosts)."""
from __future__ import annotations

import sys


def require_pil(script_name: str):
    try:
        from PIL import Image  # noqa: F401
        return Image
    except ImportError:
        print(
            f"AVISO: {script_name}: Pillow no está instalado en este Python "
            f"({sys.executable}). Se omite el procesado de imágenes "
            "(en Docker se aplica en el build).",
            file=sys.stderr,
        )
        raise SystemExit(0)
