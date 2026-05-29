#!/bin/bash

set -e  # Detener el script si hay algún error

echo "🛑 Deteniendo y eliminando contenedores, volúmenes e imágenes..."
docker-compose down -v --remove-orphans
docker system prune -a -f

echo "🗑️ Eliminando directorio de migraciones..."
rm -rf app/migrations/

echo "🔧 Reconstruyendo la aplicación sin caché..."
docker-compose build --no-cache
docker-compose up -d

echo "📦 Esperando a que los contenedores inicien..."
sleep 5

echo "🚀 Inicializando la base de datos y aplicando migraciones..."
docker exec -it project-web-1 bash -c "
    flask db init &&
    flask db migrate -m 'Initial migration with updated User model and new features' &&
    flask db upgrade
"

echo "🔄 Reiniciando el contenedor web..."
docker-compose restart web

# ... (parte anterior del script igual) ...

# Opción para crear el usuario admin
read -p "¿Deseas crear el usuario administrador? (y/n): " create_admin
if [[ $create_admin == "y" ]]; then
    echo "👤 Creando empresa principal y usuario administrador..."
    docker exec -i project-web-1 flask shell <<EOF
from app import db
from app.models import User, Company
from werkzeug.security import generate_password_hash

# 1. Crear la empresa primero (ya que la DB está vacía)
empresa = Company.query.filter_by(code="ADMIN").first()
if not empresa:
    empresa = Company(
        code="ADMIN",
        nombre="Empresa Principal SOCTEC",
        is_internal=True,  # Importante: marcar como interna
        color="#a8d5ba"
    )
    db.session.add(empresa)
    db.session.commit()
    print(f"🏢 Empresa creada: {empresa.nombre} (ID: {empresa.id})")

# 2. Crear el usuario asignándole el ID de la empresa
if not User.query.filter_by(email="admin@example.com").first():
    admin = User(
        email="admin@example.com",
        password_hash=generate_password_hash("admin123"),
        role="admin",
        name="Admin",
        lastname="Principal",
        dni="00000000X",
        company_id=empresa.id,  # USA EL ID, NO EL CÓDIGO DIRECTAMENTE
        active=True
    )
    db.session.add(admin)
    db.session.commit()
    print("✅ Usuario administrador creado: admin@example.com / admin123")
else:
    print("⚠️ El usuario admin ya existe.")
EOF
fi

echo "✅ Proceso completado correctamente."

echo "✅ Proceso completado correctamente."

