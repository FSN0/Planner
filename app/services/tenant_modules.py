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


def is_soltec_tenant(tenant=None):
    tenant = tenant if tenant is not None else current_tenant()
    sub = (getattr(tenant, 'subdominio', None) or '').strip().lower()
    return sub == 'soltec'


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


def _soltec_fallback(key, tenant=None):
    """Si la clave no está en JSON, Soltec conserva el extra histórico."""
    mods = get_modulos_activos(tenant)
    if key in mods:
        return bool(mods.get(key))
    return is_soltec_tenant(tenant)


def has_avisos_laborales(tenant=None):
    """
    Click para acusar/reactivar logs de Planificación y Solicitud + badge laboral.

    Personalización Soltec (y futuros clientes que lo pidan). Se activa con
    modulos_activos['avisos_laborales']=True. Si la clave no existe, se mantiene
    el comportamiento histórico solo para el tenant cuyo subdominio es «soltec».
    """
    return _soltec_fallback('avisos_laborales', tenant)


def has_notas(tenant=None):
    """Centro de notas / reuniones. Apagado en el SaaS genérico."""
    return _soltec_fallback('notas', tenant)


def has_valoraciones(tenant=None):
    """Puntuación de operarios: va en el producto, no es módulo a medida."""
    return True


def has_auditoria_vehiculos(tenant=None):
    """
    Auditoría de km / anomalías de flota (odómetro, TMS).
    El cuadrante de coches es producto; esto es extra a medida.
    """
    return _soltec_fallback('auditoria_vehiculos', tenant)


def has_documentacion(tenant=None):
    """Documentación de empresa y de personas. Encendido si la clave no está."""
    return module_enabled('documentacion', tenant, default=True)


def has_certificacion(tenant=None):
    """Certificación de horario por mes. Encendido si la clave no está."""
    return module_enabled('certificacion', tenant, default=True)


def has_contratacion(tenant=None):
    """Altas que entran solo a perfil y documentos. Encendido si la clave no está."""
    return module_enabled('contratacion', tenant, default=True)


def has_portal_subcontrata(tenant=None):
    """Portal del admin de subcontrata. Encendido si la clave no está."""
    return module_enabled('portal_subcontrata', tenant, default=True)


def has_portal_ausencias(tenant=None):
    """
    El trabajador pide y consulta ausencias en /fichaje.

    Producto genérico: encendido si la clave no está.
    Soltec (vacaciones en Odoo): apagado si la clave no está.
    La oficina sigue viendo /admin/ausencias y el sync de hr.leave.
    """
    mods = get_modulos_activos(tenant)
    if 'portal_ausencias' in mods:
        return bool(mods.get('portal_ausencias'))
    return not is_soltec_tenant(tenant)


# --- Ajustes de tenant (ConfiguracionGlobal), no módulos superadmin ---

CONFIG_HORA_CORTE_ACTIVA = 'hora_corte_activa'
CONFIG_HORA_CORTE_DESTINATARIOS = 'hora_corte_destinatarios'
CONFIG_CONFORME_JORNADA = 'conforme_jornada_activo'


def _config_flag(clave, *, default_generic, default_soltec):
    from app.services.config_service import get_tenant_config

    raw = get_tenant_config(clave, default=None)
    if raw is None:
        return bool(default_soltec if is_soltec_tenant() else default_generic)
    return str(raw).strip().lower() in ('true', '1', 'yes', 'on')


def hora_corte_activa():
    """Marca ausencias de fichaje y manda el resumen diario al llegar la hora.

    Fuente de verdad: matriz de correos (evento ``hora_corte_reporte``).
    Si aún no hay matriz, cae al flag legado / default Soltec.
    """
    try:
        from app.services.notification_catalog import MODE_OFF
        from app.services.notification_dispatch_service import get_event_settings
        from app.services.config_service import get_tenant_config
        from app.services.notification_catalog import CONFIG_MIGRATED

        if get_tenant_config(CONFIG_MIGRATED, default=None):
            return get_event_settings('hora_corte_reporte')['mode'] != MODE_OFF
    except Exception:
        pass
    return _config_flag(
        CONFIG_HORA_CORTE_ACTIVA,
        default_generic=False,
        default_soltec=True,
    )


def hora_corte_destinatario_ids():
    from app.services.config_service import get_tenant_config

    raw = get_tenant_config(CONFIG_HORA_CORTE_DESTINATARIOS, default='') or ''
    ids = []
    for part in str(raw).split(','):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


def conforme_jornada_activo():
    """Firma del trabajador sobre la jornada. Apagada hasta que el cliente la pida."""
    return _config_flag(
        CONFIG_CONFORME_JORNADA,
        default_generic=False,
        default_soltec=False,
    )
