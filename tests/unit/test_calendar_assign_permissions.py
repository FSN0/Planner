"""Calendarios: ver vs asignar (matriz de permisos, sin listas de roles)."""
from types import SimpleNamespace

from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL
from app.services.permission_catalog import default_actions
from app.services.permission_service import (
    can_edit_planning_calendar,
    can_view_obra_calendar,
    can_view_worker_calendar,
    can_write_assignments,
)


def test_can_write_assignments_prefers_asignaciones_module(monkeypatch):
    user = SimpleNamespace(is_authenticated=True, role=ROLE_LABORAL)

    def fake_can(u, module, action):
        if module == 'asignaciones' and action == 'w':
            return True
        return False

    monkeypatch.setattr(
        'app.services.permission_service.user_can', fake_can
    )
    assert can_write_assignments(user) is True
    assert can_edit_planning_calendar(user) is True


def test_can_write_assignments_falls_back_to_planificador(monkeypatch):
    user = SimpleNamespace(is_authenticated=True, role=ROLE_JEFE)

    def fake_can(u, module, action):
        return module == 'planificador' and action == 'w'

    monkeypatch.setattr(
        'app.services.permission_service.user_can', fake_can
    )
    assert can_write_assignments(user) is True


def test_laboral_default_cannot_edit_planning_calendar():
    assert 'w' not in default_actions(ROLE_LABORAL, 'asignaciones')
    assert 'w' not in default_actions(ROLE_LABORAL, 'planificador')
    assert 'w' not in default_actions(ROLE_LABORAL, 'tablero')


def test_admin_and_jefe_defaults_can_assign():
    assert 'w' in default_actions(ROLE_ADMIN, 'asignaciones')
    assert 'w' in default_actions(ROLE_JEFE, 'asignaciones')


def test_can_view_worker_calendar_matrix(monkeypatch):
    user = SimpleNamespace(is_authenticated=True, role='director_rrhh', id=1)

    def fake_can(u, module, action):
        return module == 'trabajadores' and action == 'r'

    monkeypatch.setattr('app.services.permission_service.user_can', fake_can)
    assert can_view_worker_calendar(user, 99) is True


def test_can_view_worker_calendar_denied_without_perm(monkeypatch):
    user = SimpleNamespace(is_authenticated=True, role='director_rrhh', id=1)
    monkeypatch.setattr(
        'app.services.permission_service.user_can',
        lambda *a, **k: False,
    )
    assert can_view_worker_calendar(user, 99) is False


def test_can_view_obra_calendar_tablero(monkeypatch):
    user = SimpleNamespace(is_authenticated=True, role='custom')
    monkeypatch.setattr(
        'app.services.permission_service.user_can',
        lambda u, m, a: m == 'tablero' and a == 'r',
    )
    assert can_view_obra_calendar(user) is True


def _flask_app():
    from flask import Flask
    app = Flask(__name__)
    app.secret_key = "test-calendar-assign-permissions"
    return app


def test_autorizar_calendario_custom_role_con_trabajadores(monkeypatch):
    from app.api import routes as api_routes

    user = SimpleNamespace(is_authenticated=True, role='director_rrhh', id=3)
    monkeypatch.setattr(api_routes, 'current_user', user)
    monkeypatch.setattr(
        api_routes,
        'can_view_worker_calendar',
        lambda u, wid=None: True,
    )
    with _flask_app().test_request_context('/'):
        assert api_routes._autorizar_calendario('worker', 999) is None


def test_autorizar_calendario_sin_trabajadores_denied(monkeypatch):
    from app.api import routes as api_routes

    user = SimpleNamespace(is_authenticated=True, role='director_rrhh', id=3)
    monkeypatch.setattr(api_routes, 'current_user', user)
    monkeypatch.setattr(
        api_routes,
        'can_view_worker_calendar',
        lambda u, wid=None: False,
    )
    with _flask_app().test_request_context('/'):
        denied = api_routes._autorizar_calendario('worker', 999)
        assert denied is not None
        assert denied[1] == 403


def test_autorizar_calendario_obra_con_tablero(monkeypatch):
    from app.api import routes as api_routes

    user = SimpleNamespace(is_authenticated=True, role='custom', id=3)
    obra = SimpleNamespace(id=55, jefe_obra_id=99)
    monkeypatch.setattr(api_routes, 'current_user', user)
    monkeypatch.setattr(api_routes, 'can_view_obra_calendar', lambda u: True)
    monkeypatch.setattr(
        api_routes,
        'Obra',
        SimpleNamespace(query=SimpleNamespace(get=lambda _id: obra)),
    )
    with _flask_app().test_request_context('/'):
        assert api_routes._autorizar_calendario('obra', 55) is None


def test_autorizar_calendario_obra_sin_tablero_denied(monkeypatch):
    from app.api import routes as api_routes

    user = SimpleNamespace(is_authenticated=True, role=ROLE_JEFE, id=7)
    monkeypatch.setattr(api_routes, 'current_user', user)
    monkeypatch.setattr(api_routes, 'can_view_obra_calendar', lambda u: False)
    with _flask_app().test_request_context('/'):
        denied = api_routes._autorizar_calendario('obra', 55)
        assert denied is not None
        assert denied[1] == 403
