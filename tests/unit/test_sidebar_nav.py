from types import SimpleNamespace
from unittest.mock import patch

from app.models import ROLE_ADMIN, ROLE_JEFE
from app.services.sidebar_nav_service import (
    ITEM_INTEGRACIONES,
    ITEM_SOLICITUDES,
    item_is_available,
)


@patch('app.services.sidebar_nav_service.user_can')
def test_solicitudes_visible_if_personal_or_flota_r(can):
    admin = SimpleNamespace(role=ROLE_ADMIN)
    jefe = SimpleNamespace(role=ROLE_JEFE)

    can.side_effect = lambda u, m, a='r': m == 'solicitudes'
    assert item_is_available(ITEM_SOLICITUDES, admin, {}) is True
    assert item_is_available(ITEM_SOLICITUDES, jefe, {}) is True

    can.side_effect = lambda u, m, a='r': m == 'solicitudes_vehiculos'
    assert item_is_available(ITEM_SOLICITUDES, jefe, {}) is True

    can.side_effect = lambda u, m, a='r': False
    assert item_is_available(ITEM_SOLICITUDES, jefe, {}) is False


@patch('app.services.sidebar_nav_service.user_can')
def test_integraciones_not_top_level_if_user_has_config(can):
    can.side_effect = lambda user, module, action='r': True
    admin = SimpleNamespace(role=ROLE_ADMIN)
    assert item_is_available(ITEM_INTEGRACIONES, admin, {}) is False


@patch('app.services.sidebar_nav_service.user_can')
def test_integraciones_top_level_if_no_config_permission(can):
    can.side_effect = lambda user, module, action='r': module == 'integraciones'
    jefe = SimpleNamespace(role=ROLE_JEFE)
    assert item_is_available(ITEM_INTEGRACIONES, jefe, {}) is True


@patch('app.services.sidebar_nav_service.user_can')
def test_jefe_can_see_own_calendar_with_portal_permission(can):
    can.side_effect = lambda user, module, action='r': module in (
        'operario_calendario', 'trabajadores',
    )
    jefe = SimpleNamespace(role=ROLE_JEFE)
    from app.services.sidebar_nav_service import ITEM_TRABAJADORES
    assert item_is_available(ITEM_TRABAJADORES, jefe, {}) is True
