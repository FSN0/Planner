#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build complete FR/PT UI catalogs from real overrides + extras."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    en = json.loads((ROOT / "_en_keys.json").read_text(encoding="utf-8"))
    fr_real = json.loads((ROOT / "_fr_real.json").read_text(encoding="utf-8"))
    pt_real = json.loads((ROOT / "_pt_real.json").read_text(encoding="utf-8"))
    fr_extra = json.loads((ROOT / "_fr_extra.json").read_text(encoding="utf-8"))
    pt_extra = json.loads((ROOT / "_pt_extra.json").read_text(encoding="utf-8"))

    fr_full: dict[str, str] = {}
    pt_full: dict[str, str] = {}
    missing_fr: list[str] = []
    missing_pt: list[str] = []

    for key, en_val in en.items():
        if key in fr_real:
            fr_full[key] = fr_real[key]
        elif key in fr_extra:
            fr_full[key] = fr_extra[key]
        else:
            missing_fr.append(key)

        if key in pt_real:
            pt_full[key] = pt_real[key]
        elif key in pt_extra:
            pt_full[key] = pt_extra[key]
        else:
            missing_pt.append(key)

    if missing_fr or missing_pt:
        raise SystemExit(f"Missing translations FR={missing_fr[:10]} PT={missing_pt[:10]}")

    if len(fr_full) != len(en) or len(pt_full) != len(en):
        raise SystemExit(f"Length mismatch EN={len(en)} FR={len(fr_full)} PT={len(pt_full)}")

    # Never leave English copies (except intentional same tokens where value == msgid)
    en_leftover_fr = [k for k, v in fr_full.items() if en.get(k) == v and v != k]
    en_leftover_pt = [k for k, v in pt_full.items() if en.get(k) == v and v != k]
    # Soft warn — some brand/technical tokens may match EN while differing from Spanish msgid
    print("EN leftover FR (v==EN and v!=key):", len(en_leftover_fr), en_leftover_fr[:20])
    print("EN leftover PT (v==EN and v!=key):", len(en_leftover_pt), en_leftover_pt[:20])

    for path, data in (
        (ROOT / "_fr_full.json", fr_full),
        (ROOT / "_pt_full.json", pt_full),
    ):
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("wrote", path, len(data))

    locales_py = ROOT / "app" / "services" / "i18n_catalog_locales.py"
    locales_py.write_text(
        '''"""Full French and Portuguese UI catalogs (Spanish msgid -> locale string).

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
''',
        encoding="utf-8",
    )
    print("wrote", locales_py)


if __name__ == "__main__":
    main()
