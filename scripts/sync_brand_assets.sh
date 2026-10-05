#!/usr/bin/env bash
# Sync SignaPlan brand PNGs from logos_signaplan/ into app/static/img/brand/
# Missing/corrupt sources: aviso y sigue (nunca tumba make/deploy).

set -euo pipefail

YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/logos_signaplan"
DEST="$ROOT/app/static/img/brand"
export PYTHONPATH="$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}"

EXPECTED=(
  "Logo.png"
  "Logo + Nombre.png"
  "Nombre.png"
  "Wallpaper.png"
)

# Script PIL sin traceback en consola.
run_pil_quiet() {
  local script="$1"
  [[ -f "$script" ]] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  local out
  out="$(python3 "$script" 2>&1)" || true
  if [[ -n "$out" ]]; then
    printf '%s\n' "$out" | grep -E '^(AVISO:|OK |skip |trimmed |wrote |missing |no content |.*knocked )' || true
  fi
  return 0
}

png_ok() {
  local path="$1"
  command -v python3 >/dev/null 2>&1 || return 0
  [[ -f "$ROOT/scripts/_pil_util.py" ]] || return 0
  python3 -c "
from pathlib import Path
from _pil_util import verify_png_or_warn
raise SystemExit(0 if verify_png_or_warn('sync_brand_assets.sh', Path(r'''$path''')) else 1)
" >/dev/null 2>&1
}

if [[ ! -d "$SRC" ]]; then
  echo -e "${YELLOW}AVISO: no existe $SRC - se omiten assets de marca${NC}"
  exit 0
fi

found_any=false
for f in "${EXPECTED[@]}"; do
  if [[ -f "$SRC/$f" ]]; then
    found_any=true
    break
  fi
done

if [[ "$found_any" != true ]]; then
  echo -e "${YELLOW}AVISO: $SRC sin logos canónicos - se omiten assets de marca${NC}"
  exit 0
fi

mkdir -p "$DEST" 2>/dev/null || {
  echo -e "${YELLOW}AVISO: no se pudo crear $DEST - se omiten assets de marca${NC}" >&2
  exit 0
}

# 1) Quitar blanco en orígenes (si Pillow/PNG fallan: silencio)
run_pil_quiet "$ROOT/scripts/knockout_brand_white.py"

copied=()

copy_if_valid() {
  local src_name="$1"
  local dest_name="$2"
  local src_path="$SRC/$src_name"
  [[ -f "$src_path" ]] || return 0
  if ! png_ok "$src_path"; then
    echo -e "${YELLOW}AVISO: origen corrupto, no se copia $src_name${NC}" >&2
    return 0
  fi
  cp -f "$src_path" "$DEST/$dest_name"
  copied+=("$src_name -> $dest_name")
}

# 2) Copiar solo PNGs válidos (si uno está truncado, no pisa el destino bueno)
copy_if_valid "Logo.png" "logo-mark.png"
copy_if_valid "Logo + Nombre.png" "logo-horizontal.png"
copy_if_valid "Logo + Nombre_con_fondo.png" "logo-horizontal-on-dark.png"
copy_if_valid "Nombre.png" "logo-wordmark.png"
copy_if_valid "Wallpaper.png" "wallpaper.png"

# 3) Recorte + favicons sobre destino
run_pil_quiet "$ROOT/scripts/trim_brand_margins.py"
run_pil_quiet "$ROOT/scripts/generate_favicons.py"

echo -e "${GREEN}Assets de marca sincronizados -> $DEST${NC}"
if [[ ${#copied[@]} -eq 0 ]]; then
  echo -e "${YELLOW}  (ningun archivo copiado)${NC}"
else
  for line in "${copied[@]}"; do
    echo -e "${GREEN}  OK $line${NC}"
  done
fi
