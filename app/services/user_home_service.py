"""Destino tras login y enlace «Inicio» según rol y matriz de permisos."""
from __future__ import annotations

from datetime import date

from flask import url_for

from app.models import (
    ROLE_ADMIN,
    ROLE_JEFE,
    ROLE_LABORAL,
    ROLE_OPERARIO,
    ROLE_RRHH,
)

# Preferencia al elegir pantalla inicial para roles custom (solo oficina).
_OFFICE_HOME_MODULES = (
    'inicio',
    'tablero',
    'vehiculos',
    'vehiculos_libres',
    'auditoria_vehiculos',
    'directorio',
    'planificador',
    'reuniones',
    'trabajadores',
    'subcontratas',
    'solicitudes',
    'ausencias',
    'auditoria_fichajes',
    'mapa_fichajes',
    'registro_jornada',
    'integraciones',
    'sync_odoo',
    'soltec_alta_odoo',
    'soltec_portal',
    'primeros_pasos',
    'configuracion',
    'permisos',
    'logs',
)

_MODULE_ENDPOINTS: dict[str, str] = {
    'inicio': 'admin.panel',
    'tablero': 'admin.obras_detailed',
    'directorio': 'admin.obras_list',
    'planificador': 'admin.planificador_jo',
    'reuniones': 'notas.centro_mando',
    'trabajadores': 'admin.personal',
    'subcontratas': 'admin.companies',
    'solicitudes': 'admin.solicitudes_list',
    'ausencias': 'admin.ausencias_list',
    'vehiculos': 'admin.vehiculos',
    'vehiculos_libres': 'admin.vehiculos_libres',
    'auditoria_vehiculos': 'sync.auditoria_vehiculos',
    'auditoria_fichajes': 'sync.auditoria_fichajes',
    'mapa_fichajes': 'admin.mapa_fichajes',
    'registro_jornada': 'admin.registro_jornada',
    'integraciones': 'sync.panel',
    'sync_odoo': 'sync.odoo_panel',
    'soltec_alta_odoo': 'admin.sso_odoo_contactos',
    'soltec_portal': 'auth.sso_portal',
    'primeros_pasos': 'admin.primeros_pasos',
    'configuracion': 'admin.configuracion_global',
    'permisos': 'admin.permisos_roles',
    'logs': 'admin.system_logs',
}


def destino_portal_operario(user):
    """Primera pantalla del operario: fichaje primero."""
    from app.services.permission_service import user_can
    from app.services.fichaje_operario_service import tenant_tiene_fichaje_operario_module

    try:
        if (
            tenant_tiene_fichaje_operario_module()
            and user_can(user, 'operario_fichaje', 'r')
        ):
            return url_for('empleado.fichar')
        if user_can(user, 'operario_calendario', 'r'):
            return url_for('empleado.calendario')
        if user_can(user, 'operario_ausencias', 'r'):
            return url_for('empleado.ausencias')
    except Exception:
        pass
    return url_for('empleado.fichar')


def _module_available_for_tenant(module: str) -> bool:
    from app.services.permission_catalog import _permission_row_enabled

    if not _permission_row_enabled(module):
        return False
    if module == 'auditoria_vehiculos':
        from app.services.tenant_modules import get_modulos_activos, has_auditoria_vehiculos

        mods = get_modulos_activos()
        return bool(mods.get('odoo') and has_auditoria_vehiculos())
    return True


def _office_home_for_custom_role(user) -> str | None:
    from app.services.permission_service import user_can

    role = getattr(user, 'role', None)
    for module in _OFFICE_HOME_MODULES:
        if not _module_available_for_tenant(module):
            continue
        if not user_can(user, module, 'r'):
            continue
        endpoint = _MODULE_ENDPOINTS.get(module)
        if not endpoint:
            continue
        if module == 'tablero' and role == ROLE_JEFE:
            return url_for(endpoint, selected_date=date.today())
        return url_for(endpoint)
    return None


def home_url_for_user(user) -> str | None:
    """URL de entrada tras login. None si el perfil no tiene ningún módulo."""
    if not user:
        return None

    role = getattr(user, 'role', None)
    if role == ROLE_ADMIN:
        try:
            from app.services.onboarding_service import (
                debe_redirigir_a_wizard,
                tour_ya_autostart,
            )

            if debe_redirigir_a_wizard():
                if not tour_ya_autostart():
                    return url_for('admin.obras_detailed', tour='inicio')
                return url_for('admin.obras_detailed')
        except Exception:
            pass
        return url_for('admin.panel')
    if role == ROLE_JEFE:
        return url_for('jefe.obras_detailed', selected_date=date.today())
    if role in (ROLE_LABORAL, ROLE_RRHH):
        return url_for('admin.panel_laboral')
    if role == ROLE_OPERARIO:
        return destino_portal_operario(user)

    office = _office_home_for_custom_role(user)
    if office:
        return office
    return destino_portal_operario(user) if _has_portal_access(user) else None


def _has_portal_access(user) -> bool:
    from app.services.permission_service import user_can

    try:
        return any(
            user_can(user, mod, 'r')
            for mod in ('operario_fichaje', 'operario_calendario', 'operario_ausencias')
        )
    except Exception:
        return False
