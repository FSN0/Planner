#!/bin/bash
set -e

echo "=== SignaPlan PROD - Iniciando ==="

echo "[1/2] Aplicando migraciones..."
flask db upgrade

echo "[2/2] Arrancando Gunicorn..."
exec gunicorn \
    --workers 4 \
    --timeout 120 \
    --bind 0.0.0.0:5000 \
    --access-logfile - \
    --error-logfile - \
    run:app
