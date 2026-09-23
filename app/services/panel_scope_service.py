"""Alcances de obras por rol (tres dimensiones independientes).

Kinds:
- planificacion → tablero, Gantt, directorio visible, planificar gente/flota, ausencias
- auditoria_fichajes → auditoría + mapa de fichajes
- solicitudes → buzón al resolver (personal y flota)

Matriz r/w = entrar/actuar. Alcance = qué obras entran en cada función.
"""
from __future__ import annotations

import json
from typing import Iterable

from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH, Obra, User
from app.services.config_service import get_tenant_config, set_tenant_config

# Kinds de alcance
KIND_PLANIFICACION = 'planificacion'
KIND_AUDITORIA = 'auditoria_fichajes'
KIND_SOLICITUDES = 'solicitudes'
SCOPE_KINDS = (KIND_PLANIFICACION, KIND_AUDITORIA, KIND_SOLICITUDES)

# Compat: paneles antiguos → kind
PANEL_PLANIFICADOR = 'planificador'
PANEL_TABLERO = 'tablero'
PANEL_AUDITORIA_FICHAJES = 'auditoria_fichajes'
PANEL_OBRAS = 'obras'
PANEL_SOLICITUDES = 'solicitudes'
PANEL_MAPA = 'mapa_fichajes'
PANELS = (
    PANEL_PLANIFICADOR,
    PANEL_TABLERO,
    PANEL_AUDITORIA_FICHAJES,
    PANEL_OBRAS,
    PANEL_SOLICITUDES,
    PANEL_MAPA,
)

SCOPE_NONE = 'none'
SCOPE_JEFE = 'jefe'
SCOPE_JEFES = 'jefes'
SCOPE_ALL = 'all'
SCOPES = (SCOPE_NONE, SCOPE_JEFE, SCOPE_JEFES, SCOPE_ALL)

_KIND_PREFIX = 'obra_scope.'
_LEGACY_FLAT_PREFIX = 'obra_scope.'  # obra_scope.{role} sin kind (v1 unified)
_TRIPLE_MIGRATED = 'obra_scope._kinds_v1'
_UNIFIED_MIGRATED = 'obra_scope._unified_v1'


def _panel_to_kind(panel: str | None) -> str:
    p = (panel or KIND_PLANIFICACION).strip()
    if p in (PANEL_AUDITORIA_FICHAJES, PANEL_MAPA, KIND_AUDITORIA):
        return KIND_AUDITORIA
    if p in (PANEL_SOLICITUDES, KIND_SOLICITUDES):
        return KIND_SOLICITUDES
    return KIND_PLANIFICACION


def _config_key(kind: str, role: str) -> str:
    kind = kind if kind in SCOPE_KINDS else KIND_PLANIFICACION
    return f'{_KIND_PREFIX}{kind}.{(role or "").strip()}'


def _legacy_flat_key(role: str) -> str:
    return f'{_LEGACY_FLAT_PREFIX}{(role or "").strip()}'


def _legacy_panel_key(panel: str, role: str) -> str:
    return f'panel_scope.{panel}.{role}'


def default_scope_for_role(role: str, panel: str | None = None) -> dict:
    """Defaults por rol (mismo para los 3 kinds; panel solo por compat)."""
    del panel
    if role == ROLE_ADMIN:
        return {'mode': SCOPE_ALL, 'jefe_ids': []}
    if role == ROLE_JEFE:
        return {'mode': SCOPE_JEFE, 'jefe_ids': []}
    if role in (ROLE_LABORAL, ROLE_RRHH):
        return {'mode': SCOPE_ALL, 'jefe_ids': []}
    return {'mode': SCOPE_NONE, 'jefe_ids': []}


def _normalize_scope(data: dict | None, role: str, panel: str | None = None) -> dict:
    base = default_scope_for_role(role, panel)
    if not isinstance(data, dict):
        return base
    mode = (data.get('mode') or base['mode'] or SCOPE_NONE).strip().lower()
    if mode not in SCOPES:
        mode = base['mode']
    jefe_ids = []
    raw_ids = data.get('jefe_ids') or []
    if isinstance(raw_ids, (list, tuple)):
        for x in raw_ids:
            try:
                jefe_ids.append(int(x))
            except (TypeError, ValueError):
                continue
    return {'mode': mode, 'jefe_ids': sorted(set(jefe_ids))}


def _parse_raw_scope(raw, role: str, panel: str | None = None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return _normalize_scope(data, role, panel)


def ensure_obra_scope_unified():
    """Compat: migra panel_scope.* → flat obra_scope.{role}, luego a 3 kinds."""
    _ensure_kinds_migrated()


def _ensure_kinds_migrated():
    if get_tenant_config(_TRIPLE_MIGRATED, default=None):
        return

    from app.services.role_registry_service import list_roles

    try:
        roles = [r for r, _ in list_roles()]
    except Exception:
        roles = [ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH]

    # Paso A: panel_scope / flat → base
    if not get_tenant_config(_UNIFIED_MIGRATED, default=None):
        for role in roles:
            if get_tenant_config(_legacy_flat_key(role), default=None):
                continue
            chosen = None
            for panel in (PANEL_PLANIFICADOR, PANEL_TABLERO, PANEL_AUDITORIA_FICHAJES):
                raw = get_tenant_config(_legacy_panel_key(panel, role), default=None)
                parsed = _parse_raw_scope(raw, role)
                if parsed:
                    chosen = parsed
                    break
            if not chosen:
                chosen = default_scope_for_role(role)
            payload = json.dumps({
                'mode': chosen['mode'],
                'jefe_ids': chosen.get('jefe_ids') or [],
            })
            set_tenant_config(_legacy_flat_key(role), payload)
        set_tenant_config(_UNIFIED_MIGRATED, '1')

    # Paso B: flat → 3 kinds (copia el mismo valor; luego se editan aparte)
    for role in roles:
        flat = _parse_raw_scope(
            get_tenant_config(_legacy_flat_key(role), default=None), role
        ) or default_scope_for_role(role)
        payload = json.dumps({
            'mode': flat['mode'],
            'jefe_ids': flat.get('jefe_ids') or [],
        })
        for kind in SCOPE_KINDS:
            if not get_tenant_config(_config_key(kind, role), default=None):
                set_tenant_config(_config_key(kind, role), payload)

    set_tenant_config(_TRIPLE_MIGRATED, '1')


def get_role_scope(role: str, kind: str = KIND_PLANIFICACION) -> dict:
    try:
        _ensure_kinds_migrated()
    except Exception:
        pass
    role = (role or '').strip()
    kind = kind if kind in SCOPE_KINDS else KIND_PLANIFICACION
    raw = get_tenant_config(_config_key(kind, role), default=None)
    parsed = _parse_raw_scope(raw, role)
    if parsed:
        return parsed
    # Fallback flat legacy
    flat = _parse_raw_scope(get_tenant_config(_legacy_flat_key(role), default=None), role)
    if flat:
        return flat
    return default_scope_for_role(role)


def set_role_scope(role: str, kind: str, mode: str, jefe_ids: Iterable[int] | None = None):
    role = (role or '').strip()
    kind = kind if kind in SCOPE_KINDS else KIND_PLANIFICACION
    mode = (mode or SCOPE_NONE).strip().lower()
    if mode not in SCOPES:
        mode = SCOPE_NONE
    ids = []
    for x in (jefe_ids or []):
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    if mode != SCOPE_JEFES:
        ids = []
    payload = json.dumps({'mode': mode, 'jefe_ids': sorted(set(ids))})
    set_tenant_config(_config_key(kind, role), payload)
    # Mantener flat + legacy panel keys alineados al de planificación (compat)
    if kind == KIND_PLANIFICACION:
        set_tenant_config(_legacy_flat_key(role), payload)
        for panel in (PANEL_PLANIFICADOR, PANEL_TABLERO, PANEL_OBRAS):
            set_tenant_config(_legacy_panel_key(panel, role), payload)
    elif kind == KIND_AUDITORIA:
        set_tenant_config(_legacy_panel_key(PANEL_AUDITORIA_FICHAJES, role), payload)


def get_role_obra_scope(role: str) -> dict:
    """Compat: alcance de planificación."""
    return get_role_scope(role, KIND_PLANIFICACION)


def set_role_obra_scope(role: str, mode: str, jefe_ids: Iterable[int] | None = None):
    set_role_scope(role, KIND_PLANIFICACION, mode, jefe_ids)


def get_role_panel_scope(role: str, panel: str) -> dict:
    return get_role_scope(role, _panel_to_kind(panel))


def set_role_panel_scope(role: str, panel: str, mode: str, jefe_ids: Iterable[int] | None = None):
    set_role_scope(role, _panel_to_kind(panel), mode, jefe_ids)


def copy_role_panel_scopes(from_role: str, to_role: str):
    for kind in SCOPE_KINDS:
        scope = get_role_scope(from_role, kind)
        set_role_scope(to_role, kind, scope['mode'], scope.get('jefe_ids'))


def clear_role_panel_scopes(role: str):
    from app.models import ConfiguracionGlobal
    from app import db

    claves = [_legacy_flat_key(role)] + [_config_key(k, role) for k in SCOPE_KINDS]
    claves += [_legacy_panel_key(p, role) for p in (
        PANEL_PLANIFICADOR, PANEL_TABLERO, PANEL_AUDITORIA_FICHAJES, PANEL_OBRAS,
    )]
    for clave in claves:
        row = ConfiguracionGlobal.query.filter_by(clave=clave).first()
        if row:
            db.session.delete(row)
    db.session.commit()


def get_user_scope(user, kind: str = KIND_PLANIFICACION) -> dict:
    role = getattr(user, 'role', None) or ''
    scope = get_role_scope(role, kind)
    if role == ROLE_ADMIN:
        return {'mode': SCOPE_ALL, 'jefe_ids': []}
    # Jefe de obra: planificación siempre custodía propia (no “todas”)
    if role == ROLE_JEFE and kind == KIND_PLANIFICACION and scope['mode'] in (
        SCOPE_NONE, SCOPE_ALL,
    ):
        return {'mode': SCOPE_JEFE, 'jefe_ids': []}
    return scope


def get_user_panel_scope(user, panel: str) -> dict:
    return get_user_scope(user, _panel_to_kind(panel))


def user_panel_mode(user, panel: str) -> str:
    """none | office | custody"""
    scope = get_user_panel_scope(user, panel)
    mode = scope.get('mode') or SCOPE_NONE
    if mode == SCOPE_NONE:
        return 'none'
    if mode == SCOPE_ALL:
        return 'office'
    return 'custody'


def user_scope_mode(user, kind: str) -> str:
    return user_panel_mode(user, kind)


def user_custody_jefe_ids(user, panel: str) -> list[int]:
    scope = get_user_panel_scope(user, panel)
    mode = scope.get('mode')
    if mode == SCOPE_JEFE:
        uid = getattr(user, 'id', None)
        return [int(uid)] if uid else []
    if mode == SCOPE_JEFES:
        return list(scope.get('jefe_ids') or [])
    return []


def planning_acts_as_office(user) -> bool:
    return user_panel_mode(user, PANEL_PLANIFICADOR) == 'office'


def planning_custody_jefe_ids(user) -> list[int]:
    return user_custody_jefe_ids(user, PANEL_PLANIFICADOR)


def obra_in_planning_custody(user, obra) -> bool:
    if not obra:
        return False
    if planning_acts_as_office(user):
        return True
    custody = set(planning_custody_jefe_ids(user))
    return bool(obra.jefe_obra_id and obra.jefe_obra_id in custody)


def planning_move_involves_custody(user, *obras) -> bool:
    if planning_acts_as_office(user):
        return True
    for obra in obras:
        if obra is None:
            continue
        if isinstance(obra, int):
            obra = Obra.query.get(obra)
        if obra_in_planning_custody(user, obra):
            return True
    return False


def apply_obra_scope_filter(query, user, panel: str, jefe_id_filter=None):
    mode = user_panel_mode(user, panel)
    if mode == 'none':
        return query.filter(Obra.id.is_(None))
    if mode == 'office':
        if jefe_id_filter:
            try:
                jid = int(jefe_id_filter)
            except (TypeError, ValueError):
                jid = None
            if jid:
                return query.filter(Obra.jefe_obra_id == jid)
        return query
    ids = user_custody_jefe_ids(user, panel)
    if not ids:
        return query.filter(Obra.id.is_(None))
    return query.filter(Obra.jefe_obra_id.in_(ids))


def _obras_ids_for_custody_jefes(jefe_ids: list[int]) -> list[int]:
    if not jefe_ids:
        return []
    return [
        oid
        for (oid,) in (
            Obra.query.filter(Obra.jefe_obra_id.in_(jefe_ids))
            .with_entities(Obra.id)
            .all()
        )
    ]


def registro_fichaje_scope_clause(user, panel: str = PANEL_AUDITORIA_FICHAJES):
    from sqlalchemy import false, or_

    from app.models import RegistroFichaje

    mode = user_panel_mode(user, panel)
    if mode == 'none':
        return false()
    if mode == 'office':
        return None
    jefe_ids = user_custody_jefe_ids(user, panel)
    obras_ids = _obras_ids_for_custody_jefes(jefe_ids)
    if not obras_ids:
        return false()
    return or_(
        RegistroFichaje.obra_planificada_id.in_(obras_ids),
        RegistroFichaje.obra_real_id.in_(obras_ids),
    )


def registro_fichaje_in_scope(user, registro, panel: str = PANEL_AUDITORIA_FICHAJES) -> bool:
    if not registro:
        return False
    mode = user_panel_mode(user, panel)
    if mode == 'none':
        return False
    if mode == 'office':
        return True
    allowed = set(user_custody_jefe_ids(user, panel))
    if not allowed:
        return False
    for oid in (registro.obra_planificada_id, registro.obra_real_id):
        if not oid:
            continue
        obra = Obra.query.get(oid)
        if obra and obra.jefe_obra_id in allowed:
            return True
    return False


def solicitud_obra_in_scope(user, obra) -> bool:
    """¿Esta obra entra en el buzón de solicitudes del usuario?"""
    if not obra:
        return user_panel_mode(user, PANEL_SOLICITUDES) == 'office'
    mode = user_panel_mode(user, PANEL_SOLICITUDES)
    if mode == 'none':
        return False
    if mode == 'office':
        return True
    custody = set(user_custody_jefe_ids(user, PANEL_SOLICITUDES))
    return bool(obra.jefe_obra_id and obra.jefe_obra_id in custody)


def list_jefes_for_scope_ui():
    return (
        User.query.filter(
            User.role == ROLE_JEFE,
            User.is_deleted.is_(False),
            User.active.is_(True),
        )
        .order_by(User.name, User.lastname)
        .all()
    )


def parse_scope_from_form(form, panel: str = PANEL_OBRAS) -> tuple[str, list[int]]:
    """Acepta scope__{kind}__* o legacy scope__obras__*."""
    kind = _panel_to_kind(panel)
    mode = (
        form.get(f'scope__{kind}__mode')
        or form.get('scope__obras__mode')
        or form.get(f'scope__{panel}__mode')
        or form.get('scope__planificador__mode')
        or SCOPE_NONE
    )
    mode = (mode or SCOPE_NONE).strip().lower()
    if mode not in SCOPES:
        mode = SCOPE_NONE
    ids = []
    raw_list = (
        form.getlist(f'scope__{kind}__jefe_ids')
        or form.getlist('scope__obras__jefe_ids')
        or form.getlist(f'scope__{panel}__jefe_ids')
        or form.getlist('scope__planificador__jefe_ids')
    )
    for raw in raw_list:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return mode, ids


def parse_all_scopes_from_form(form) -> dict[str, tuple[str, list[int]]]:
    """kind → (mode, jefe_ids) desde el formulario de permisos."""
    out = {}
    for kind in SCOPE_KINDS:
        mode = form.get(f'scope__{kind}__mode') or SCOPE_NONE
        mode = (mode or SCOPE_NONE).strip().lower()
        if mode not in SCOPES:
            mode = SCOPE_NONE
        ids = []
        for raw in form.getlist(f'scope__{kind}__jefe_ids'):
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        out[kind] = (mode, ids)
    # Compat: un solo scope__obras__ → los tres si no vinieron kinds
    if not any(form.get(f'scope__{k}__mode') for k in SCOPE_KINDS):
        mode, ids = parse_scope_from_form(form, PANEL_OBRAS)
        for kind in SCOPE_KINDS:
            out[kind] = (mode, ids)
    return out
