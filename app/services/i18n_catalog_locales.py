"""Full French and Portuguese UI catalogs (Spanish msgid -> locale string).

Loaded from JSON at repo root so catalogs stay editable without huge Python literals.
"""
from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> dict[str, str]:
    path = _ROOT / name
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{name} must be a JSON object")
    return {str(k): str(v) for k, v in data.items()}


APP_UI_FR_FULL: dict[str, str] = _load("_fr_full.json")
APP_UI_PT_FULL: dict[str, str] = _load("_pt_full.json")
