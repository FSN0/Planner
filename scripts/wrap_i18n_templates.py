#!/usr/bin/env python3
"""Wrap catalog msgids in Jinja templates with {{ _('...') }}. Idempotent."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "app" / "templates"
EN = json.loads((ROOT / "app" / "i18n" / "locales" / "en.json").read_text(encoding="utf-8"))

SKIP_PREFIXES = (
    "nav.", "hero.", "suite.", "erp.", "legal.", "access.", "cta.", "footer.",
    "alta.", "pref.", "role.", "seo.", "landing.", "cookie.",
)

ATTR = (
    "placeholder", "title", "aria-label", "alt", "value", "data-original-title",
    "aria-placeholder",
)

_JINJA = re.compile(r"(\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\})", re.S)


def is_msgid(key: str) -> bool:
    if not key or len(key) < 2:
        return False
    if key.startswith(SKIP_PREFIXES):
        return False
    if "." in key and key.split(".", 1)[0] in {
        "nav", "hero", "suite", "erp", "legal", "access", "cta", "footer",
        "alta", "pref", "role", "seo", "landing", "cookie",
    }:
        return False
    return True


def jinja_expr(key: str) -> str:
    if "'" not in key:
        return "{{ _('%s') }}" % key
    if '"' not in key:
        return '{{ _("%s") }}' % key
    return "{{ _(%s) }}" % repr(key)


def wrap_text(src: str, keys: list[str]) -> str:
    parts = []
    last = 0
    slots = []
    for m in _JINJA.finditer(src):
        parts.append(src[last:m.start()])
        slots.append(m.group(0))
        parts.append("\x00%d\x00" % (len(slots) - 1))
        last = m.end()
    parts.append(src[last:])
    body = "".join(parts)

    for key in keys:
        if key not in body:
            continue
        expr = jinja_expr(key)
        escaped = re.escape(key)
        body = re.sub(
            rf'(?P<pre>(?:{"|".join(ATTR)})\s*=\s*["\']){escaped}(?P<post>["\'])',
            lambda m, e=expr: m.group("pre") + e + m.group("post"),
            body,
        )
        body = body.replace(">" + key + "<", ">" + expr + "<")
        body = re.sub(
            rf"(?P<pre>>)\s*{escaped}\s*(?P<post><)",
            lambda m, e=expr: m.group("pre") + e + m.group("post")
            if m.group(0).strip()[1:-1].strip() == key
            else m.group(0),
            body,
        )

    def restore(m):
        return slots[int(m.group(1))]

    return re.sub(r"\x00(\d+)\x00", restore, body)


def main() -> None:
    keys = sorted((k for k in EN if is_msgid(k)), key=len, reverse=True)
    changed = 0
    for path in sorted(TPL.rglob("*.html")):
        original = path.read_text(encoding="utf-8")
        updated = wrap_text(original, keys)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
            print("wrapped", path.relative_to(ROOT))
    print("files_changed", changed, "keys", len(keys))


if __name__ == "__main__":
    main()
