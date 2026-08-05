"""ACL helpers for ROLE_LABORAL / ROLE_RRHH (and shared admin checks)."""
from __future__ import annotations

from app.models import ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH, ROLES_LABORAL_LIKE
from app.services.config_service import get_tenant_config
from app.services.log_notification_service import LABORAL_LOG_CATEGORIES

# Modules → allowed actions for laboral/rrhh (r/w/x). Admin bypasses via user_can.
LABORAL_ACL = {
    'ausencias': frozenset('rwx'),
    'auditoria_fichajes': frozenset('rwx'),  # resolve gated by config; sections limited
    'logs': frozenset('rwx'),               # categories limited to LABORAL_LOG_CATEGORIES
    'tablero': frozenset('r'),
    'auditoria_vehiculos': frozenset('r'),
    'vehiculos': frozenset('r'),
    'vehiculos_libres': frozenset('r'),
    'vehicle_panel': frozenset('r'),
    'worker_panel': frozenset('r'),
    'obra_panel': frozenset('r'),
}

LABORAL_AUDITORIA_SECTIONS = frozenset({
    'ausencias',
    'modificacion_odoo',
    'historico_global',
})

CONFIG_LABORAL_RESOLVER = 'laboral_puede_resolver_fichajes'


def is_admin(user) -> bool:
    return bool(user and getattr(user, 'is_authenticated', False) and user.role == ROLE_ADMIN)


def is_laboral(user) -> bool:
    """Laboral y RRHH comparten ACL hasta que RRHH tenga permisos propios."""
    return bool(
        user
        and getattr(user, 'is_authenticated', False)
        and getattr(user, 'role', None) in ROLES_LABORAL_LIKE
    )


def expand_laboral_roles(*roles):
    """Si el conjunto incluye laboral, añade RRHH."""
    allowed = tuple(roles)
    if ROLE_LABORAL in allowed and ROLE_RRHH not in allowed:
        return allowed + (ROLE_RRHH,)
    return allowed


def laboral_puede_resolver_fichajes() -> bool:
    """ConfiguracionGlobal toggle; default False."""
    val = get_tenant_config(CONFIG_LABORAL_RESOLVER, default='False')
    return str(val).strip().lower() in ('true', '1', 'yes', 'on')


def laboral_auditoria_sections(user) -> set:
    """Sections of auditoría fichajes visible to the user."""
    if is_admin(user):
        return {
            'conflictos',
            'paracaidistas',
            'ausencias',
            'modificacion_odoo',
            'historico_global',
        }
    if is_laboral(user):
        return set(LABORAL_AUDITORIA_SECTIONS)
    # jefe sees all pending sections (existing behaviour)
    return {
        'conflictos',
        'paracaidistas',
        'ausencias',
        'modificacion_odoo',
        'historico_global',
    }


def laboral_log_categories(user) -> list:
    """Allowed SystemLog categories for the logs page."""
    if is_laboral(user):
        return list(LABORAL_LOG_CATEGORIES)
    return [
        'accesos', 'valoraciones', 'planificacion', 'obras', 'fichajes',
        'solicitud', 'persona_obra',
    ]


def user_can(user, module: str, action: str) -> bool:
    """
    Check module permission. action in 'r','w','x'.
    Admin: always True. Laboral/RRHH: LABORAL_ACL. Others: False for these modules
    (callers still use roles_required for jefe/admin routes).
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    action = (action or '').lower()[:1]
    if action not in ('r', 'w', 'x'):
        return False
    if is_admin(user):
        return True
    if not is_laboral(user):
        return False
    allowed = LABORAL_ACL.get(module)
    if not allowed:
        return False
    if module == 'auditoria_fichajes' and action == 'x':
        return laboral_puede_resolver_fichajes()
    return action in allowed


def can_resolve_fichajes(user) -> bool:
    if is_admin(user):
        return True
    if is_laboral(user):
        return laboral_puede_resolver_fichajes()
    # jefe: existing route logic allows resolve (scoped)
    return getattr(user, 'role', None) == 'jefe_obra'
