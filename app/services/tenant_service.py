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
        # 1. Asegurar estar en public para registrar el Tenant
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
        
        # 2. Crear infraestructura física (Esquema)
        db.session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        db.session.commit()
        
        # 3. EL TRUCO: Cerrar la sesión actual para forzar a SQLAlchemy a olvidar 
        # cualquier caché de tablas y metadatos de la sesión anterior.
        db.session.remove() 
        
        # 4. Cambiar el search_path en esta NUEVA sesión limpia
        db.session.execute(text(f"SET search_path TO {schema_name}"))
        
        # 5. Crear tablas en el nuevo esquema
        db.metadata.create_all(db.engine)
        
        # 6. Crear el administrador (ahora este insert irá al esquema tenant_X)
        admin_user = User(
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            role=ROLE_ADMIN,
            name="Administrador",
            lastname=nombre_empresa,
            dni=f"ADMIN-{nuevo_tenant.id}", 
            active=True
        )
        db.session.add(admin_user)
        db.session.commit()
        
        # 7. Regresar al estado limpio
        db.session.execute(text("SET search_path TO public"))
        db.session.commit()
        
        return nuevo_tenant

    except Exception as e:
        # Siempre hacemos rollback ante cualquier error
        db.session.rollback()
        # Volvemos a public para no dejar la sesión "colgada" en un esquema fallido
        try:
            db.session.execute(text("SET search_path TO public"))
        except:
            pass
        raise e