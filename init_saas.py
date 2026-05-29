# init_saas.py

from app import create_app, db
from sqlalchemy import text
from app.services.tenant_service import provision_new_tenant

app = create_app()

with app.app_context():
    print("🚀 Iniciando el Big Bang del SaaS...")

    # 1. Forzar el esquema público
    db.session.execute(text("SET search_path TO public"))
    
    # 2. Crear la tabla de Tenants en el esquema público
    print("📁 Creando estructura global...")
    db.create_all()
    
    # 3. Crear tu primer cliente (Por ejemplo, tu cliente original para no perder sus datos, o uno de demo)
    print("🏗️ Provisionando el primer Inquilino (Tenant)...")
    try:
        # Cambia 'demo' por el subdominio que quieras probar en local (ej: localhost:5000 para public, demo.localhost:5000 para el tenant)
        tenant = provision_new_tenant(
            nombre_empresa="Constructora Demo S.L.", 
            subdominio="demo",
            admin_email="admin@demo.com",
            admin_password="1234"
        )
        print(f"✅ ¡Éxito! Inquilino creado: {tenant.nombre} en el esquema '{tenant.schema_name}'")
        
        # Aquí podrías inyectar el primer usuario administrador (ROLE_ADMIN) para este tenant.
        
    except Exception as e:
        print(f"⚠️ Error durante la provisión: {e}")

    print("🏁 Inicialización completada.")