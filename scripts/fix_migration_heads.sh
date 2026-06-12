#!/bin/bash
set -euo pipefail

# Elimina migraciones duplicadas/obsoletas de custom_domain antes de flask db upgrade.
# Uso: bash scripts/fix_migration_heads.sh

VERSIONS_DIR="migrations/versions"
CANONICAL="a8f3c2b1d0e9_add_tenant_custom_domain.py"

if [ ! -d "$VERSIONS_DIR" ]; then
    echo "No existe $VERSIONS_DIR"
    exit 1
fi

echo "==> Archivos de migración actuales:"
ls -1 "$VERSIONS_DIR" || true

if [ -f "$VERSIONS_DIR/$CANONICAL" ]; then
    echo "==> Limpiando migraciones custom_domain obsoletas..."
    rm -f "$VERSIONS_DIR"/e5f6a7b8c9d0_*.py
    for path in "$VERSIONS_DIR"/*custom_domain*.py; do
        [ -e "$path" ] || continue
        base="$(basename "$path")"
        [ "$base" = "$CANONICAL" ] && continue
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
    print("ERROR: revisiones duplicadas detectadas:", file=sys.stderr)
    for rev, files in duplicates.items():
        print(f"  {rev}: {files}", file=sys.stderr)
    print("Elimina manualmente los duplicados y vuelve a ejecutar.", file=sys.stderr)
    sys.exit(1)

heads = []
for path in sorted(versions.glob("*.py")):
    text = path.read_text(encoding="utf-8", errors="ignore")
    rev_m = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
    down_m = re.search(r"^down_revision\s*=\s*(.+)$", text, re.M)
    if not rev_m:
        continue
    down = down_m.group(1).strip() if down_m else "None"
    if down in ("None", "null"):
        heads.append(rev_m.group(1))

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

computed_heads = sorted(all_revs - referenced)
if len(computed_heads) > 1:
    print(f"AVISO: varias heads detectadas: {computed_heads}", file=sys.stderr)
    print("Si persisten tras limpiar duplicados, puede hacer falta flask db merge.", file=sys.stderr)
else:
    print(f"==> Head actual: {computed_heads[0] if computed_heads else 'desconocida'}")
PY

echo "==> Listo."
