#!/bin/bash
set -e  # Detener el script si hay algún error

echo "🛑 Deteniendo y eliminando contenedores y volúmenes (DATA LOST)..."
docker compose down -v --remove-orphans

echo "🗑️ Eliminando carpetas de migraciones corruptas..."
rm -rf migrations/
rm -rf app/migrations/

echo "🔧 Reconstruyendo y levantando contenedores..."
docker compose build
docker compose up -d

echo "📦 Esperando a que PostgreSQL inicie (10 segundos)..."
sleep 10

echo "🚀 Ejecutando el BIG BANG del SaaS..."
# Aquí usamos tu script maestro de la Fase 2 para crear el esquema public y el primer Tenant
docker compose exec web python init_saas.py

echo "✅ Proceso completado correctamente."
echo "👉 Ya puedes entrar en: http://localhost:5000/superadmin/"