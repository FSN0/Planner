from types import SimpleNamespace
from unittest.mock import patch

from app.models import ROLE_ADMIN, ROLE_JEFE
from app.services.sidebar_nav_service import (
    ITEM_INTEGRACIONES,
    ITEM_SOLICITUDES,
    item_is_available,
)


@patch('app.services.sidebar_nav_service.user_can', return_value=True)
def test_solicitudes_hidden_only_for_jefe_when_asignan_direct(_can):
    admin = SimpleNamespace(role=ROLE_ADMIN)
    jefe = SimpleNamespace(role=ROLE_JEFE)
    on = {'jefes_asignan_directo': True}
    off = {'jefes_asignan_directo': False}
    # Oficina sigue viendo el buzón (peticiones genéricas CUALQUIERA).
    assert item_is_available(ITEM_SOLICITUDES, admin, on) is True
    assert item_is_available(ITEM_SOLICITUDES, jefe, on) is False
    assert item_is_available(ITEM_SOLICITUDES, admin, off) is True
    assert item_is_available(ITEM_SOLICITUDES, jefe, off) is True


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
    from app.services.sidebar_nav_service import ITEM_MI_CALENDARIO, ITEM_MI_FICHAJE

    can.side_effect = lambda user, module, action='r': module == 'operario_calendario'
    jefe = SimpleNamespace(role=ROLE_JEFE)
    assert item_is_available(ITEM_MI_CALENDARIO, jefe, {}) is True
    # Sin módulo de fichaje / permiso, no ve el reloj
    assert item_is_available(
        ITEM_MI_FICHAJE, jefe, {'tenant_has_fichaje_operario': True},
    ) is False
