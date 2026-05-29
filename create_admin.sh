#!/bin/bash
echo "👤 Gestionando usuario administrador..."

# Usamos exec(''' ... ''') para evitar errores de indentación en la consola
docker exec -i project-web-1 flask shell <<EOF
exec('''
from app import db
from app.models import User, Company
from werkzeug.security import generate_password_hash

print("--- INICIANDO ---")

# 1. RECUPERAR O CREAR EMPRESA
# Como ya sabemos que la empresa existe (del intento anterior), la buscamos.
empresa = Company.query.filter_by(code="ADMIN").first()

if not empresa:
    print("✨ Creando empresa...")
    empresa = Company(
        code="ADMIN",
        nombre="Empresa Principal SOCTEC",
        is_internal=True,
        color="#a8d5ba"
    )
    db.session.add(empresa)
    db.session.commit()
    print(f"✅ Empresa creada con ID: {empresa.id}")
else:
    print(f"ℹ️ La empresa ya existe con ID: {empresa.id}")

# 2. VERIFICAR SI EL USUARIO EXISTE
user = User.query.filter_by(email="admin@example.com").first()

if user:
    print("⚠️ El usuario admin ya existe. No se hace nada.")
else:
    print("✨ Creando usuario admin...")
    try:
        admin = User(
            email="admin@example.com",
            password_hash=generate_password_hash("admin123"),
            role="admin",
            name="Admin",
            lastname="Principal",
            dni="00000000X",
            company_id=empresa.id,  # Usamos el ID de la empresa recuperada arriba
            active=True
        )
        db.session.add(admin)
        db.session.commit()
        print("✅ Usuario administrador creado: admin@example.com / admin123")
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error creando usuario: {e}")
''')
EOF

echo "✅ Script finalizado."
