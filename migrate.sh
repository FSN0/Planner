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

# --- CORRECCIÓN AQUÍ ---
# Se añade 'rm -rf migrations' antes de 'flask db init' para limpiar carpetas corruptas
echo "Verificando estado de migraciones..."
docker exec -it project-web-1 bash -c 'if [ ! -f "migrations/env.py" ]; then 
    echo "Carpeta de migraciones corrupta o inexistente. Reinicializando..."; 
    rm -rf migrations; 
    flask db init && flask db migrate -m "Initial migration"; 
fi'

# Opcional: Si existe algún problema con una revisión antigua, limpia la tabla alembic_version
echo "Limpiando la tabla alembic_version..."
docker exec -it project-db-1 psql -U postgres -d gestion_obra_saas -c "TRUNCATE TABLE alembic_version;"

echo "Marcando la versión head en la base de datos..."
docker exec -it project-web-1 flask db stamp head

echo "Generando migración: $MIGRATION_MESSAGE"
docker exec -it project-web-1 flask db migrate -m "$MIGRATION_MESSAGE"

echo "Aplicando migración en la base de datos..."
docker exec -it project-web-1 flask db upgrade

echo "Proceso de migración completado."
