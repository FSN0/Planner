#!/bin/bash
set -e

echo "=== SignaPlan DEV - Iniciando ==="

echo "[1/3] Verificando migraciones..."
if [ ! -d "migrations/versions" ] || [ -z "$(ls -A migrations/versions/ 2>/dev/null)" ]; then
    echo "  → No hay migraciones, inicializando..."
    flask db init 2>/dev/null || true
    flask db migrate -m "Initial migration"
fi

echo "[2/3] Aplicando migraciones..."
flask db upgrade

echo "[3/3] Arrancando servidor de desarrollo..."
exec python run.py
