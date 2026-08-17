"""Catálogo de módulos de la app (navegación + portales).

Cada módulo se configura por rol en RolePermission (R/W/X).
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
    ('integraciones', 'Integraciones', 'Sistema'),
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

# Defaults = comportamiento histórico de la app
# value: frozenset of 'r','w','x' or empty
_DEFAULTS = {
    ROLE_ADMIN: {m: frozenset('rwx') for m, _, _ in PERMISSION_MODULES},
    ROLE_JEFE: {
        'inicio': frozenset('r'),
        'tablero': frozenset('rwx'),
        'directorio': frozenset('r'),
        'planificador': frozenset('rwx'),
        'reuniones': frozenset('rwx'),
        'solicitudes': frozenset('rwx'),
        'ausencias': frozenset('rwx'),
        'vehiculos': frozenset('rwx'),
        'vehiculos_libres': frozenset('r'),
        'auditoria_fichajes': frozenset('rwx'),
        'integraciones': frozenset('r'),  # alta Odoo si el tenant lo tiene
    },
    ROLE_LABORAL: {
        'inicio': frozenset('r'),
        'ausencias': frozenset('rwx'),
        'auditoria_fichajes': frozenset('rwx'),
        'logs': frozenset('rwx'),
        'tablero': frozenset('r'),
        'auditoria_vehiculos': frozenset('r'),
        'vehiculos': frozenset('r'),
        'vehiculos_libres': frozenset('r'),
        'trabajadores': frozenset('r'),
    },
    ROLE_RRHH: {
        'inicio': frozenset('r'),
        'ausencias': frozenset('rwx'),
        'auditoria_fichajes': frozenset('rwx'),
        'logs': frozenset('rwx'),
        'tablero': frozenset('r'),
        'auditoria_vehiculos': frozenset('r'),
        'vehiculos': frozenset('r'),
        'vehiculos_libres': frozenset('r'),
        'trabajadores': frozenset('r'),
    },
    ROLE_OPERARIO: {
        'operario_fichaje': frozenset('rwx'),
        'operario_calendario': frozenset('r'),
        'operario_ausencias': frozenset('rwx'),
        # Portal web: el rol puede; cada ficha sigue necesitando web_access.
        # Si una empresa no quiere ningún operario en web, desmarca este módulo.
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
            rows.append({
                'role': role,
                'module': module,
                'can_read': 'r' in actions,
                'can_write': 'w' in actions,
                'can_execute': 'x' in actions,
            })
    return rows


# Módulos que el admin no puede quitarse a sí mismo (evitar auto-lockout)
ADMIN_LOCKED_MODULES = frozenset({'configuracion', 'permisos'})

# Dónde X tiene efecto real (el resto: X ≈ W o no aplica).
# Se muestra en la UI de permisos para no confundir.
MODULE_EXECUTE_HINTS = {
    'trabajadores': 'Reset contraseña / PIN',
    'reuniones': 'Eliminar notas',
    'solicitudes': 'Resolver / aprobar solicitudes',
    'ausencias': 'Aprobar / resolver conflictos',
    'auditoria_fichajes': 'Resolver incidencias de fichaje',
    'auditoria_vehiculos': 'Resolver auditoría de flota',
}

MODULE_WRITE_HINTS = {
    'planificador': 'Mover y asignar en el Gantt',
    'tablero': 'Arrastrar en kanban / editar calendario de obra',
    'reuniones': 'Crear y editar notas',
    'trabajadores': 'Alta / editar fichas',
    'vehiculos': 'Asignar y editar flota',
    'directorio': 'Crear / editar obras',
    'subcontratas': 'Crear / editar empresas',
    'solicitudes': 'Crear solicitudes',
    'ausencias': 'Crear / gestionar ausencias',
}


def module_execute_hint(module: str) -> str | None:
    return MODULE_EXECUTE_HINTS.get(normalize_module(module))


def module_write_hint(module: str) -> str | None:
    return MODULE_WRITE_HINTS.get(normalize_module(module))
