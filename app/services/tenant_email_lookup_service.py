# app/services/tenant_email_lookup_service.py
#
# Resuelve «este correo → ¿en qué empresas puede entrar?».

from sqlalchemy import create_engine, text

from flask import current_app

from app.models import Tenant


def _engine():
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI')
    return create_engine(uri, pool_pre_ping=True)


def _puede_login_web_row(role, web_access):
    del role, web_access
    return True


def buscar_tenants_por_email(email):
    """
    Devuelve lista de dicts {tenant, user_name, email_verified} para emails con acceso web.

    Mensaje genérico hacia fuera: el caller no debe delatar si el correo
    existe cuando la lista está vacía.
    """
    email = (email or '').strip().lower()
    if not email or '@' not in email:
        return []

    tenants = (
        Tenant.query
        .filter_by(is_active=True)
        .order_by(Tenant.nombre.asc())
        .all()
    )
    if not tenants:
        return []

    resultados = []
    engine = _engine()
    try:
        with engine.connect() as conn:
            for tenant in tenants:
                schema = tenant.schema_name
                if not schema:
                    continue
                row = conn.execute(
                    text(
                        f"""
                        SELECT name, lastname, role,
                               COALESCE(web_access, false) AS web_access,
                               COALESCE(active, false) AS active,
                               COALESCE(is_deleted, false) AS is_deleted,
                               COALESCE(email_verified, false) AS email_verified
                        FROM {schema}.users
                        WHERE lower(email) = :email
                        LIMIT 1
                        """
                    ),
                    {'email': email},
                ).mappings().first()
                if not row:
                    continue
                if row['is_deleted'] or not row['active']:
                    continue
                if not _puede_login_web_row(row['role'], row['web_access']):
                    continue
                resultados.append({
                    'tenant': tenant,
                    'user_name': f"{row['name']} {row['lastname']}".strip(),
                    'role': row['role'],
                    'email_verified': bool(row['email_verified']),
                })
    finally:
        engine.dispose()

    return resultados
