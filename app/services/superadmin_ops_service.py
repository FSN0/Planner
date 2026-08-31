# app/services/superadmin_ops_service.py
#
# Operaciones de plataforma: KPIs por tenant, desactivar/borrar, impersonación.

from datetime import datetime, timedelta

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import create_engine, text

from flask import current_app

from app import db
from app.models import ROLE_ADMIN, Tenant

_IMPERSONATE_SALT = 'signaplan-superadmin-impersonate'
_IMPERSONATE_MAX_AGE = 300  # 5 minutos
DIAS_PURGA_TRAS_DESACTIVAR = 30


def _engine():
    return create_engine(
        current_app.config.get('SQLALCHEMY_DATABASE_URI'),
        pool_pre_ping=True,
    )


def _serializer():
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        raise RuntimeError('SECRET_KEY no configurada.')
    return URLSafeTimedSerializer(secret_key=secret, salt=_IMPERSONATE_SALT)


def tenant_kpis(tenant):
    """Métricas ligeras leyendo el schema del tenant con conexión aislada."""
    out = {
        'usuarios': 0,
        'obras': 0,
        'fichajes_7d': 0,
        'last_activity': None,
        'dias_sin_uso': None,
        'admin_email': None,
    }
    schema = tenant.schema_name
    if not schema:
        return out
    engine = _engine()
    try:
        with engine.connect() as conn:
            out['usuarios'] = conn.execute(text(
                f"SELECT COUNT(*) FROM {schema}.users "
                f"WHERE COALESCE(is_deleted,false)=false"
            )).scalar() or 0
            out['obras'] = conn.execute(text(
                f"SELECT COUNT(*) FROM {schema}.obras "
                f"WHERE COALESCE(is_deleted,false)=false"
            )).scalar() or 0
            try:
                out['fichajes_7d'] = conn.execute(text(
                    f"SELECT COUNT(*) FROM {schema}.fichajes_eventos "
                    f"WHERE ocurrido_en >= NOW() - INTERVAL '7 days'"
                )).scalar() or 0
            except Exception:
                out['fichajes_7d'] = 0
            try:
                last = conn.execute(text(
                    f"SELECT MAX(timestamp) FROM {schema}.system_logs"
                )).scalar()
                out['last_activity'] = last
            except Exception:
                out['last_activity'] = None
            admin = conn.execute(text(
                f"SELECT email FROM {schema}.users "
                f"WHERE role=:role AND COALESCE(is_deleted,false)=false "
                f"ORDER BY id ASC LIMIT 1"
            ), {'role': ROLE_ADMIN}).scalar()
            out['admin_email'] = admin
    finally:
        engine.dispose()

    if out['last_activity']:
        try:
            delta = datetime.utcnow() - out['last_activity'].replace(tzinfo=None)
            out['dias_sin_uso'] = max(0, delta.days)
        except Exception:
            out['dias_sin_uso'] = None
    elif tenant.created_at:
        try:
            out['dias_sin_uso'] = max(
                0, (datetime.utcnow() - tenant.created_at.replace(tzinfo=None)).days
            )
        except Exception:
            pass
    return out


def enrich_tenants(tenants):
    return [
        {'tenant': t, 'kpis': tenant_kpis(t), 'purge_ready': puede_purgar(t)}
        for t in tenants
    ]


def desactivar_tenant(tenant):
    tenant.is_active = False
    tenant.deactivated_at = datetime.utcnow()
    db.session.commit()
    return tenant


def reactivar_tenant(tenant):
    tenant.is_active = True
    tenant.deactivated_at = None
    db.session.commit()
    return tenant


def puede_purgar(tenant):
    """Siempre se puede borrar con confirmación del subdominio (irreversible)."""
    return bool(tenant and tenant.schema_name and tenant.schema_name != 'public')


def dias_para_purga(tenant):
    """Compat: ya no hay espera obligatoria; None = borrable ya."""
    return None


def purgar_tenant(tenant, confirm_subdominio):
    """DROP SCHEMA CASCADE + borra fila en public.tenants. Irreversible."""
    from app import is_safe_schema_name

    if (confirm_subdominio or '').strip() != tenant.subdominio:
        raise ValueError(
            f'Escribe exactamente el subdominio «{tenant.subdominio}» para confirmar.'
        )
    schema = tenant.schema_name
    if not schema or schema == 'public' or not is_safe_schema_name(schema):
        raise ValueError('Esquema no válido.')
    # Asegura search_path fuera del schema que vamos a tirar.
    db.session.execute(text('SET search_path TO public'))
    db.session.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
    db.session.delete(tenant)
    db.session.commit()


def crear_token_impersonacion(tenant, admin_user_id=None):
    """
    Token de corta vida para entrar en el tenant como su admin.
    Si no se pasa admin_user_id, se resuelve el primer admin activo.
    """
    uid = admin_user_id
    if uid is None:
        engine = _engine()
        try:
            with engine.connect() as conn:
                uid = conn.execute(text(
                    f"SELECT id FROM {tenant.schema_name}.users "
                    f"WHERE role=:role AND COALESCE(active,false)=true "
                    f"AND COALESCE(is_deleted,false)=false "
                    f"ORDER BY id ASC LIMIT 1"
                ), {'role': ROLE_ADMIN}).scalar()
        finally:
            engine.dispose()
    if not uid:
        raise ValueError('No hay un administrador activo en este tenant.')
    return _serializer().dumps({
        'tid': tenant.id,
        'uid': int(uid),
        'sub': tenant.subdominio,
    })


def leer_token_impersonacion(token, tenant_esperado):
    try:
        data = _serializer().loads(token, max_age=_IMPERSONATE_MAX_AGE)
    except SignatureExpired as exc:
        raise ValueError('El enlace de acceso ha caducado. Genera uno nuevo desde superadmin.') from exc
    except BadSignature as exc:
        raise ValueError('Enlace de impersonación no válido.') from exc
    if int(data.get('tid') or 0) != int(tenant_esperado.id):
        raise ValueError('El enlace no corresponde a esta empresa.')
    if (data.get('sub') or '') != tenant_esperado.subdominio:
        raise ValueError('El enlace no corresponde a esta empresa.')
    return int(data['uid'])


def seed_tenant_content(tenant, qty=None, activar_fichaje=True):
    """Rellena el schema del tenant SIN marcar modo demo (sin banner)."""
    from flask import g

    from app import is_safe_schema_name
    from app.models import User
    from app.services.demo_data_service import generar_datos_demo

    schema = tenant.schema_name
    if not is_safe_schema_name(schema):
        raise ValueError('Esquema de tenant no válido.')

    prev = getattr(g, 'current_tenant', None)
    try:
        db.session.execute(text(f'SET search_path TO {schema}, public'))
        g.current_tenant = tenant
        admin = (
            User.query
            .filter_by(role=ROLE_ADMIN, is_deleted=False)
            .order_by(User.id.asc())
            .first()
        )
        qty_out = generar_datos_demo(
            actor_user=admin,
            activar_fichaje=activar_fichaje,
            qty=qty,
            marcar_demo=False,
        )
        db.session.commit()
        return qty_out
    except Exception:
        db.session.rollback()
        raise
    finally:
        try:
            db.session.execute(text('SET search_path TO public'))
        except Exception:
            pass
        g.current_tenant = prev
