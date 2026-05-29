#!/bin/sh
set -e

echo "Verificando migraciones..."
if [ ! -f "migrations/env.py" ]; then
    echo "No se encontró migrations/env.py, inicializando migraciones..."
    flask db init
    flask db migrate -m "Initial migration"
fi

echo "Ejecutando migraciones..."
flask db upgrade

echo "Creando usuario administrador (si no existe)..."
python create_admin.py

echo "Iniciando la aplicación..."
exec python run.py
