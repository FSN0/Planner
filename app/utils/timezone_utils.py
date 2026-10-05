# app/utils/timezone_utils.py
#
# Convención del proyecto:
#   - Los DateTime en BD se almacenan como naive UTC.
#   - Visualización y lógica de negocio ("hoy", cortes) usan la zona del tenant.

from datetime import datetime, date, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

DEFAULT_TIMEZONE = 'Europe/Madrid'
CONFIG_KEY_TIMEZONE = 'zona_horaria'

COMMON_TIMEZONES = [
    ('Europe/Madrid', 'España peninsular (CET/CEST)'),
    ('Atlantic/Canary', 'Islas Canarias'),
    ('Europe/Lisbon', 'Portugal'),
    ('Europe/London', 'Reino Unido'),
    ('Europe/Paris', 'Francia'),
    ('Europe/Berlin', 'Alemania'),
    ('Europe/Rome', 'Italia'),
    ('America/Mexico_City', 'México (Ciudad de México)'),
    ('America/Bogota', 'Colombia'),
    ('America/Argentina/Buenos_Aires', 'Argentina'),
    ('America/Santiago', 'Chile'),
    ('UTC', 'UTC (sin desplazamiento)'),
]


def _safe_zone(name):
    try:
        ZoneInfo(name)
        return name
    except Exception:
        return DEFAULT_TIMEZONE


@lru_cache(maxsize=1)
def get_app_timezone():
    """Zona horaria global de la aplicación (lógica de negocio y fichajes)."""
    try:
        from app.models import ConfiguracionGlobal
        conf = ConfiguracionGlobal.query.filter_by(clave=CONFIG_KEY_TIMEZONE).first()
        if conf and conf.valor:
            return _safe_zone(conf.valor.strip())
    except Exception:
        pass
    return DEFAULT_TIMEZONE


def invalidate_app_timezone_cache():
    get_app_timezone.cache_clear()


def get_user_timezone(user=None):
    """Zona horaria efectiva: siempre la del tenant (un huso por empresa)."""
    return get_app_timezone()


def utc_now():
    """Hora actual en UTC naive (para persistir en BD)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_in_tz(tz_name):
    """Hora actual naive en una zona concreta."""
    return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)


def now_local():
    """Hora actual naive en la zona global de la app (cortes, ausencias)."""
    return now_in_tz(get_app_timezone())


def today_local():
    """Fecha de hoy según la zona global de la app."""
    return now_local().date()


def utc_to_local(dt, user=None):
    """Convierte datetime naive UTC → naive en zona del usuario."""
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return None
    tz = get_user_timezone(user)
    if dt.tzinfo is not None:
        aware = dt.astimezone(timezone.utc)
    else:
        aware = dt.replace(tzinfo=timezone.utc)
    return aware.astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def local_to_utc(dt, tz_name=None):
    """Convierte datetime naive en zona dada → naive UTC."""
    if dt is None:
        return None
    tz = tz_name or get_app_timezone()
    aware = dt.replace(tzinfo=ZoneInfo(tz))
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def parse_odoo_datetime(dt_str):
    """
    Odoo envía timestamps en UTC. Devuelve naive UTC para almacenar en BD.
    """
    if not dt_str:
        return None
    try:
        dt_utc = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        return dt_utc.replace(tzinfo=None)
    except ValueError:
        return None


def format_datetime(dt, fmt=None, user=None):
    """Formatea un datetime UTC de BD en la zona horaria del usuario."""
    if dt is None:
        return ''
    if fmt is None:
        try:
            from app.services.i18n_service import datetime_format
            fmt = datetime_format()
        except Exception:
            fmt = '%d/%m/%Y %H:%M'
    local_dt = utc_to_local(dt, user)
    return local_dt.strftime(fmt)


def format_time(dt, user=None):
    return format_datetime(dt, '%H:%M', user)


def format_date(dt, fmt=None, user=None):
    if dt is None:
        return ''
    if fmt is None:
        try:
            from app.services.i18n_service import date_format
            fmt = date_format()
        except Exception:
            fmt = '%d/%m/%Y'
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.strftime(fmt)
    local_dt = utc_to_local(dt, user)
    return local_dt.strftime(fmt)


def timezone_label(tz_name):
    for code, label in COMMON_TIMEZONES:
        if code == tz_name:
            return label
    return tz_name


def is_valid_timezone(tz_name):
    return tz_name in available_timezones()
