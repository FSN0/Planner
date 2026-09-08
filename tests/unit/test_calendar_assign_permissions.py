"""Calendarios: ver vs asignar (jefe / asignaciones)."""
from types import SimpleNamespace

from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL
from app.services.permission_catalog import default_actions
from app.services.permission_service import (
    can_edit_planning_calendar,
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


def _flask_app():
    """Request context only — avoid session app fixture (DB / SECRET_KEY)."""
    from flask import Flask
    app = Flask(__name__)
    app.secret_key = "test-calendar-assign-permissions"
    return app


def test_autorizar_calendario_jefe_worker_always_ok(monkeypatch):
    from app.api import routes as api_routes

    jefe = SimpleNamespace(
        is_authenticated=True,
        role=ROLE_JEFE,
        id=7,
    )
    monkeypatch.setattr(api_routes, 'current_user', jefe)
    with _flask_app().test_request_context('/'):
        assert api_routes._autorizar_calendario('worker', 999999) is None


def test_autorizar_calendario_jefe_obra_ajena_denied(monkeypatch):
    from app.api import routes as api_routes

    jefe = SimpleNamespace(
        is_authenticated=True,
        role=ROLE_JEFE,
        id=7,
    )
    obra = SimpleNamespace(id=55, jefe_obra_id=99)
    monkeypatch.setattr(api_routes, 'current_user', jefe)
    monkeypatch.setattr(
        api_routes,
        'Obra',
        SimpleNamespace(query=SimpleNamespace(get=lambda _id: obra)),
    )
    with _flask_app().test_request_context('/'):
        denied = api_routes._autorizar_calendario('obra', 55)
        assert denied is not None
        assert denied[1] == 403


def test_autorizar_calendario_jefe_obra_propia_ok(monkeypatch):
    from app.api import routes as api_routes

    jefe = SimpleNamespace(
        is_authenticated=True,
        role=ROLE_JEFE,
        id=7,
    )
    obra = SimpleNamespace(id=55, jefe_obra_id=7)
    monkeypatch.setattr(api_routes, 'current_user', jefe)
    monkeypatch.setattr(
        api_routes,
        'Obra',
        SimpleNamespace(query=SimpleNamespace(get=lambda _id: obra)),
    )
    with _flask_app().test_request_context('/'):
        assert api_routes._autorizar_calendario('obra', 55) is None
