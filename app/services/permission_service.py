"""Permisos por rol (matriz tenant) + helpers legacy."""
from __future__ import annotations

from flask import g, has_request_context

from app import db
from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH, ROLES_LABORAL_LIKE, RolePermission
from app.services.config_service import get_tenant_config
from app.services.log_notification_service import LABORAL_LOG_CATEGORIES
from app.services.permission_catalog import (
    ADMIN_LOCKED_MODULES,
    default_actions,
    default_matrix_rows,
    module_keys,
    normalize_module,
)

# Legacy export (tests / imports)
LABORAL_ACL = {
    'ausencias': frozenset('rwx'),
    'auditoria_fichajes': frozenset('rwx'),
    'logs': frozenset('rwx'),
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

_CACHE_ATTR = '_role_perm_cache'
_TABLE_READY_ATTR = '_role_perm_table_ready'


def is_admin(user) -> bool:
    return bool(user and getattr(user, 'is_authenticated', False) and user.role == ROLE_ADMIN)


def is_laboral(user) -> bool:
    return bool(
        user
        and getattr(user, 'is_authenticated', False)
        and getattr(user, 'role', None) in ROLES_LABORAL_LIKE
    )


def expand_laboral_roles(*roles):
    allowed = tuple(roles)
    if ROLE_LABORAL in allowed and ROLE_RRHH not in allowed:
        return allowed + (ROLE_RRHH,)
    return allowed


def laboral_puede_resolver_fichajes() -> bool:
    val = get_tenant_config(CONFIG_LABORAL_RESOLVER, default='False')
    return str(val).strip().lower() in ('true', '1', 'yes', 'on')


def laboral_auditoria_sections(user) -> set:
    if is_admin(user):
        return {
            'conflictos', 'paracaidistas', 'ausencias',
            'modificacion_odoo', 'historico_global',
        }
    if is_laboral(user):
        return set(LABORAL_AUDITORIA_SECTIONS)
    return {
        'conflictos', 'paracaidistas', 'ausencias',
        'modificacion_odoo', 'historico_global',
    }


def laboral_log_categories(user) -> list:
    if is_laboral(user):
        return list(LABORAL_LOG_CATEGORIES)
    cats = [
        'accesos', 'valoraciones', 'planificacion', 'obras', 'fichajes',
        'solicitud', 'persona_obra',
    ]
    from app.services.tenant_modules import has_valoraciones
    if not has_valoraciones():
        cats = [c for c in cats if c != 'valoraciones']
    return cats


def _checkbox_on(form_data, key: str) -> bool:
    """Checkbox HTML: presente con valor on/true/1/yes."""
    if form_data is None:
        return False
    raw = form_data.get(key)
    if raw is None:
        return False
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if raw is True:
        return True
    if raw is False or raw is None:
        return False
    return str(raw).strip().lower() in ('on', 'true', '1', 'yes', 'y', 'checked')


def _clear_inspector_cache():
    try:
        bind = db.session.get_bind()
        if bind is None:
            return
        from sqlalchemy import inspect as sa_inspect
        insp = sa_inspect(bind)
        clear = getattr(insp, 'clear_cache', None)
        if callable(clear):
            clear()
    except Exception:
        pass


def _table_ready(force_refresh: bool = False) -> bool:
    """
    True si role_permissions existe en el search_path actual (esquema tenant).

    Usa to_regclass (respeta search_path) y evita el inspector cacheado de SQLAlchemy,
    que puede decir que no hay tabla justo después de crearla/migrar.
    """
    if has_request_context() and not force_refresh and hasattr(g, _TABLE_READY_ATTR):
        return bool(getattr(g, _TABLE_READY_ATTR))

    ready = False
    try:
        reg = db.session.execute(db.text("SELECT to_regclass('role_permissions')")).scalar()
        ready = reg is not None
        if not ready:
            row = db.session.execute(db.text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'role_permissions'
                LIMIT 1
                """
            )).scalar()
            ready = row is not None
    except Exception:
        ready = False

    if has_request_context():
        setattr(g, _TABLE_READY_ATTR, ready)
    return ready


def _ensure_table() -> bool:
    """Crea role_permissions en el esquema actual si falta (tenants sin migrar)."""
    if _table_ready():
        return True
    try:
        schema = db.session.execute(db.text('SELECT current_schema()')).scalar()
        if not schema or schema == 'public':
            return False
        # Validación mínima del identificador de esquema (tenant_*)
        import re
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', schema):
            return False

        # CREATE en el esquema del tenant (no depender del search_path del pool)
        db.session.execute(db.text(f'''
            CREATE TABLE IF NOT EXISTS {schema}.role_permissions (
                id SERIAL PRIMARY KEY,
                role VARCHAR(30) NOT NULL,
                module VARCHAR(50) NOT NULL,
                can_read BOOLEAN NOT NULL DEFAULT FALSE,
                can_write BOOLEAN NOT NULL DEFAULT FALSE,
                can_execute BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT uq_role_permissions_role_module UNIQUE (role, module)
            )
        '''))
        db.session.execute(db.text(
            f'CREATE INDEX IF NOT EXISTS ix_role_permissions_role '
            f'ON {schema}.role_permissions (role)'
        ))
        db.session.execute(db.text(
            f'CREATE INDEX IF NOT EXISTS ix_role_permissions_module '
            f'ON {schema}.role_permissions (module)'
        ))
        db.session.commit()
        _clear_inspector_cache()
        if has_request_context() and hasattr(g, _TABLE_READY_ATTR):
            delattr(g, _TABLE_READY_ATTR)
        return _table_ready(force_refresh=True)
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


def ensure_role_permissions(force: bool = False) -> int:
    """Si no hay filas (o force), siembra defaults. Devuelve filas creadas/actualizadas."""
    if not _ensure_table():
        return 0
    existing = RolePermission.query.count()
    if existing and not force:
        return 0
    if force:
        RolePermission.query.delete()
        db.session.flush()
    created = 0
    for row in default_matrix_rows():
        db.session.add(RolePermission(**row))
        created += 1
    db.session.commit()
    _clear_perm_cache()
    return created


def _clear_perm_cache():
    if has_request_context() and hasattr(g, _CACHE_ATTR):
        delattr(g, _CACHE_ATTR)


def _load_matrix() -> dict:
    """role -> module -> frozenset(actions). Cache por request."""
    if has_request_context() and hasattr(g, _CACHE_ATTR):
        return getattr(g, _CACHE_ATTR)

    matrix: dict = {}
    if _ensure_table():
        rows = RolePermission.query.all()
        if not rows:
            ensure_role_permissions()
            rows = RolePermission.query.all()
        for row in rows:
            actions = set()
            if row.can_read:
                actions.add('r')
            if row.can_write:
                actions.add('w')
            if row.can_execute:
                actions.add('x')
            matrix.setdefault(row.role, {})[row.module] = frozenset(actions)

    if has_request_context():
        setattr(g, _CACHE_ATTR, matrix)
    return matrix


def _actions_for(role: str, module: str) -> frozenset:
    module = normalize_module(module)
    matrix = _load_matrix()
    if role in matrix and module in matrix[role]:
        return matrix[role][module]
    return default_actions(role, module)


def can_write_assignments(user) -> bool:
    """Asignar/mover gente: W en planificador, tablero, trabajadores o flota."""
    return any(
        user_can(user, mod, 'w')
        for mod in ('planificador', 'tablero', 'trabajadores', 'vehiculos')
    )


def user_can(user, module: str, action: str) -> bool:
    """
    Comprueba permiso de módulo. action in r|w|x.
    Admin puede perder módulos vía matriz, excepto configuracion/permisos (anti-lockout).
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    action = (action or '').lower()[:1]
    if action not in ('r', 'w', 'x'):
        return False
    module = normalize_module(module)
    role = getattr(user, 'role', None)
    if not role:
        return False

    # Anti-lockout: admin siempre puede configurar permisos
    if role == ROLE_ADMIN and module in ADMIN_LOCKED_MODULES:
        return True

    allowed = _actions_for(role, module)
    if action not in allowed:
        return False

    # Gate extra histórico: resolver fichajes laboral
    if module == 'auditoria_fichajes' and action == 'x' and role in ROLES_LABORAL_LIKE:
        return laboral_puede_resolver_fichajes()

    return True


def can_resolve_fichajes(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if user_can(user, 'auditoria_fichajes', 'x'):
        if is_laboral(user):
            return laboral_puede_resolver_fichajes()
        return True
    return False


def roles_with_module(module: str, action: str = 'r') -> tuple:
    """Roles que tienen el permiso (para decoradores)."""
    module = normalize_module(module)
    action = (action or 'r').lower()[:1]
    found = []
    from app.services.permission_catalog import PERMISSION_ROLES
    for role, _ in PERMISSION_ROLES:
        if action in _actions_for(role, module):
            if module == 'auditoria_fichajes' and action == 'x' and role in ROLES_LABORAL_LIKE:
                if not laboral_puede_resolver_fichajes():
                    continue
            found.append(role)
        elif role == ROLE_ADMIN and module in ADMIN_LOCKED_MODULES:
            found.append(role)
    return tuple(found)


def save_role_matrix(role: str, form_data) -> int:
    """
    Persiste checkboxes del form para un rol.
    form_data keys: perm__{module}__r / __w / __x
    Devuelve nº de módulos actualizados.
    """
    if not _ensure_table():
        raise RuntimeError(
            'No se pudo crear/acceder a la tabla role_permissions. '
            'Ejecuta la migración de permisos en este tenant.'
        )
    ensure_role_permissions()
    updated = 0
    for module in module_keys():
        can_r = _checkbox_on(form_data, f'perm__{module}__r')
        can_w = _checkbox_on(form_data, f'perm__{module}__w')
        can_x = _checkbox_on(form_data, f'perm__{module}__x')
        if can_w or can_x:
            can_r = True
        if role == ROLE_ADMIN and module in ADMIN_LOCKED_MODULES:
            can_r = can_w = can_x = True
        row = RolePermission.query.filter_by(role=role, module=module).first()
        if not row:
            row = RolePermission(role=role, module=module)
            db.session.add(row)
        row.can_read = bool(can_r)
        row.can_write = bool(can_w)
        row.can_execute = bool(can_x)
        updated += 1
    db.session.commit()
    _clear_perm_cache()
    if has_request_context() and hasattr(g, _TABLE_READY_ATTR):
        delattr(g, _TABLE_READY_ATTR)
    return updated


def matrix_for_role(role: str) -> dict:
    """module -> {r,w,x bools} para la UI."""
    ensure_role_permissions()
    out = {}
    # Pantalla de edición: no reutilizar cache a medias de la misma request
    _clear_perm_cache()
    for module in module_keys():
        actions = _actions_for(role, module)
        if role == ROLE_ADMIN and module in ADMIN_LOCKED_MODULES:
            actions = frozenset('rwx')
        out[module] = {
            'r': 'r' in actions,
            'w': 'w' in actions,
            'x': 'x' in actions,
        }
    return out
