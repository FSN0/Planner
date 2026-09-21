"""Alcance de obras por rol en planificador y tablero.

Independiente de la matriz r/w:
- r/w = puede abrir / actuar en el panel
- alcance = qué obras ve y con qué reglas escribe (oficina vs custodia)

Modos: none | jefe | jefes | all
"""
from __future__ import annotations

import json
from typing import Iterable

from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH, Obra, User
from app.services.config_service import get_tenant_config, set_tenant_config

PANEL_PLANIFICADOR = 'planificador'
PANEL_TABLERO = 'tablero'
PANELS = (PANEL_PLANIFICADOR, PANEL_TABLERO)

SCOPE_NONE = 'none'
SCOPE_JEFE = 'jefe'
SCOPE_JEFES = 'jefes'
SCOPE_ALL = 'all'
SCOPES = (SCOPE_NONE, SCOPE_JEFE, SCOPE_JEFES, SCOPE_ALL)


def _config_key(panel: str, role: str) -> str:
    return f'panel_scope.{panel}.{role}'


def default_scope_for_role(role: str, panel: str | None = None) -> dict:
    """Defaults compatibles con el comportamiento histórico por rol built-in."""
    del panel  # mismos defaults en ambos paneles
    if role == ROLE_ADMIN:
        return {'mode': SCOPE_ALL, 'jefe_ids': []}
    if role == ROLE_JEFE:
        return {'mode': SCOPE_JEFE, 'jefe_ids': []}
    if role in (ROLE_LABORAL, ROLE_RRHH):
        return {'mode': SCOPE_ALL, 'jefe_ids': []}
    return {'mode': SCOPE_NONE, 'jefe_ids': []}


def _normalize_scope(data: dict | None, role: str) -> dict:
    base = default_scope_for_role(role)
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
    # Admin / jefe sistema: el modo efectivo lo fijamos al leer por usuario,
    # pero guardamos lo que pidan (salvo admin forzado a all en get).
    return {'mode': mode, 'jefe_ids': sorted(set(jefe_ids))}


def get_role_panel_scope(role: str, panel: str) -> dict:
    if panel not in PANELS:
        panel = PANEL_PLANIFICADOR
    role = (role or '').strip()
    raw = get_tenant_config(_config_key(panel, role), default=None)
    if not raw:
        return default_scope_for_role(role, panel)
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return default_scope_for_role(role, panel)
    return _normalize_scope(data, role)


def set_role_panel_scope(role: str, panel: str, mode: str, jefe_ids: Iterable[int] | None = None):
    if panel not in PANELS:
        raise ValueError('panel inválido')
    role = (role or '').strip()
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
    set_tenant_config(_config_key(panel, role), payload)


def copy_role_panel_scopes(from_role: str, to_role: str):
    for panel in PANELS:
        scope = get_role_panel_scope(from_role, panel)
        set_role_panel_scope(to_role, panel, scope['mode'], scope.get('jefe_ids'))


def clear_role_panel_scopes(role: str):
    from app.models import ConfiguracionGlobal
    from app import db

    for panel in PANELS:
        clave = _config_key(panel, role)
        row = ConfiguracionGlobal.query.filter_by(clave=clave).first()
        if row:
            db.session.delete(row)
    db.session.commit()


def get_user_panel_scope(user, panel: str) -> dict:
    role = getattr(user, 'role', None) or ''
    scope = get_role_panel_scope(role, panel)
    # Built-ins: no dejar que un admin se quede en none por config rara.
    if role == ROLE_ADMIN:
        return {'mode': SCOPE_ALL, 'jefe_ids': []}
    if role == ROLE_JEFE and scope['mode'] in (SCOPE_NONE, SCOPE_ALL):
        # Un jefe_obra siempre opera en modo custodia propia.
        return {'mode': SCOPE_JEFE, 'jefe_ids': []}
    return scope


def user_panel_mode(user, panel: str) -> str:
    """none | office | custody"""
    scope = get_user_panel_scope(user, panel)
    mode = scope.get('mode') or SCOPE_NONE
    if mode == SCOPE_NONE:
        return 'none'
    if mode == SCOPE_ALL:
        return 'office'
    return 'custody'


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


def apply_obra_scope_filter(query, user, panel: str, jefe_id_filter=None):
    """Aplica el alcance del panel a una query de Obra. Devuelve query (puede quedar vacía)."""
    mode = user_panel_mode(user, panel)
    if mode == 'none':
        return query.filter(Obra.id.is_(None))  # vacío
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


def parse_scope_from_form(form, panel: str) -> tuple[str, list[int]]:
    mode = (form.get(f'scope__{panel}__mode') or SCOPE_NONE).strip().lower()
    if mode not in SCOPES:
        mode = SCOPE_NONE
    ids = []
    for raw in form.getlist(f'scope__{panel}__jefe_ids'):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return mode, ids
