"""Catálogo de módulos de la app (navegación + portales).

Capas:
- L/E en paneles reales (entrar / mutar catálogo o cola)
- Ticks binarios (capacidad: planificar gente/flota, editar pasado)
- Alcances de obras (planificación / auditoría fichajes / solicitudes) → panel_scope_service
- Modos directo|solicitud → assign_mode_service
"""
from __future__ import annotations

from app.models import (
    ROLE_ADMIN,
    ROLE_ADMIN_SUBCONTRATA,
    ROLE_JEFE,
    ROLE_LABORAL,
    ROLE_OPERARIO,
    ROLE_RRHH,
)

# (module_key, label, group)
PERMISSION_MODULES = (
    ('inicio', 'Inicio / panel', 'General'),
    ('tablero', 'Tablero de obras', 'Planificación'),
    ('directorio', 'Obras', 'Planificación'),
    ('planificador', 'Planificador', 'Planificación'),
    ('asignaciones', 'Planificar gente', 'Planificación'),
    ('planificar_flota', 'Planificar flota', 'Planificación'),
    ('cuadrante_pasado', 'Editar cuadrante en pasado', 'Planificación'),
    ('reuniones', 'Reuniones / notas', 'Planificación'),
    ('trabajadores', 'Trabajadores (fichas y calendarios)', 'Personal'),
    ('valoraciones', 'Valoraciones', 'Personal'),
    ('subcontratas', 'Subcontratas', 'Personal'),
    ('solicitudes', 'Solicitudes de personal', 'Personal'),
    ('solicitudes_vehiculos', 'Solicitudes de flota', 'Personal'),
    ('ausencias', 'Ausencias', 'Personal'),
    ('vehiculos', 'Flota (catálogo)', 'Vehículos'),
    ('vehiculos_libres', 'Coches libres', 'Vehículos'),
    ('auditoria_vehiculos', 'Auditoría vehículos', 'Vehículos'),
    ('auditoria_fichajes', 'Auditoría fichajes', 'Jornada'),
    ('mapa_fichajes', 'Mapa de fichajes', 'Jornada'),
    ('registro_jornada', 'Registro de jornada', 'Jornada'),
    ('operario_fichaje', 'Fichar (portal propio)', 'Portal propio'),
    ('operario_calendario', 'Mi calendario (portal propio)', 'Portal propio'),
    ('operario_ausencias', 'Mis ausencias (portal propio)', 'Portal propio'),
    ('integraciones', 'Integraciones (hub)', 'Integraciones'),
    ('sync_odoo', 'Sincronización Odoo', 'Integraciones'),
    ('soltec_alta_odoo', 'Alta Odoo', 'Integraciones'),
    ('soltec_alta_odoo_admin', 'Alta Odoo · entrar como admin', 'Integraciones'),
    ('soltec_portal', 'Portal Soltec', 'Integraciones'),
    ('primeros_pasos', 'Primeros pasos', 'Sistema'),
    ('etiquetas', 'Etiquetas (ver / asignar)', 'Sistema'),
    ('etiquetas_catalogo', 'Etiquetas · catálogo', 'Sistema'),
    ('configuracion', 'Configuración', 'Sistema'),
    ('permisos', 'Permisos por rol', 'Sistema'),
    ('logs', 'Logs', 'Sistema'),
    ('documentacion', 'Documentación', 'Personal'),
    ('certificacion', 'Certificación de horario', 'Personal'),
    ('contratacion', 'Contratación', 'Personal'),
)

PORTAL_JORNADA_MODULES = frozenset({
    'operario_fichaje',
    'operario_calendario',
    'operario_ausencias',
})

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
    (ROLE_ADMIN_SUBCONTRATA, 'Admin subcontrata'),
)

# Ticks: un solo checkbox en UI (activado = r+w en BD)
BINARY_TICK_MODULES = frozenset({
    'asignaciones',
    'planificar_flota',
    'cuadrante_pasado',
    'soltec_alta_odoo_admin',
})

# Solo lectura en UI (entrar a pantalla; la acción cuelga de otro módulo)
WRITE_DISABLED_MODULES = frozenset({
    'inicio',
    'tablero',
    'planificador',
    'mapa_fichajes',
    'vehiculos_libres',
    'registro_jornada',
})

SSO_READ_ONLY_MODULES = frozenset({'soltec_alta_odoo', 'soltec_portal'})

ADMIN_LOCKED_MODULES = frozenset({'configuracion', 'permisos'})

# Defaults históricos adaptados al modelo nuevo
# Admin: casi todo, excepto portal propio (fichaje/calendario/ausencias del operario).
_DEFAULTS = {
    ROLE_ADMIN: {
        m: frozenset('rw')
        for m, _, _ in PERMISSION_MODULES
        if m not in PORTAL_JORNADA_MODULES
    },
    ROLE_JEFE: {
        'inicio': frozenset('r'),
        'tablero': frozenset('r'),
        'directorio': frozenset('r'),
        'planificador': frozenset('r'),
        'trabajadores': frozenset('r'),
        'asignaciones': frozenset('rw'),       # tick planificar gente
        'planificar_flota': frozenset('rw'),  # tick planificar coches
        'reuniones': frozenset('rw'),
        # Crea vía planificar; no resuelve el buzón de oficina
        'solicitudes': frozenset('r'),
        'solicitudes_vehiculos': frozenset('r'),
        'ausencias': frozenset('rw'),
        'valoraciones': frozenset('rw'),
        'vehiculos': frozenset('r'),          # ver catálogo; asignar = planificar_flota
        'vehiculos_libres': frozenset('r'),
        'subcontratas': frozenset('r'),       # ficha empresa (company_panel)
        'auditoria_fichajes': frozenset('rw'),
        'soltec_alta_odoo': frozenset('r'),
        'soltec_portal': frozenset('r'),
        'etiquetas': frozenset('r'),
        'documentacion': frozenset('r'),
        'certificacion': frozenset('rw'),
    },
    ROLE_LABORAL: {
        'inicio': frozenset('r'),
        'ausencias': frozenset('rw'),
        'auditoria_fichajes': frozenset('rw'),
        'mapa_fichajes': frozenset('r'),
        'registro_jornada': frozenset('r'),
        'logs': frozenset('rw'),
        'tablero': frozenset('r'),
        'planificador': frozenset('r'),
        'solicitudes': frozenset('rw'),
        'solicitudes_vehiculos': frozenset('rw'),
        'auditoria_vehiculos': frozenset('r'),
        'vehiculos': frozenset('r'),
        'vehiculos_libres': frozenset('r'),
        'trabajadores': frozenset('r'),
        'valoraciones': frozenset('r'),
        'directorio': frozenset('r'),
        'etiquetas': frozenset('r'),
        'documentacion': frozenset('rw'),
        'certificacion': frozenset('rw'),
        'contratacion': frozenset('rw'),
    },
    ROLE_RRHH: {
        'inicio': frozenset('r'),
        'ausencias': frozenset('rw'),
        'auditoria_fichajes': frozenset('rw'),
        'mapa_fichajes': frozenset('r'),
        'registro_jornada': frozenset('r'),
        'logs': frozenset('rw'),
        'tablero': frozenset('r'),
        'planificador': frozenset('r'),
        'solicitudes': frozenset('rw'),
        'solicitudes_vehiculos': frozenset('rw'),
        'auditoria_vehiculos': frozenset('r'),
        'vehiculos': frozenset('r'),
        'vehiculos_libres': frozenset('r'),
        'trabajadores': frozenset('r'),
        'valoraciones': frozenset('r'),
        'directorio': frozenset('r'),
        'etiquetas': frozenset('r'),
        'documentacion': frozenset('rw'),
        'certificacion': frozenset('rw'),
        'contratacion': frozenset('rw'),
    },
    ROLE_OPERARIO: {
        'operario_fichaje': frozenset('rw'),
        'operario_calendario': frozenset('r'),
        'operario_ausencias': frozenset('rw'),
        'etiquetas': frozenset('r'),
        'documentacion': frozenset('rw'),
    },
    ROLE_ADMIN_SUBCONTRATA: {
        'documentacion': frozenset('rw'),
        'certificacion': frozenset('rw'),
        'operario_fichaje': frozenset('rw'),
        'operario_calendario': frozenset('r'),
    },
}


def module_keys():
    return [m for m, _, _ in PERMISSION_MODULES]


def _tenant_modulos(tenant=None):
    from app.services.tenant_modules import current_tenant, get_modulos_activos

    return get_modulos_activos(tenant if tenant is not None else current_tenant())


def _permission_row_enabled(module: str, tenant=None) -> bool:
    from app.services.tenant_modules import (
        has_auditoria_vehiculos,
        has_notas,
        has_valoraciones,
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
    if module == 'valoraciones':
        return has_valoraciones(tenant)
    if module == 'auditoria_vehiculos':
        return has_auditoria_vehiculos(tenant)
    if module == 'sync_odoo':
        return has_odoo
    if module == 'soltec_alta_odoo':
        return has_odoo_alta
    if module == 'soltec_alta_odoo_admin':
        return has_odoo_alta
    if module == 'soltec_portal':
        return is_soltec_tenant(tenant) and has_odoo
    if module == 'integraciones':
        return has_odoo or has_odoo_alta
    if module == 'primeros_pasos':
        return has_onboarding
    if module == 'operario_fichaje':
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
    if module == 'documentacion':
        from app.services.tenant_modules import has_documentacion
        return has_documentacion(tenant)
    if module == 'certificacion':
        from app.services.tenant_modules import has_certificacion
        return has_certificacion(tenant)
    if module == 'contratacion':
        from app.services.tenant_modules import has_contratacion
        return has_contratacion(tenant)
    return True


def visible_permission_modules(tenant=None):
    return tuple(
        row for row in PERMISSION_MODULES
        if _permission_row_enabled(row[0], tenant)
    )


def modules_for_role(role: str, tenant=None):
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
        role_map = _DEFAULTS.get(ROLE_LABORAL) or {}
    return frozenset(role_map.get(module, frozenset()))


def default_matrix_rows():
    rows = []
    try:
        from app.services.role_registry_service import list_roles
        roles = list_roles()
    except Exception:
        roles = list(PERMISSION_ROLES)
    for role, _label in roles:
        for module, _mlabel, _group in PERMISSION_MODULES:
            actions = default_actions(role, module)
            can_r = 'r' in actions
            can_w = 'w' in actions
            if module in WRITE_DISABLED_MODULES or module in SSO_READ_ONLY_MODULES:
                can_w = False
            if module in BINARY_TICK_MODULES:
                # Tick on → r+w; off → neither
                on = can_w or can_r
                can_r = can_w = on
            rows.append({
                'role': role,
                'module': module,
                'can_read': can_r,
                'can_write': can_w,
                'can_execute': can_w,
            })
    return rows


MODULE_WRITE_HINTS = {
    'planificador': 'Solo ver el Gantt. Mover gente: tick «Planificar gente»',
    'tablero': 'Solo ver el kanban. Mover gente: tick «Planificar gente»',
    'asignaciones': 'Mover gente en Gantt, kanban y calendarios',
    'planificar_flota': 'Asignar / desasignar coches en el cuadrante',
    'cuadrante_pasado': 'Forzar cambios en días pasados o validados',
    'reuniones': 'Crear, editar y eliminar notas',
    'trabajadores': 'Alta / editar fichas; reset contraseña y PIN',
    'valoraciones': 'Puntuar operarios; editar o resetear valoraciones',
    'vehiculos': 'Crear / editar vehículos del catálogo',
    'directorio': 'Crear / editar obras',
    'subcontratas': 'Crear / editar empresas',
    'solicitudes': 'Resolver solicitudes de personal (crear = planificar en modo solicitud)',
    'solicitudes_vehiculos': 'Resolver solicitudes de flota',
    'ausencias': 'Crear / aprobar ausencias y conflictos',
    'auditoria_fichajes': 'Resolver incidencias y sincronizar',
    'mapa_fichajes': 'Solo consulta',
    'auditoria_vehiculos': 'Resolver auditoría de flota',
    'integraciones': 'Acciones del hub',
    'sync_odoo': 'Preview, sincronizar, guardar configuración',
    'soltec_alta_odoo': 'Con Lectura basta para abrir',
    'soltec_alta_odoo_admin': 'Ver todos los contratos (como admin de Altas)',
    'soltec_portal': 'Con Lectura basta para abrir',
    'etiquetas': 'Asignar etiquetas en fichas de personal y subcontratas',
    'etiquetas_catalogo': 'Crear, renombrar, absorber y borrar etiquetas',
    'logs': 'Marcar / gestionar avisos',
    'configuracion': 'Guardar ajustes del espacio',
    'permisos': 'Cambiar la matriz de permisos',
    'operario_fichaje': 'Fichar entrada, pausas y salida',
    'operario_calendario': 'Ver asignaciones propias en /fichaje',
    'operario_ausencias': 'Solicitar y consultar ausencias propias',
    'documentacion': 'Validar, rechazar y definir qué documentos se piden',
    'certificacion': 'Editar horas/precios y enviar, aceptar o rechazar la certificación',
    'contratacion': 'Crear altas y validar la documentación de contratación',
}

MODULE_READ_HINTS = {
    'asignaciones': 'Capacidad de planificar gente (tick)',
    'planificar_flota': 'Capacidad de asignar coches (tick)',
    'tablero': 'Ver el kanban de obras',
    'planificador': 'Ver el Gantt',
    'cuadrante_pasado': 'Permitir tocar el plan en pasado',
    'trabajadores': 'Ver fichas y calendarios de personal',
    'valoraciones': 'Ver puntuaciones e historial de valoraciones',
    'vehiculos': 'Ver el catálogo y calendarios de flota',
    'solicitudes': 'Ver el buzón de personal (resolver = escritura)',
    'solicitudes_vehiculos': 'Ver el buzón de flota (resolver = escritura)',
    'auditoria_fichajes': 'Ver secciones; el alcance filtra filas',
    'integraciones': 'Ver el listado de integraciones',
    'sync_odoo': 'Entrar al centro de sincronización Odoo',
    'soltec_alta_odoo': 'Abrir el panel de altas Odoo',
    'soltec_alta_odoo_admin': 'Entrar a Altas con visión completa (todos los contratos)',
    'soltec_portal': 'Abrir el portal Soltec',
    'etiquetas': 'Ver y filtrar por etiquetas',
    'etiquetas_catalogo': 'Gestionar el catálogo en Ajustes',
    'operario_fichaje': 'Acceso a /fichaje para fichar',
    'operario_calendario': 'Ver el calendario propio en /fichaje',
    'operario_ausencias': 'Ver y pedir ausencias propias en /fichaje',
    'documentacion': 'Ver el estado de la documentación',
    'certificacion': 'Entrar al panel; el alcance filtra obras y empresas',
    'contratacion': 'Seguir las altas que aún no están activas',
}


def module_write_hint(module: str) -> str | None:
    return MODULE_WRITE_HINTS.get(normalize_module(module))


def module_read_hint(module: str) -> str | None:
    return MODULE_READ_HINTS.get(normalize_module(module))


MODULE_EXECUTE_HINTS = {}


def module_execute_hint(module: str) -> str | None:
    return None
