#!/usr/bin/env python3
"""One-shot: dump in-memory catalogs to app/i18n/locales/*.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.i18n_service import _CATALOG  # noqa: E402

OUT = ROOT / "app" / "i18n" / "locales"
OUT.mkdir(parents=True, exist_ok=True)

for loc, bag in _CATALOG.items():
    data = {str(k): str(v) for k, v in bag.items() if k is not None and v is not None}
    path = OUT / f"{loc}.json"
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{path.name}: {len(data)} keys")
