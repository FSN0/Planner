#!/bin/bash
# Script para automatizar las migraciones de la base de datos en Docker.
# Uso: ./migrate.sh "Mensaje descriptivo para la migración"

if [ "$#" -ne 1 ]; then
    echo "Uso: $0 \"Mensaje descriptivo para la migración\""
    exit 1
fi

MIGRATION_MESSAGE="$1"

echo "Reconstruyendo las imágenes Docker..."
docker compose build

echo "Levantando contenedores en modo detached..."
docker compose up -d

echo "Generando nueva migración (si hay cambios en los modelos)..."
docker exec -it project-web-1 flask db migrate -m "$MIGRATION_MESSAGE"

echo "Aplicando migraciones en esquema public y en todos los inquilinos..."
docker exec -it project-web-1 flask db upgrade

echo "Proceso de migración completado."
