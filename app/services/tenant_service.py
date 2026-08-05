import re
from app import db
from sqlalchemy import text
from app.models import Tenant, User, ROLE_ADMIN, Company
from app.services.tenant_domain_service import validate_custom_domain, assert_custom_domain_available
from werkzeug.security import generate_password_hash
from flask_migrate import stamp 


def provision_new_tenant(
    nombre_empresa,
    subdominio,
    admin_email,
    admin_password,
    custom_domain=None,
    modulos_activos=None,
    email_verified=True,
    active=True,
):
    """
    Registra un nuevo cliente, construye su esquema aislado, crea su empresa matriz y su primer administrador.

    email_verified/active: True en superadmin y demos; el alta pública deja
    active=True y email_verified=False (entrar sí; verificar refuerza confianza).
    """
    subdominio = (subdominio or '').lower().strip()
    # Validación estricta: solo letras minúsculas, números y guiones.
    # Evita inyección SQL al construir el nombre de esquema y CREATE SCHEMA.
    if not re.match(r'^[a-z0-9-]+$', subdominio):
        raise ValueError("El subdominio solo puede contener letras minúsculas, números y guiones.")

    schema_name = f"tenant_{subdominio.replace('-', '_')}"

    try:
        db.session.execute(text("SET search_path TO public"))
        
        if Tenant.query.filter_by(subdominio=subdominio).first():
            raise ValueError(f"El subdominio '{subdominio}' ya está en uso.")

        custom_domain = validate_custom_domain(custom_domain)
        assert_custom_domain_available(custom_domain)

        from app.services.plan_service import LIMITE_PLAN_GRATUITO, PLAN_FREE

        nuevo_tenant = Tenant(
            nombre=nombre_empresa, 
            subdominio=subdominio,
            custom_domain=custom_domain,
            schema_name=schema_name,
            plan=PLAN_FREE,
            limite_empleados=LIMITE_PLAN_GRATUITO,
            modulos_activos=modulos_activos or {},
        )
        db.session.add(nuevo_tenant)
        db.session.commit()
        
        tenant_id = nuevo_tenant.id
        
        # 2. Crear infraestructura física
        db.session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        db.session.commit()
        
        # 3. Limpiamos la caché de la sesión actual
        db.session.remove() 
        
        # 4. Obtenemos la conexión ACTIVA de esta transacción específica
        connection = db.session.connection()
        
        # 5. Aplicamos el esquema SOLO a esta conexión
        connection.execute(text(f"SET search_path TO {schema_name}"))
        
        # 6. Creamos las tablas pasándole explícitamente esta misma conexión (bind=connection)
        db.metadata.create_all(bind=connection)

        # 6.4. create_all no aplica triggers: el libro de fichajes debe ser
        # inmutable también en tenants nuevos (no solo en los que pasaron
        # por la migración Alembic del ledger).
        from app.ddl import proteger_libro_fichajes
        proteger_libro_fichajes(
            lambda sql: connection.execute(text(sql)),
            schema_name,
        )

        # ========================================================
        # 6.5. EL SELLO ORTODOXO: Marcar como migrado a la última versión
        # ========================================================
        stamp(directory='migrations', revision='head')

        # >>> NUEVO: 7. Crear la Empresa Interna matriz <<<
        empresa_interna = Company(
            nombre=nombre_empresa,
            is_internal=True,      # Fundamental para que Odoo sepa dónde meter a la plantilla
            code=subdominio[:15].upper() # Generamos un código corto basado en el subdominio
        )
        db.session.add(empresa_interna)
        db.session.flush() # Flush para que la base de datos le asigne un ID sin cerrar la transacción

        # 8. Crear el administrador asignado a esta nueva empresa
        admin_user = User(
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            role=ROLE_ADMIN,
            name="Administrador",
            lastname=nombre_empresa,
            dni=f"ADMIN-{tenant_id}",
            active=bool(active),
            email_verified=bool(email_verified),
            company_id=empresa_interna.id,  # vinculamos al admin con la empresa
        )
        db.session.add(admin_user)
        db.session.commit()
        
        # 9. Regresar a public
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