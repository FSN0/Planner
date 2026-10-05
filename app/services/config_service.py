from flask import g, has_app_context, has_request_context
from sqlalchemy import text

from app import db
from app.models import ConfiguracionGlobal
from app.utils.crypto_utils import encrypt_data, decrypt_data

_CACHE_ATTR = '_tenant_config_cache'


def _cache():
    if not has_request_context():
        return None
    cache = getattr(g, _CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(g, _CACHE_ATTR, cache)
    return cache


def _cache_key(clave: str, desencriptar: bool) -> str:
    return f'{clave}|{1 if desencriptar else 0}'


def set_tenant_config(clave: str, valor: str, encriptar: bool = False):
    """
    Guarda o actualiza una configuración en el esquema del cliente actual.
    Si encriptar=True, el valor se cifra antes de guardarse en base de datos.
    """
    if valor and encriptar:
        valor_guardar = encrypt_data(valor)
    else:
        valor_guardar = valor

    config = ConfiguracionGlobal.query.filter_by(clave=clave).first()
    if config:
        config.valor = valor_guardar
    else:
        config = ConfiguracionGlobal(clave=clave, valor=valor_guardar)
        db.session.add(config)

    db.session.commit()
    _restore_tenant_search_path()

    cache = _cache()
    if cache is not None:
        # Invalida ambas variantes (plain / decrypt)
        cache.pop(_cache_key(clave, False), None)
        cache.pop(_cache_key(clave, True), None)


def _restore_tenant_search_path():
    """
    commit() puede devolver la conexión al pool y perder SET search_path.
    Sin esto, el seed del alta (que corre en signaplan.com, no en el
    subdominio del tenant) escribe en public o revienta en silencio.
    """
    if not has_app_context():
        return
    tenant = getattr(g, 'current_tenant', None)
    schema = getattr(tenant, 'schema_name', None)
    if not schema:
        return
    from app import is_safe_schema_name
    if not is_safe_schema_name(schema):
        return
    try:
        db.session.execute(text(f'SET search_path TO {schema}, public'))
    except Exception:
        pass


def get_tenant_config(clave: str, desencriptar: bool = False, default=None):
    """
    Obtiene una configuración del esquema del cliente actual.
    Si desencriptar=True, desencripta el valor al vuelo antes de devolverlo.
    Si la fila existe pero el valor está vacío, usa default (p.ej. env ODOO_*).
    Cache por request para evitar N consultas idénticas en onboarding/sidebar.
    """
    cache = _cache()
    key = _cache_key(clave, desencriptar)
    if cache is not None and key in cache:
        stored = cache[key]
        return default if stored['miss'] else stored['value']

    config = ConfiguracionGlobal.query.filter_by(clave=clave).first()
    if not config:
        if cache is not None:
            cache[key] = {'miss': True, 'value': None}
        return default

    valor = config.valor
    if desencriptar and valor:
        try:
            valor = decrypt_data(valor)
        except Exception:
            valor = config.valor

    if valor is None or (isinstance(valor, str) and not str(valor).strip()):
        if cache is not None:
            cache[key] = {'miss': True, 'value': None}
        return default

    if cache is not None:
        cache[key] = {'miss': False, 'value': valor}
    return valor
