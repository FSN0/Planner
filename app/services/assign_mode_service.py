"""Modos de asignación por rol: gente y vehículos por separado.

Cada uno: directo | solicitud.
- Gente: requiere W en ``asignaciones``
- Vehículos: requiere W en ``vehiculos`` (flota)

App-wide. Independiente del alcance de obras.
"""
from __future__ import annotations

from app.models import ROLE_ADMIN, ROLE_JEFE
from app.services.config_service import get_tenant_config, set_tenant_config

ASSIGN_MODE_DIRECT = 'direct'
ASSIGN_MODE_SOLICITUD = 'solicitud'
ASSIGN_MODES = (ASSIGN_MODE_DIRECT, ASSIGN_MODE_SOLICITUD)

KIND_PEOPLE = 'people'
KIND_VEHICLES = 'vehicles'
ASSIGN_KINDS = (KIND_PEOPLE, KIND_VEHICLES)

_MIGRATED_KEY = 'assign_mode._migrated_v2'
_LEGACY_JEFES_DIRECTO = 'jefes_asignan_directo'
_LEGACY_SINGLE_PREFIX = 'assign_mode.'  # assign_mode.{role} sin kind (v1)


def _config_key(kind: str, role: str) -> str:
    return f'assign_mode.{kind}.{(role or "").strip()}'


def default_assign_mode_for_role(role: str, kind: str = KIND_PEOPLE) -> str:
    del kind  # mismos defaults históricos para gente y coches
    role = (role or '').strip()
    if role == ROLE_ADMIN:
        return ASSIGN_MODE_DIRECT
    if role == ROLE_JEFE:
        try:
            from app.services.tenant_modules import is_soltec_tenant
            return (
                ASSIGN_MODE_SOLICITUD
                if is_soltec_tenant()
                else ASSIGN_MODE_DIRECT
            )
        except Exception:
            return ASSIGN_MODE_SOLICITUD
    return ASSIGN_MODE_DIRECT


def _normalize_mode(raw, role: str, kind: str = KIND_PEOPLE) -> str:
    mode = (raw or '').strip().lower()
    if mode in ASSIGN_MODES:
        return mode
    return default_assign_mode_for_role(role, kind)


def get_role_assign_mode(role: str, kind: str = KIND_PEOPLE) -> str:
    try:
        ensure_assign_modes_migrated()
    except Exception:
        pass
    role = (role or '').strip()
    kind = kind if kind in ASSIGN_KINDS else KIND_PEOPLE
    if role == ROLE_ADMIN:
        return ASSIGN_MODE_DIRECT
    raw = get_tenant_config(_config_key(kind, role), default=None)
    if raw is None or raw == '':
        return default_assign_mode_for_role(role, kind)
    return _normalize_mode(raw, role, kind)


def set_role_assign_mode(role: str, mode: str, kind: str = KIND_PEOPLE):
    role = (role or '').strip()
    kind = kind if kind in ASSIGN_KINDS else KIND_PEOPLE
    if not role:
        raise ValueError('role vacío')
    if role == ROLE_ADMIN:
        mode = ASSIGN_MODE_DIRECT
    mode = _normalize_mode(mode, role, kind)
    set_tenant_config(_config_key(kind, role), mode)


def copy_role_assign_mode(from_role: str, to_role: str):
    for kind in ASSIGN_KINDS:
        set_role_assign_mode(to_role, get_role_assign_mode(from_role, kind), kind)


def clear_role_assign_mode(role: str):
    from app import db
    from app.models import ConfiguracionGlobal

    for kind in ASSIGN_KINDS:
        row = ConfiguracionGlobal.query.filter_by(clave=_config_key(kind, role)).first()
        if row:
            db.session.delete(row)
    # Legacy v1
    legacy = ConfiguracionGlobal.query.filter_by(
        clave=f'{_LEGACY_SINGLE_PREFIX}{(role or "").strip()}'
    ).first()
    if legacy:
        db.session.delete(legacy)
    db.session.commit()


def parse_assign_mode_from_form(form, role: str, kind: str = KIND_PEOPLE) -> str:
    if kind == KIND_VEHICLES:
        raw = form.get('assign_mode_vehicles') or form.get(f'assign_mode_vehicles__{role}')
    else:
        raw = (
            form.get('assign_mode_people')
            or form.get('assign_mode')
            or form.get(f'assign_mode__{role}')
        )
    return _normalize_mode(raw, role, kind)


def user_assign_mode(user, kind: str = KIND_PEOPLE) -> str:
    if not user:
        return ASSIGN_MODE_SOLICITUD
    role = getattr(user, 'role', None) or ''
    if role == ROLE_ADMIN:
        return ASSIGN_MODE_DIRECT
    return get_role_assign_mode(role, kind)


def user_assigns_direct(user) -> bool:
    """Gente: W asignaciones + modo directo."""
    from app.services.permission_service import can_write_assignments

    if not user or not can_write_assignments(user):
        return False
    return user_assign_mode(user, KIND_PEOPLE) == ASSIGN_MODE_DIRECT


def user_assigns_via_solicitud(user) -> bool:
    """Gente: W asignaciones + modo solicitud."""
    from app.services.permission_service import can_write_assignments

    if not user or not can_write_assignments(user):
        return False
    return user_assign_mode(user, KIND_PEOPLE) == ASSIGN_MODE_SOLICITUD


def user_assigns_vehicles_direct(user) -> bool:
    """Coches: tick planificar flota + modo directo."""
    from app.services.permission_service import can_plan_fleet

    if not user or not can_plan_fleet(user):
        return False
    return user_assign_mode(user, KIND_VEHICLES) == ASSIGN_MODE_DIRECT


def user_assigns_vehicles_via_solicitud(user) -> bool:
    """Coches: tick planificar flota + modo solicitud."""
    from app.services.permission_service import can_plan_fleet

    if not user or not can_plan_fleet(user):
        return False
    return user_assign_mode(user, KIND_VEHICLES) == ASSIGN_MODE_SOLICITUD


def role_assigns_direct(role: str, kind: str = KIND_PEOPLE) -> bool:
    return get_role_assign_mode(role, kind) == ASSIGN_MODE_DIRECT


def ensure_assign_modes_migrated():
    """
    v1: tick jefes_asignan_directo → assign_mode.{jefe}
    v2: assign_mode.{role} → people + vehicles; claves con kind.
    """
    if get_tenant_config(_MIGRATED_KEY, default=None):
        return

    from app import db
    from app.models import ConfiguracionGlobal

    # --- Paso v1 (legacy tick) ---
    legacy_tick = ConfiguracionGlobal.query.filter_by(clave=_LEGACY_JEFES_DIRECTO).first()
    v1_jefe = get_tenant_config(f'{_LEGACY_SINGLE_PREFIX}{ROLE_JEFE}', default=None)

    if legacy_tick is not None and not v1_jefe:
        raw = (legacy_tick.valor or '').strip().lower()
        mode = (
            ASSIGN_MODE_DIRECT
            if raw in ('true', '1', 'yes', 'on')
            else ASSIGN_MODE_SOLICITUD
        )
        set_tenant_config(_config_key(KIND_PEOPLE, ROLE_JEFE), mode)
        set_tenant_config(_config_key(KIND_VEHICLES, ROLE_JEFE), mode)
        db.session.delete(legacy_tick)
    elif legacy_tick is not None:
        db.session.delete(legacy_tick)

    # --- Paso v2: claves planas assign_mode.{role} → people+vehicles ---
    prefix = _LEGACY_SINGLE_PREFIX
    rows = ConfiguracionGlobal.query.filter(
        ConfiguracionGlobal.clave.like(f'{prefix}%')
    ).all()
    for row in rows:
        clave = row.clave or ''
        if clave in (_MIGRATED_KEY, 'assign_mode._migrated_v1'):
            continue
        if clave.startswith('assign_mode.people.') or clave.startswith('assign_mode.vehicles.'):
            continue
        # assign_mode.{role}
        role = clave[len(prefix):]
        if not role or '.' in role:
            continue
        mode = _normalize_mode(row.valor, role, KIND_PEOPLE)
        set_tenant_config(_config_key(KIND_PEOPLE, role), mode)
        set_tenant_config(_config_key(KIND_VEHICLES, role), mode)
        db.session.delete(row)

    # Materializar jefe si aún no hay people
    if not get_tenant_config(_config_key(KIND_PEOPLE, ROLE_JEFE), default=None):
        mode = default_assign_mode_for_role(ROLE_JEFE)
        set_tenant_config(_config_key(KIND_PEOPLE, ROLE_JEFE), mode)
        set_tenant_config(_config_key(KIND_VEHICLES, ROLE_JEFE), mode)

    set_tenant_config(_MIGRATED_KEY, '1')
    # Limpia marca v1 si existía
    v1 = ConfiguracionGlobal.query.filter_by(clave='assign_mode._migrated_v1').first()
    if v1:
        db.session.delete(v1)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
