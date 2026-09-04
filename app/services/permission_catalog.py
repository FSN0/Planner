"""Catálogo de módulos de la app (navegación + portales).

Cada módulo se configura por rol en RolePermission (Lectura / Escritura).
La antigua X (ejecutar) se unifica con Escritura.
"""
from __future__ import annotations

from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_OPERARIO, ROLE_RRHH

# (module_key, label, group)
PERMISSION_MODULES = (
    ('inicio', 'Inicio / panel', 'General'),
    ('tablero', 'Tablero de obras', 'Planificación'),
    ('directorio', 'Obras', 'Planificación'),
    ('planificador', 'Planificador', 'Planificación'),
    ('reuniones', 'Reuniones / notas', 'Planificación'),
    ('trabajadores', 'Trabajadores', 'Personal'),
    ('subcontratas', 'Subcontratas', 'Personal'),
    ('solicitudes', 'Solicitudes', 'Personal'),
    ('ausencias', 'Ausencias', 'Personal'),
    ('vehiculos', 'Flota', 'Vehículos'),
    ('vehiculos_libres', 'Coches libres', 'Vehículos'),
    ('auditoria_vehiculos', 'Auditoría vehículos', 'Vehículos'),
    ('auditoria_fichajes', 'Auditoría fichajes', 'Jornada'),
    ('mapa_fichajes', 'Mapa de fichajes', 'Jornada'),
    ('registro_jornada', 'Registro de jornada', 'Jornada'),
    # Portal propio (/fichaje): cualquier rol puede tenerlos (p. ej. jefe con su calendario)
    ('operario_fichaje', 'Fichar (portal propio)', 'Portal propio'),
    ('operario_calendario', 'Mi calendario (portal propio)', 'Portal propio'),
    ('operario_ausencias', 'Mis ausencias (portal propio)', 'Portal propio'),
    # Integraciones: hub + cada integración (permisos independientes entre sí)
    ('integraciones', 'Integraciones (hub)', 'Integraciones'),
    ('sync_odoo', 'Sincronización Odoo', 'Integraciones'),
    ('soltec_alta_odoo', 'Alta Odoo', 'Integraciones'),
    ('soltec_portal', 'Portal Soltec', 'Integraciones'),
    ('primeros_pasos', 'Primeros pasos', 'Sistema'),
    ('configuracion', 'Configuración', 'Sistema'),
    ('permisos', 'Permisos por rol', 'Sistema'),
    ('logs', 'Logs', 'Sistema'),
)

# Módulos del portal /fichaje (autogestión). Solo se configuran en el rol Operario.
PORTAL_JORNADA_MODULES = frozenset({
    'operario_fichaje',
    'operario_calendario',
    'operario_ausencias',
})

# Compat: paneles detalle usados en código legado
LEGACY_MODULE_ALIASES = {
    'vehicle_panel': 'vehiculos',
    'worker_panel': 'trabajadores',
    'obra_panel': 'tablero',
}

PERMISSION_ROLES = (
    (ROLE_ADMIN, 'Administrador'),
    (ROLE_JEFE, 'Jefe de obra'),
    (ROLE_LABORAL, 'Laboral'),
    (ROLE_RRHH, 'RRHH'),
    (ROLE_OPERARIO, 'Operario'),
)

# Defaults = comportamiento histórico. Solo r/w (x ≡ w).
_DEFAULTS = {
    ROLE_ADMIN: {m: frozenset('rw') for m, _, _ in PERMISSION_MODULES},
    ROLE_JEFE: {
        'inicio': frozenset('r'),
        'tablero': frozenset('rw'),
        'directorio': frozenset('r'),
        'planificador': frozenset('rw'),
        'reuniones': frozenset('rw'),
        'solicitudes': frozenset('rw'),
        'ausencias': frozenset('rw'),
        'vehiculos': frozenset('rw'),
        'vehiculos_libres': frozenset('r'),
        'auditoria_fichajes': frozenset('rw'),
        # Atajos SSO (no requieren hub Integraciones)
        'soltec_alta_odoo': frozenset('r'),
        'soltec_portal': frozenset('r'),
    },
    ROLE_LABORAL: {
        'inicio': frozenset('r'),
        'ausencias': frozenset('rw'),
        'auditoria_fichajes': frozenset('rw'),
        'logs': frozenset('rw'),
        'tablero': frozenset('r'),
        'auditoria_vehiculos': frozenset('r'),
        'vehiculos': frozenset('r'),
        'vehiculos_libres': frozenset('r'),
        'trabajadores': frozenset('r'),
    },
    ROLE_RRHH: {
        'inicio': frozenset('r'),
        'ausencias': frozenset('rw'),
        'auditoria_fichajes': frozenset('rw'),
        'logs': frozenset('rw'),
        'tablero': frozenset('r'),
        'auditoria_vehiculos': frozenset('r'),
        'vehiculos': frozenset('r'),
        'vehiculos_libres': frozenset('r'),
        'trabajadores': frozenset('r'),
    },
    ROLE_OPERARIO: {
        'operario_fichaje': frozenset('rw'),
        'operario_calendario': frozenset('r'),
        'operario_ausencias': frozenset('rw'),
    },
}


def module_keys():
    return [m for m, _, _ in PERMISSION_MODULES]


def _tenant_modulos(tenant=None):
    from app.services.tenant_modules import current_tenant, get_modulos_activos

    return get_modulos_activos(tenant if tenant is not None else current_tenant())


def _permission_row_enabled(module: str, tenant=None) -> bool:
    """
    False si el extra no está en este espacio: no se enseña ni se pisa al guardar.

    Lo genérico (tablero, gente, flota…) va siempre. Lo a medida (Odoo, Portal
    Soltec, notas, auditoría de km…) solo si el módulo está activo.
    """
    from app.services.tenant_modules import (
        has_auditoria_vehiculos,
        has_notas,
        is_soltec_tenant,
    )

    mods = _tenant_modulos(tenant)
    has_odoo = bool(mods.get('odoo'))
    has_odoo_alta = bool(mods.get('odoo_alta'))
    has_fichaje = bool(mods.get('fichaje_operario'))
    has_onboarding = bool(mods.get('onboarding'))
    has_registro = True if 'registro_jornada' not in mods else bool(mods.get('registro_jornada'))

    if module == 'reuniones':
        return has_notas(tenant)
    if module == 'auditoria_vehiculos':
        return has_auditoria_vehiculos(tenant)
    if module == 'sync_odoo':
        return has_odoo
    if module == 'soltec_alta_odoo':
        return has_odoo_alta
    if module == 'soltec_portal':
        return is_soltec_tenant(tenant) and has_odoo
    if module == 'integraciones':
        return has_odoo or has_odoo_alta
    if module == 'primeros_pasos':
        return has_onboarding
    if module == 'operario_fichaje':
        # Reloj de fichaje: solo si el espacio tiene el módulo.
        return has_fichaje
    if module == 'operario_calendario':
        return True
    if module == 'operario_ausencias':
        from app.services.tenant_modules import has_portal_ausencias
        return has_portal_ausencias(tenant)
    if module == 'auditoria_fichajes':
        return has_fichaje or has_odoo
    if module == 'mapa_fichajes':
        return has_fichaje
    if module == 'registro_jornada':
        return has_registro
    return True


def visible_permission_modules(tenant=None):
    """Filas de la matriz que este tenant puede ver y editar."""
    return tuple(
        row for row in PERMISSION_MODULES
        if _permission_row_enabled(row[0], tenant)
    )


def modules_for_role(role: str, tenant=None):
    """
    Misma lista de módulos para todos los roles: el admin decide qué marcar.
    Incluye el portal propio (calendario / ausencias / fichar) para poder
    dárselo también a un jefe u otro perfil de oficina.
    """
    return visible_permission_modules(tenant)


def visible_permission_keys(tenant=None):
    return [m for m, _, _ in visible_permission_modules(tenant)]


def normalize_module(module: str) -> str:
    key = (module or '').strip()
    return LEGACY_MODULE_ALIASES.get(key, key)


def default_actions(role: str, module: str) -> frozenset:
    module = normalize_module(module)
    role_map = _DEFAULTS.get(role)
    if role_map is None:
        # Roles custom: plantilla laboral (oficina)
        role_map = _DEFAULTS.get(ROLE_LABORAL) or {}
    return frozenset(role_map.get(module, frozenset()))


def default_matrix_rows():
    """Lista de dicts listos para insertar en RolePermission."""
    rows = []
    try:
        from app.services.role_registry_service import list_roles
        roles = list_roles()
    except Exception:
        roles = list(PERMISSION_ROLES)
    for role, _label in roles:
        for module, _mlabel, _group in PERMISSION_MODULES:
            actions = default_actions(role, module)
            can_w = 'w' in actions
            rows.append({
                'role': role,
                'module': module,
                'can_read': 'r' in actions,
                'can_write': can_w,
                # Columna legada: se mantiene alineada con escritura
                'can_execute': can_w,
            })
    return rows


ADMIN_LOCKED_MODULES = frozenset({'configuracion', 'permisos'})

# Módulos SSO: la escritura no aporta (abrir el enlace = lectura)
SSO_READ_ONLY_MODULES = frozenset({'soltec_alta_odoo', 'soltec_portal'})

MODULE_WRITE_HINTS = {
    'planificador': 'Mover y asignar en el Gantt',
    'tablero': 'Arrastrar en kanban / editar calendario de obra',
    'reuniones': 'Crear, editar y eliminar notas',
    'trabajadores': 'Alta / editar fichas; reset contraseña y PIN',
    'vehiculos': 'Asignar y editar flota',
    'directorio': 'Crear / editar obras',
    'subcontratas': 'Crear / editar empresas',
    'solicitudes': 'Crear y resolver solicitudes',
    'ausencias': 'Crear / aprobar ausencias y conflictos',
    'auditoria_fichajes': 'Resolver incidencias y sincronizar',
    'mapa_fichajes': 'Solo consulta: no requiere escritura',
    'auditoria_vehiculos': 'Resolver auditoría de flota',
    'integraciones': 'Acciones del hub (si las hay)',
    'sync_odoo': 'Preview, sincronizar, guardar configuración',
    'soltec_alta_odoo': 'No necesario: con Lectura basta para abrir',
    'soltec_portal': 'No necesario: con Lectura basta para abrir',
    'logs': 'Marcar / gestionar avisos',
    'configuracion': 'Guardar ajustes del espacio',
    'permisos': 'Cambiar la matriz de permisos',
    'operario_fichaje': 'Fichar entrada, pausas y salida',
    'operario_calendario': 'Ver asignaciones propias en /fichaje',
    'operario_ausencias': 'Solicitar y consultar ausencias propias',
}

MODULE_READ_HINTS = {
    'integraciones': 'Ver el listado de integraciones',
    'sync_odoo': 'Entrar al centro de sincronización Odoo',
    'soltec_alta_odoo': 'Abrir el panel de altas Odoo',
    'soltec_portal': 'Abrir el portal Soltec',
    'operario_fichaje': 'Acceso a /fichaje para fichar (requiere módulo de fichaje)',
    'operario_calendario': 'Ver el calendario propio (asignaciones) en /fichaje',
    'operario_ausencias': 'Ver y pedir ausencias propias en /fichaje (si el espacio no las gestiona en el ERP)',
}


def module_write_hint(module: str) -> str | None:
    return MODULE_WRITE_HINTS.get(normalize_module(module))


def module_read_hint(module: str) -> str | None:
    return MODULE_READ_HINTS.get(normalize_module(module))


# Compat imports antiguos
MODULE_EXECUTE_HINTS = {}


def module_execute_hint(module: str) -> str | None:
    return None
