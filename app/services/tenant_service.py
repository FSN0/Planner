from app import db
from sqlalchemy import text
from app.models import Tenant, User, ROLE_ADMIN
from werkzeug.security import generate_password_hash

def provision_new_tenant(nombre_empresa, subdominio, admin_email, admin_password):
    """
    Registra un nuevo cliente, construye su esquema aislado y crea su primer administrador.
    """
    schema_name = f"tenant_{subdominio.lower().strip()}"
    
    try:
        db.session.execute(text("SET search_path TO public"))
        
        if Tenant.query.filter_by(subdominio=subdominio).first():
            raise ValueError(f"El subdominio '{subdominio}' ya está en uso.")

        nuevo_tenant = Tenant(
            nombre=nombre_empresa, 
            subdominio=subdominio, 
            schema_name=schema_name
        )
        db.session.add(nuevo_tenant)
        db.session.commit()
        
        tenant_id = nuevo_tenant.id
        
        # 2. Crear infraestructura física
        db.session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        db.session.commit()
        
        # 3. Limpiamos la caché de la sesión actual
        db.session.remove() 
        
        # --- AQUÍ ESTÁ LA CORRECCIÓN CLAVE ---
        # 4. Obtenemos la conexión ACTIVA de esta transacción específica
        connection = db.session.connection()
        
        # 5. Aplicamos el esquema SOLO a esta conexión
        connection.execute(text(f"SET search_path TO {schema_name}"))
        
        # 6. Creamos las tablas pasándole explícitamente esta misma conexión (bind=connection)
        db.metadata.create_all(bind=connection)
        # ------------------------------------

        # 7. Crear el administrador
        admin_user = User(
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            role=ROLE_ADMIN,
            name="Administrador",
            lastname=nombre_empresa,
            dni=f"ADMIN-{tenant_id}", 
            active=True
        )
        db.session.add(admin_user)
        db.session.commit()
        
        # 8. Regresar a public
        db.session.execute(text("SET search_path TO public"))
        db.session.commit()
        
        tenant_final = db.session.query(Tenant).get(tenant_id)
        return tenant_final

    except Exception as e:
        db.session.rollback()
        try:
            db.session.execute(text("SET search_path TO public"))
        except:
            pass
        raise e