"""Alcances de obras: cuatro kinds (planificación / auditoría / solicitudes / valoraciones)."""
from types import SimpleNamespace

import pytest

from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL
from app.services.panel_scope_service import (
    KIND_AUDITORIA,
    KIND_PLANIFICACION,
    KIND_SOLICITUDES,
    KIND_VALORACIONES,
    PANEL_AUDITORIA_FICHAJES,
    PANEL_MAPA,
    PANEL_PLANIFICADOR,
    PANEL_SOLICITUDES,
    PANEL_TABLERO,
    SCOPE_ALL,
    SCOPE_JEFE,
    SCOPE_JEFES,
    SCOPE_NONE,
    clear_role_panel_scopes,
    copy_role_panel_scopes,
    default_scope_for_role,
    get_role_obra_scope,
    get_role_panel_scope,
    get_role_scope,
    get_user_panel_scope,
    parse_all_scopes_from_form,
    planning_acts_as_office,
    planning_custody_jefe_ids,
    set_role_obra_scope,
    set_role_scope,
    user_panel_mode,
    valoraciones_acts_as_office,
    valoraciones_visible_author_ids,
)


@pytest.fixture
def scope_store(monkeypatch):
    store = {
        'obra_scope._unified_v1': '1',
        'obra_scope._kinds_v1': '1',
        'obra_scope._valoraciones_v1': '1',
    }

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
    assert default_scope_for_role('director_rrhh')['mode'] == SCOPE_NONE


def test_four_kinds_independent(scope_store):
    set_role_scope('coord', KIND_PLANIFICACION, SCOPE_JEFES, [1, 2])
    set_role_scope('coord', KIND_AUDITORIA, SCOPE_ALL, [])
    set_role_scope('coord', KIND_SOLICITUDES, SCOPE_JEFE, [])
    set_role_scope('coord', KIND_VALORACIONES, SCOPE_JEFES, [9])
    assert get_role_scope('coord', KIND_PLANIFICACION) == {
        'mode': SCOPE_JEFES, 'jefe_ids': [1, 2],
    }
    assert get_role_scope('coord', KIND_AUDITORIA)['mode'] == SCOPE_ALL
    assert get_role_scope('coord', KIND_SOLICITUDES)['mode'] == SCOPE_JEFE
    assert get_role_scope('coord', KIND_VALORACIONES) == {
        'mode': SCOPE_JEFES, 'jefe_ids': [9],
    }
    assert get_role_panel_scope('coord', PANEL_TABLERO)['jefe_ids'] == [1, 2]
    assert get_role_panel_scope('coord', PANEL_MAPA)['mode'] == SCOPE_ALL
    assert get_role_panel_scope('coord', PANEL_SOLICITUDES)['mode'] == SCOPE_JEFE


def test_admin_user_always_office(scope_store):
    set_role_scope(ROLE_ADMIN, KIND_PLANIFICACION, SCOPE_NONE, [])
    user = SimpleNamespace(id=1, role=ROLE_ADMIN)
    assert get_user_panel_scope(user, PANEL_PLANIFICADOR)['mode'] == SCOPE_ALL
    assert planning_acts_as_office(user) is True
    assert valoraciones_acts_as_office(user) is True


def test_jefe_planning_forced_custody(scope_store):
    set_role_scope(ROLE_JEFE, KIND_PLANIFICACION, SCOPE_ALL, [])
    user = SimpleNamespace(id=42, role=ROLE_JEFE)
    assert get_user_panel_scope(user, PANEL_PLANIFICADOR)['mode'] == SCOPE_JEFE
    assert planning_custody_jefe_ids(user) == [42]


def test_jefe_can_have_office_auditoria(scope_store):
    set_role_scope(ROLE_JEFE, KIND_AUDITORIA, SCOPE_ALL, [])
    user = SimpleNamespace(id=42, role=ROLE_JEFE)
    assert user_panel_mode(user, PANEL_AUDITORIA_FICHAJES) == 'office'
    assert user_panel_mode(user, PANEL_MAPA) == 'office'


def test_jefe_valoraciones_only_own(scope_store):
    set_role_scope(ROLE_JEFE, KIND_VALORACIONES, SCOPE_JEFE, [])
    user = SimpleNamespace(id=42, role=ROLE_JEFE)
    assert valoraciones_acts_as_office(user) is False
    assert valoraciones_visible_author_ids(user) == {42}


def test_valoraciones_jefes_includes_self(scope_store):
    set_role_scope(ROLE_LABORAL, KIND_VALORACIONES, SCOPE_JEFES, [7, 8])
    user = SimpleNamespace(id=3, role=ROLE_LABORAL)
    assert valoraciones_visible_author_ids(user) == {3, 7, 8}


def test_copy_all_kinds(scope_store):
    set_role_scope(ROLE_LABORAL, KIND_PLANIFICACION, SCOPE_JEFES, [4])
    set_role_scope(ROLE_LABORAL, KIND_AUDITORIA, SCOPE_ALL, [])
    set_role_scope(ROLE_LABORAL, KIND_SOLICITUDES, SCOPE_ALL, [])
    set_role_scope(ROLE_LABORAL, KIND_VALORACIONES, SCOPE_JEFE, [])
    copy_role_panel_scopes(ROLE_LABORAL, 'nuevo')
    assert get_role_scope('nuevo', KIND_PLANIFICACION)['jefe_ids'] == [4]
    assert get_role_scope('nuevo', KIND_AUDITORIA)['mode'] == SCOPE_ALL
    assert get_role_scope('nuevo', KIND_VALORACIONES)['mode'] == SCOPE_JEFE


def test_parse_all_scopes_from_form():
    class FakeForm(dict):
        def getlist(self, key):
            val = self.get(key, [])
            if isinstance(val, list):
                return val
            return [val]

    form = FakeForm({
        'scope__planificacion__mode': 'jefes',
        'scope__planificacion__jefe_ids': ['3', '1'],
        'scope__auditoria_fichajes__mode': 'all',
        'scope__solicitudes__mode': 'none',
        'scope__valoraciones__mode': 'jefe',
    })
    parsed = parse_all_scopes_from_form(form)
    assert parsed[KIND_PLANIFICACION][0] == SCOPE_JEFES
    assert parsed[KIND_PLANIFICACION][1] == [3, 1]
    assert parsed[KIND_AUDITORIA][0] == SCOPE_ALL
    assert parsed[KIND_SOLICITUDES][0] == SCOPE_NONE
    assert parsed[KIND_VALORACIONES][0] == SCOPE_JEFE


def test_clear_role_panel_scopes(scope_store, monkeypatch):
    set_role_obra_scope('tmp_rol', SCOPE_ALL, [])

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

    import app.models as models_mod
    monkeypatch.setattr(models_mod, 'ConfiguracionGlobal', FakeModel)
    monkeypatch.setattr('app.db.session', FakeSession())

    clear_role_panel_scopes('tmp_rol')
    assert get_role_obra_scope('tmp_rol')['mode'] == SCOPE_NONE
