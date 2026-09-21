"""Alcance de obras por rol (planificador / tablero)."""
import json
from types import SimpleNamespace

import pytest

from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH
from app.services.panel_scope_service import (
    PANEL_PLANIFICADOR,
    PANEL_TABLERO,
    SCOPE_ALL,
    SCOPE_JEFE,
    SCOPE_JEFES,
    SCOPE_NONE,
    clear_role_panel_scopes,
    copy_role_panel_scopes,
    default_scope_for_role,
    get_role_panel_scope,
    get_user_panel_scope,
    parse_scope_from_form,
    planning_acts_as_office,
    planning_custody_jefe_ids,
    set_role_panel_scope,
    user_custody_jefe_ids,
    user_panel_mode,
)


@pytest.fixture
def scope_store(monkeypatch):
    store = {}

    def fake_get(key, default=None):
        return store.get(key, default)

    def fake_set(key, value, **_kwargs):
        store[key] = value

    monkeypatch.setattr(
        'app.services.panel_scope_service.get_tenant_config', fake_get
    )
    monkeypatch.setattr(
        'app.services.panel_scope_service.set_tenant_config', fake_set
    )
    return store


def test_defaults_builtin_roles():
    assert default_scope_for_role(ROLE_ADMIN)['mode'] == SCOPE_ALL
    assert default_scope_for_role(ROLE_JEFE)['mode'] == SCOPE_JEFE
    assert default_scope_for_role(ROLE_LABORAL)['mode'] == SCOPE_ALL
    assert default_scope_for_role(ROLE_RRHH)['mode'] == SCOPE_ALL
    assert default_scope_for_role('director_rrhh')['mode'] == SCOPE_NONE


def test_get_role_falls_back_to_default(scope_store):
    assert get_role_panel_scope('director_rrhh', PANEL_PLANIFICADOR) == {
        'mode': SCOPE_NONE,
        'jefe_ids': [],
    }
    assert get_role_panel_scope(ROLE_LABORAL, PANEL_TABLERO)['mode'] == SCOPE_ALL


def test_set_and_get_jefes_scope(scope_store):
    set_role_panel_scope('director_rrhh', PANEL_PLANIFICADOR, SCOPE_JEFES, [3, 1, 3])
    scope = get_role_panel_scope('director_rrhh', PANEL_PLANIFICADOR)
    assert scope['mode'] == SCOPE_JEFES
    assert scope['jefe_ids'] == [1, 3]
    raw = scope_store['panel_scope.planificador.director_rrhh']
    assert json.loads(raw)['jefe_ids'] == [1, 3]


def test_non_jefes_mode_drops_ids(scope_store):
    set_role_panel_scope('custom', PANEL_TABLERO, SCOPE_ALL, [9, 8])
    assert get_role_panel_scope('custom', PANEL_TABLERO) == {
        'mode': SCOPE_ALL,
        'jefe_ids': [],
    }


def test_admin_user_always_office(scope_store):
    set_role_panel_scope(ROLE_ADMIN, PANEL_PLANIFICADOR, SCOPE_NONE, [])
    user = SimpleNamespace(id=1, role=ROLE_ADMIN)
    assert get_user_panel_scope(user, PANEL_PLANIFICADOR)['mode'] == SCOPE_ALL
    assert user_panel_mode(user, PANEL_PLANIFICADOR) == 'office'
    assert planning_acts_as_office(user) is True


def test_jefe_user_forced_to_custody(scope_store):
    set_role_panel_scope(ROLE_JEFE, PANEL_PLANIFICADOR, SCOPE_ALL, [])
    user = SimpleNamespace(id=42, role=ROLE_JEFE)
    assert get_user_panel_scope(user, PANEL_PLANIFICADOR)['mode'] == SCOPE_JEFE
    assert user_panel_mode(user, PANEL_PLANIFICADOR) == 'custody'
    assert planning_custody_jefe_ids(user) == [42]
    assert planning_acts_as_office(user) is False


def test_custom_role_all_is_office(scope_store):
    set_role_panel_scope('director_rrhh', PANEL_PLANIFICADOR, SCOPE_ALL, [])
    user = SimpleNamespace(id=10, role='director_rrhh')
    assert user_panel_mode(user, PANEL_PLANIFICADOR) == 'office'
    assert planning_acts_as_office(user) is True
    assert planning_custody_jefe_ids(user) == []


def test_custom_role_jefes_custody(scope_store):
    set_role_panel_scope('coord', PANEL_PLANIFICADOR, SCOPE_JEFES, [5, 7])
    user = SimpleNamespace(id=99, role='coord')
    assert user_panel_mode(user, PANEL_PLANIFICADOR) == 'custody'
    assert user_custody_jefe_ids(user, PANEL_PLANIFICADOR) == [5, 7]


def test_custom_role_none(scope_store):
    user = SimpleNamespace(id=1, role='sin_alcance')
    assert user_panel_mode(user, PANEL_PLANIFICADOR) == 'none'
    assert planning_acts_as_office(user) is False


def test_panels_are_independent(scope_store):
    set_role_panel_scope('coord', PANEL_PLANIFICADOR, SCOPE_ALL, [])
    set_role_panel_scope('coord', PANEL_TABLERO, SCOPE_JEFES, [2])
    user = SimpleNamespace(id=1, role='coord')
    assert user_panel_mode(user, PANEL_PLANIFICADOR) == 'office'
    assert user_panel_mode(user, PANEL_TABLERO) == 'custody'
    assert user_custody_jefe_ids(user, PANEL_TABLERO) == [2]


def test_copy_role_panel_scopes(scope_store):
    set_role_panel_scope(ROLE_LABORAL, PANEL_PLANIFICADOR, SCOPE_ALL, [])
    set_role_panel_scope(ROLE_LABORAL, PANEL_TABLERO, SCOPE_JEFES, [4])
    copy_role_panel_scopes(ROLE_LABORAL, 'nuevo_rol')
    assert get_role_panel_scope('nuevo_rol', PANEL_PLANIFICADOR)['mode'] == SCOPE_ALL
    assert get_role_panel_scope('nuevo_rol', PANEL_TABLERO) == {
        'mode': SCOPE_JEFES,
        'jefe_ids': [4],
    }


def test_clear_role_panel_scopes(scope_store, monkeypatch):
    set_role_panel_scope('tmp_rol', PANEL_PLANIFICADOR, SCOPE_ALL, [])
    set_role_panel_scope('tmp_rol', PANEL_TABLERO, SCOPE_JEFE, [])

    class FakeRow:
        def __init__(self, clave):
            self.clave = clave

    class FakeQuery:
        def filter_by(self, clave=None):
            self._clave = clave
            return self

        def first(self):
            if getattr(self, '_clave', None) in scope_store:
                return FakeRow(self._clave)
            return None

    class FakeModel:
        query = FakeQuery()

    class FakeSession:
        def delete(self, row):
            scope_store.pop(row.clave, None)

        def commit(self):
            pass

    monkeypatch.setattr(
        'app.models.ConfiguracionGlobal', FakeModel, raising=False
    )
    # clear_role_panel_scopes does: from app.models import ConfiguracionGlobal
    import app.models as models_mod
    monkeypatch.setattr(models_mod, 'ConfiguracionGlobal', FakeModel)
    monkeypatch.setattr('app.db.session', FakeSession())

    clear_role_panel_scopes('tmp_rol')
    assert get_role_panel_scope('tmp_rol', PANEL_PLANIFICADOR)['mode'] == SCOPE_NONE
    assert get_role_panel_scope('tmp_rol', PANEL_TABLERO)['mode'] == SCOPE_NONE


def test_parse_scope_from_form():
    class FakeForm(dict):
        def getlist(self, key):
            val = self.get(key, [])
            if isinstance(val, list):
                return val
            return [val]

    form = FakeForm({
        'scope__planificador__mode': 'jefes',
        'scope__planificador__jefe_ids': ['10', 'x', '12'],
    })
    mode, ids = parse_scope_from_form(form, PANEL_PLANIFICADOR)
    assert mode == SCOPE_JEFES
    assert ids == [10, 12]
