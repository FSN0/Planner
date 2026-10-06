"""Registro de roles del tenant: etiquetas, alta y baja (con roles bloqueados)."""
from __future__ import annotations

import re

from flask import g, has_request_context

from app import db
from app.models import (
    ROLE_ADMIN,
    ROLE_JEFE,
    ROLE_LABORAL,
    ROLE_ADMIN_SUBCONTRATA,
    ROLE_OPERARIO,
    ROLE_RRHH,
    ROLES_BUILTIN,
    ROLES_SYSTEM_LOCKED,
    RolePermission,
    TenantRole,
    User,
)

_TABLE_READY_ATTR = '_tenant_roles_table_ready'
_CACHE_ATTR = '_tenant_roles_cache'

_BUILTIN_LABELS = {
    ROLE_ADMIN: 'Administrador',
    ROLE_JEFE: 'Jefe de obra',
    ROLE_LABORAL: 'Laboral',
    ROLE_RRHH: 'RRHH',
    ROLE_OPERARIO: 'Operario',
    ROLE_ADMIN_SUBCONTRATA: 'Admin subcontrata',
}

_BUILTIN_SORT = {
    ROLE_ADMIN: 10,
    ROLE_JEFE: 20,
    ROLE_LABORAL: 30,
    ROLE_RRHH: 40,
    ROLE_OPERARIO: 50,
    ROLE_ADMIN_SUBCONTRATA: 55,
}

_KEY_RE = re.compile(r'^[a-z][a-z0-9_]{1,38}$')
_RESERVED_KEYS = frozenset(ROLES_BUILTIN) | frozenset({
    'superadmin', 'root', 'system', 'null', 'none', 'undefined',
})


def _clear_cache():
    if has_request_context() and hasattr(g, _CACHE_ATTR):
        delattr(g, _CACHE_ATTR)


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
    if (
        not force_refresh
        and has_request_context()
        and hasattr(g, _TABLE_READY_ATTR)
    ):
        return bool(getattr(g, _TABLE_READY_ATTR))
    ready = False
    try:
        reg = db.session.execute(db.text("SELECT to_regclass('tenant_roles')")).scalar()
        ready = reg is not None
        if not ready:
            row = db.session.execute(db.text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'tenant_roles'
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
    if _table_ready():
        return True
    try:
        schema = db.session.execute(db.text('SELECT current_schema()')).scalar()
        if not schema or schema == 'public':
            return False
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', schema):
            return False
        db.session.execute(db.text(f'''
            CREATE TABLE IF NOT EXISTS {schema}.tenant_roles (
                id SERIAL PRIMARY KEY,
                key VARCHAR(40) NOT NULL UNIQUE,
                label VARCHAR(80) NOT NULL,
                is_system BOOLEAN NOT NULL DEFAULT FALSE,
                is_locked BOOLEAN NOT NULL DEFAULT FALSE,
                sort_order INTEGER NOT NULL DEFAULT 100,
                clone_from VARCHAR(40) NULL
            )
        '''))
        db.session.execute(db.text(
            f'CREATE INDEX IF NOT EXISTS ix_tenant_roles_key '
            f'ON {schema}.tenant_roles (key)'
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


def ensure_tenant_roles() -> int:
    """Siembra roles de fábrica si faltan. Devuelve filas creadas."""
    if not _ensure_table():
        return 0
    created = 0
    for key in ROLES_BUILTIN:
        row = TenantRole.query.filter_by(key=key).first()
        if row:
            continue
        db.session.add(TenantRole(
            key=key,
            label=_BUILTIN_LABELS.get(key, key),
            is_system=True,
            is_locked=key in ROLES_SYSTEM_LOCKED,
            sort_order=_BUILTIN_SORT.get(key, 100),
            clone_from=None,
        ))
        created += 1
    if created:
        db.session.commit()
        _clear_cache()
    return created


def list_roles() -> list[tuple[str, str]]:
    """Lista (key, label) para UI, ordenada."""
    if has_request_context() and hasattr(g, _CACHE_ATTR):
        return list(getattr(g, _CACHE_ATTR))

    if not _ensure_table():
        from app.services.permission_catalog import PERMISSION_ROLES
        return list(PERMISSION_ROLES)

    ensure_tenant_roles()
    rows = TenantRole.query.order_by(TenantRole.sort_order.asc(), TenantRole.key.asc()).all()
    result = [(r.key, r.label) for r in rows]
    if not result:
        from app.services.permission_catalog import PERMISSION_ROLES
        result = list(PERMISSION_ROLES)
    if has_request_context():
        setattr(g, _CACHE_ATTR, result)
    return result


def valid_role_keys() -> set[str]:
    return {k for k, _ in list_roles()}


def get_role(key: str) -> TenantRole | None:
    if not key or not _ensure_table():
        return None
    ensure_tenant_roles()
    return TenantRole.query.filter_by(key=key).first()


def role_display_label(key: str) -> str:
    if not key:
        return ''
    row = get_role(key)
    if row and row.label:
        return row.label
    return _BUILTIN_LABELS.get(key) or key.replace('_', ' ').title()


def is_role_locked(key: str) -> bool:
    if key in ROLES_SYSTEM_LOCKED:
        return True
    row = get_role(key)
    return bool(row and row.is_locked)


def slugify_role_key(raw: str) -> str:
    text = (raw or '').strip().lower()
    for src, dst in (
        ('á', 'a'), ('é', 'e'), ('í', 'i'), ('ó', 'o'), ('ú', 'u'),
        ('ü', 'u'), ('ñ', 'n'),
    ):
        text = text.replace(src, dst)
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text[:40]


def _seed_permissions_for_role(role_key: str, clone_from: str | None) -> None:
    from app.services.permission_catalog import PERMISSION_MODULES, default_actions
    from app.services.permission_service import _clear_perm_cache, ensure_role_permissions

    ensure_role_permissions()
    template = clone_from if clone_from in valid_role_keys() else ROLE_LABORAL
    # Si clonan desde operario a un rol de oficina, copiamos su matriz tal cual
    # (módulos de portal + lo que tenga); la UI de oficina solo edita módulos de oficina.

    # Copiar filas del template si existen; si no, defaults del catálogo
    template_rows = RolePermission.query.filter_by(role=template).all()
    if template_rows:
        for src in template_rows:
            if RolePermission.query.filter_by(role=role_key, module=src.module).first():
                continue
            db.session.add(RolePermission(
                role=role_key,
                module=src.module,
                can_read=src.can_read,
                can_write=src.can_write,
                can_execute=src.can_execute,
            ))
    else:
        for module, _l, _g in PERMISSION_MODULES:
            actions = default_actions(template, module)
            db.session.add(RolePermission(
                role=role_key,
                module=module,
                can_read='r' in actions,
                can_write='w' in actions,
                can_execute='w' in actions,
            ))
    db.session.commit()
    _clear_perm_cache()


def rename_role(key: str, new_label: str) -> TenantRole:
    if not _ensure_table():
        raise RuntimeError('Tabla tenant_roles no disponible')
    ensure_tenant_roles()
    row = TenantRole.query.filter_by(key=key).first()
    if not row:
        raise ValueError('Rol no encontrado')
    if row.is_locked or key in ROLES_SYSTEM_LOCKED:
        raise ValueError('Este rol no se puede renombrar')
    label = (new_label or '').strip()
    if not label or len(label) > 80:
        raise ValueError('Nombre inválido')
    row.label = label
    db.session.commit()
    _clear_cache()
    return row


def create_role(
    *,
    key: str | None = None,
    label: str,
    clone_from: str | None = ROLE_LABORAL,
) -> TenantRole:
    if not _ensure_table():
        raise RuntimeError('Tabla tenant_roles no disponible')
    ensure_tenant_roles()
    label = (label or '').strip()
    if not label or len(label) > 80:
        raise ValueError('Nombre inválido')

    role_key = (key or '').strip().lower() or slugify_role_key(label)
    if not _KEY_RE.match(role_key):
        raise ValueError(
            'Clave inválida: usa minúsculas, números y _ (2-40 caracteres, empieza por letra)'
        )
    if role_key in _RESERVED_KEYS or TenantRole.query.filter_by(key=role_key).first():
        raise ValueError('Ya existe un rol con esa clave')

    template = (clone_from or ROLE_LABORAL).strip()
    if template not in valid_role_keys():
        template = ROLE_LABORAL

    max_sort = db.session.query(db.func.max(TenantRole.sort_order)).scalar() or 100
    row = TenantRole(
        key=role_key,
        label=label,
        is_system=False,
        is_locked=False,
        sort_order=int(max_sort) + 10,
        clone_from=template,
    )
    db.session.add(row)
    db.session.commit()
    _clear_cache()
    _seed_permissions_for_role(role_key, template)
    try:
        from app.services.panel_scope_service import copy_role_panel_scopes
        copy_role_panel_scopes(template, role_key)
    except Exception:
        pass
    try:
        from app.services.assign_mode_service import copy_role_assign_mode
        copy_role_assign_mode(template, role_key)
    except Exception:
        pass
    return row


def delete_role(key: str) -> None:
    if not _ensure_table():
        raise RuntimeError('Tabla tenant_roles no disponible')
    ensure_tenant_roles()
    row = TenantRole.query.filter_by(key=key).first()
    if not row:
        raise ValueError('Rol no encontrado')
    if row.is_system or row.is_locked or key in ROLES_SYSTEM_LOCKED or key in ROLES_BUILTIN:
        raise ValueError('No se pueden eliminar los roles de fábrica')
    users = User.query.filter_by(role=key, is_deleted=False).count()
    if users:
        raise ValueError(
            f'Hay {users} usuario(s) con este rol. Reasígnarlos antes de eliminarlo.'
        )
    RolePermission.query.filter_by(role=key).delete()
    try:
        from app.services.panel_scope_service import clear_role_panel_scopes
        clear_role_panel_scopes(key)
    except Exception:
        pass
    try:
        from app.services.assign_mode_service import clear_role_assign_mode
        clear_role_assign_mode(key)
    except Exception:
        pass
    db.session.delete(row)
    db.session.commit()
    _clear_cache()
    from app.services.permission_service import _clear_perm_cache
    _clear_perm_cache()
