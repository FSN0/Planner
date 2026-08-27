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
    ('registro_jornada', 'Registro de jornada', 'Jornada'),
    # Integraciones: hub + cada integración (permisos independientes entre sí)
    ('integraciones', 'Integraciones (hub)', 'Integraciones'),
    ('sync_odoo', 'Sincronización Odoo', 'Integraciones'),
    ('soltec_alta_odoo', 'Alta Odoo', 'Integraciones'),
    ('soltec_portal', 'Portal Soltec', 'Integraciones'),
    ('primeros_pasos', 'Primeros pasos', 'Sistema'),
    ('configuracion', 'Configuración', 'Sistema'),
    ('permisos', 'Permisos por rol', 'Sistema'),
    ('logs', 'Logs', 'Sistema'),
    # Portales operario
    ('operario_fichaje', 'Fichaje móvil (/mi)', 'Operario'),
    ('operario_calendario', 'Calendario propio', 'Operario'),
    ('operario_ausencias', 'Solicitar / ver ausencias', 'Operario'),
    ('operario_web', 'Portal web empleado', 'Operario'),
)

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
        'operario_web': frozenset('r'),
    },
}


def module_keys():
    return [m for m, _, _ in PERMISSION_MODULES]


def normalize_module(module: str) -> str:
    key = (module or '').strip()
    return LEGACY_MODULE_ALIASES.get(key, key)


def default_actions(role: str, module: str) -> frozenset:
    module = normalize_module(module)
    role_map = _DEFAULTS.get(role) or {}
    return frozenset(role_map.get(module, frozenset()))


def default_matrix_rows():
    """Lista de dicts listos para insertar en RolePermission."""
    rows = []
    for role, _label in PERMISSION_ROLES:
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
    'auditoria_vehiculos': 'Resolver auditoría de flota',
    'integraciones': 'Acciones del hub (si las hay)',
    'sync_odoo': 'Preview, sincronizar, guardar configuración',
    'soltec_alta_odoo': 'No necesario: con Lectura basta para abrir',
    'soltec_portal': 'No necesario: con Lectura basta para abrir',
    'logs': 'Marcar / gestionar avisos',
    'configuracion': 'Guardar ajustes del espacio',
    'permisos': 'Cambiar la matriz de permisos',
    'operario_fichaje': 'Fichar en la PWA',
    'operario_ausencias': 'Solicitar ausencias',
}

MODULE_READ_HINTS = {
    'integraciones': 'Ver el listado de integraciones',
    'sync_odoo': 'Entrar al centro de sincronización Odoo',
    'soltec_alta_odoo': 'Abrir el panel de altas Odoo',
    'soltec_portal': 'Abrir el portal Soltec',
}


def module_write_hint(module: str) -> str | None:
    return MODULE_WRITE_HINTS.get(normalize_module(module))


def module_read_hint(module: str) -> str | None:
    return MODULE_READ_HINTS.get(normalize_module(module))


# Compat imports antiguos
MODULE_EXECUTE_HINTS = {}


def module_execute_hint(module: str) -> str | None:
    return None
