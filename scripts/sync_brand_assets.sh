#!/usr/bin/env bash
set -euo pipefail

# Sync SignaPlan brand PNGs from logos_signaplan/ into app/static/img/brand/
# Missing source tree or files: warn and exit 0 (do not fail deploy).

YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/logos_signaplan"
DEST="$ROOT/app/static/img/brand"

# Canonical sources (ignore *_con_fondo.png - archived old assets)
EXPECTED=(
  "Logo.png"
  "Logo + Nombre.png"
  "Nombre.png"
  "Wallpaper.png"
)

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
  echo -e "${YELLOW}AVISO: $SRC no contiene Logo.png / Logo + Nombre.png / Nombre.png / Wallpaper.png - se omiten assets de marca${NC}"
  exit 0
fi

mkdir -p "$DEST"

copied=()

copy_if_exists() {
  local src_name="$1"
  local dest_name="$2"
  local src_path="$SRC/$src_name"
  if [[ -f "$src_path" ]]; then
    cp -f "$src_path" "$DEST/$dest_name"
    copied+=("$src_name -> $dest_name")
  fi
}

# Si el export trae blanco opaco (p.ej. Logo + Nombre), quitarlo antes de copiar.
# Sin Pillow: aviso limpio y se sigue (el build Docker lo aplica con Pillow).
if command -v python3 >/dev/null 2>&1 && [[ -f "$ROOT/scripts/knockout_brand_white.py" ]]; then
  python3 "$ROOT/scripts/knockout_brand_white.py" 2>&1 || true
fi

copy_if_exists "Logo.png" "logo-mark.png"
copy_if_exists "Logo + Nombre.png" "logo-horizontal.png"
copy_if_exists "Logo + Nombre_con_fondo.png" "logo-horizontal-on-dark.png"
copy_if_exists "Nombre.png" "logo-wordmark.png"
copy_if_exists "Wallpaper.png" "wallpaper.png"

# Quitar margen vacío del canvas (el export suele venir muy aireado).
if command -v python3 >/dev/null 2>&1 && [[ -f "$ROOT/scripts/trim_brand_margins.py" ]]; then
  python3 "$ROOT/scripts/trim_brand_margins.py" 2>&1 || true
fi

# Favicons 48/192 para Google SERP
if command -v python3 >/dev/null 2>&1 && [[ -f "$ROOT/scripts/generate_favicons.py" ]]; then
  python3 "$ROOT/scripts/generate_favicons.py" 2>&1 || true
fi

echo -e "${GREEN}Assets de marca sincronizados -> $DEST${NC}"
if [[ ${#copied[@]} -eq 0 ]]; then
  echo -e "${YELLOW}  (ningun archivo copiado)${NC}"
else
  for line in "${copied[@]}"; do
    echo -e "${GREEN}  OK $line${NC}"
  done
fi

