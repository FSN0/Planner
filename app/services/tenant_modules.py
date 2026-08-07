# app/services/tenant_modules.py
#
# Personalizaciones por cliente.
#
# Lo genérico del producto va para todos. Lo de un cliente concreto (Soltec,
# o el siguiente con un flujo a medida) se enciende con una clave en
# Tenant.modulos_activos desde el panel superadmin. Así no se cuela en el
# resto de tenants y no hace falta if subdomain == 'x' repartidos por el código.
#
# Convención:
# - Clave ausente → default (False, salvo módulos con default True documentado).
# - Clave True/False → valor explícito.
# - Fallback legacy solo si hace falta no romper un cliente ya en producción.

from flask import g, has_app_context, has_request_context


def current_tenant():
    if has_request_context() or has_app_context():
        return getattr(g, 'current_tenant', None)
    return None


def get_modulos_activos(tenant=None):
    tenant = tenant if tenant is not None else current_tenant()
    if not tenant:
        return {}
    return getattr(tenant, 'modulos_activos', None) or {}


def module_enabled(key, tenant=None, *, default=False):
    """True si el módulo está activo para el tenant."""
    mods = get_modulos_activos(tenant)
    if key not in mods:
        return bool(default)
    return bool(mods.get(key))


def has_avisos_laborales(tenant=None):
    """
    Click para acusar/reactivar logs de Planificación y Solicitud + badge laboral.

    Personalización Soltec (y futuros clientes que lo pidan). Se activa con
    modulos_activos['avisos_laborales']=True. Si la clave no existe, se mantiene
    el comportamiento histórico solo para el tenant cuyo subdominio es «soltec».
    """
    mods = get_modulos_activos(tenant)
    if 'avisos_laborales' in mods:
        return bool(mods.get('avisos_laborales'))
    tenant = tenant if tenant is not None else current_tenant()
    sub = (getattr(tenant, 'subdominio', None) or '').strip().lower()
    return sub == 'soltec'
