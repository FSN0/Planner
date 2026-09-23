"""Modos de asignación: gente y vehículos independientes."""
from types import SimpleNamespace

from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL
from app.services.assign_mode_service import (
    ASSIGN_MODE_DIRECT,
    ASSIGN_MODE_SOLICITUD,
    KIND_PEOPLE,
    KIND_VEHICLES,
    default_assign_mode_for_role,
    get_role_assign_mode,
    parse_assign_mode_from_form,
    set_role_assign_mode,
    user_assigns_direct,
    user_assigns_vehicles_direct,
    user_assigns_vehicles_via_solicitud,
    user_assigns_via_solicitud,
)


def test_people_and_vehicles_modes_independent(monkeypatch):
    store = {'assign_mode._migrated_v2': '1'}

    def fake_get(key, default=None):
        return store.get(key, default)

    def fake_set(key, value, **_kwargs):
        store[key] = value

    monkeypatch.setattr(
        'app.services.assign_mode_service.get_tenant_config', fake_get
    )
    monkeypatch.setattr(
        'app.services.assign_mode_service.set_tenant_config', fake_set
    )

    set_role_assign_mode(ROLE_JEFE, ASSIGN_MODE_DIRECT, KIND_PEOPLE)
    set_role_assign_mode(ROLE_JEFE, ASSIGN_MODE_SOLICITUD, KIND_VEHICLES)
    assert get_role_assign_mode(ROLE_JEFE, KIND_PEOPLE) == ASSIGN_MODE_DIRECT
    assert get_role_assign_mode(ROLE_JEFE, KIND_VEHICLES) == ASSIGN_MODE_SOLICITUD


def test_user_assigns_requires_module_write(monkeypatch):
    user = SimpleNamespace(role=ROLE_JEFE, is_authenticated=True)
    monkeypatch.setattr(
        'app.services.assign_mode_service.get_role_assign_mode',
        lambda role, kind=KIND_PEOPLE: ASSIGN_MODE_DIRECT,
    )
    monkeypatch.setattr(
        'app.services.permission_service.can_write_assignments',
        lambda u: False,
    )
    monkeypatch.setattr(
        'app.services.permission_service.can_plan_fleet',
        lambda u: True,
    )
    assert user_assigns_direct(user) is False
    assert user_assigns_vehicles_direct(user) is True
    assert user_assigns_vehicles_via_solicitud(user) is False


def test_user_assigns_vehicles_uses_planificar_flota(monkeypatch):
    user = SimpleNamespace(role=ROLE_JEFE, is_authenticated=True)
    monkeypatch.setattr(
        'app.services.assign_mode_service.user_assign_mode',
        lambda u, kind=KIND_PEOPLE: ASSIGN_MODE_DIRECT,
    )
    monkeypatch.setattr(
        'app.services.permission_service.can_plan_fleet',
        lambda u: True,
    )
    monkeypatch.setattr(
        'app.services.permission_service.can_write_vehicles',
        lambda u: False,
    )
    assert user_assigns_vehicles_direct(user) is True


def test_parse_form_dual_modes():
    class Form(dict):
        pass

    form = Form({
        'assign_mode_people': ASSIGN_MODE_SOLICITUD,
        'assign_mode_vehicles': ASSIGN_MODE_DIRECT,
    })
    assert parse_assign_mode_from_form(form, ROLE_JEFE, KIND_PEOPLE) == ASSIGN_MODE_SOLICITUD
    assert parse_assign_mode_from_form(form, ROLE_JEFE, KIND_VEHICLES) == ASSIGN_MODE_DIRECT


def test_admin_always_direct(monkeypatch):
    store = {'assign_mode._migrated_v2': '1'}
    monkeypatch.setattr(
        'app.services.assign_mode_service.get_tenant_config',
        lambda k, default=None: store.get(k, default),
    )
    monkeypatch.setattr(
        'app.services.assign_mode_service.set_tenant_config',
        lambda k, v, **kw: store.__setitem__(k, v),
    )
    set_role_assign_mode(ROLE_ADMIN, ASSIGN_MODE_SOLICITUD, KIND_PEOPLE)
    assert get_role_assign_mode(ROLE_ADMIN, KIND_PEOPLE) == ASSIGN_MODE_DIRECT
    assert default_assign_mode_for_role(ROLE_ADMIN) == ASSIGN_MODE_DIRECT


def test_people_via_solicitud_needs_write(monkeypatch):
    user = SimpleNamespace(role=ROLE_JEFE, is_authenticated=True)
    monkeypatch.setattr(
        'app.services.assign_mode_service.user_assign_mode',
        lambda u, kind=KIND_PEOPLE: ASSIGN_MODE_SOLICITUD,
    )
    monkeypatch.setattr(
        'app.services.permission_service.can_write_assignments',
        lambda u: True,
    )
    assert user_assigns_via_solicitud(user) is True
    assert user_assigns_direct(user) is False
