#!/bin/bash
set -euo pipefail

# Limpia migraciones obsoletas/duplicadas antes de flask db upgrade.
# Uso: bash scripts/fix_migration_heads.sh

VERSIONS_DIR="migrations/versions"
CANONICAL_CUSTOM_DOMAIN="a8f3c2b1d0e9_add_tenant_custom_domain.py"
CANONICAL_FICHAJES="e5f6a7b8c9d0_add_registros_fichajes_nota_odoo.py"

if [ ! -d "$VERSIONS_DIR" ]; then
    echo "No existe $VERSIONS_DIR"
    exit 1
fi

echo "==> Archivos de migración en disco:"
ls -1 "$VERSIONS_DIR" || true

echo "==> Eliminando migraciones duplicadas/obsoletas..."
rm -f "$VERSIONS_DIR"/b4c5d6e7f8a9_*.py
rm -f "$VERSIONS_DIR"/e5f6a7b8c9d0_add_tenant_custom_domain.py

if [ -f "$VERSIONS_DIR/$CANONICAL_CUSTOM_DOMAIN" ]; then
    for path in "$VERSIONS_DIR"/*custom_domain*.py; do
        [ -e "$path" ] || continue
        base="$(basename "$path")"
        [ "$base" = "$CANONICAL_CUSTOM_DOMAIN" ] && continue
        echo "    eliminando $base"
        rm -f "$path"
    done
fi

if [ -f "$VERSIONS_DIR/$CANONICAL_FICHAJES" ]; then
    for path in "$VERSIONS_DIR"/*fichajes*nota_odoo*.py; do
        [ -e "$path" ] || continue
        base="$(basename "$path")"
        [ "$base" = "$CANONICAL_FICHAJES" ] && continue
        echo "    eliminando $base"
        rm -f "$path"
    done
fi

python3 - <<'PY'
import pathlib
import re
import sys

versions = pathlib.Path("migrations/versions")
revs = {}
for path in sorted(versions.glob("*.py")):
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
    if not match:
        continue
    revs.setdefault(match.group(1), []).append(path.name)

duplicates = {rev: files for rev, files in revs.items() if len(files) > 1}
if duplicates:
    print("ERROR: revisiones duplicadas en migrations/versions:", file=sys.stderr)
    for rev, files in duplicates.items():
        print(f"  {rev}: {files}", file=sys.stderr)
    sys.exit(1)

all_revs = set(revs)
referenced = set()
for path in versions.glob("*.py"):
    text = path.read_text(encoding="utf-8", errors="ignore")
    down_m = re.search(r"^down_revision\s*=\s*(.+)$", text, re.M)
    if not down_m:
        continue
    down = down_m.group(1).strip()
    if down.startswith("("):
        inner = down.strip("()")
        for part in inner.split(","):
            referenced.add(part.strip().strip("'\""))
    elif down not in ("None", "null"):
        referenced.add(down.strip("'\""))

heads = sorted(all_revs - referenced)
if len(heads) != 1:
    print(f"ERROR: se esperaba 1 head, encontradas: {heads}", file=sys.stderr)
    sys.exit(1)

print(f"==> Head en disco: {heads[0]}")
PY

echo "==> Cadena esperada: ... -> q8l9m0n1o2p3 -> p7k8l9m0n1o2 -> r9s0t1u2v3w4 -> s0t1u2v3w4x5"
