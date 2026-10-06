from types import SimpleNamespace
from unittest.mock import patch

from app.models import ROLE_ADMIN, ROLE_JEFE
from app.services.sidebar_nav_service import (
    ITEM_AUSENCIAS,
    ITEM_DOCUMENTACION,
    ITEM_INTEGRACIONES,
    ITEM_SOLICITUDES,
    ITEM_TRABAJADORES,
    _GROUP_ABSORBS,
    _default_sections_blueprint,
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
def test_integraciones_top_level_for_admin(can):
    can.side_effect = lambda user, module, action='r': True
    admin = SimpleNamespace(role=ROLE_ADMIN)
    assert item_is_available(ITEM_INTEGRACIONES, admin, {}) is True


@patch('app.services.sidebar_nav_service.user_can')
def test_integraciones_visible_with_odoo_child_permission(can):
    can.side_effect = lambda user, module, action='r': module == 'sync_odoo'
    jefe = SimpleNamespace(role=ROLE_JEFE)
    assert item_is_available(
        ITEM_INTEGRACIONES, jefe, {'tenant_has_odoo': True},
    ) is True


@patch('app.services.sidebar_nav_service.user_can')
def test_oficina_hides_portal_calendar_even_with_permission(can):
    can.side_effect = lambda user, module, action='r': True
    from app.services.sidebar_nav_service import ITEM_MI_CALENDARIO, ITEM_TRABAJADORES

    jefe = SimpleNamespace(role=ROLE_JEFE)
    admin = SimpleNamespace(role=ROLE_ADMIN)
    assert item_is_available(ITEM_TRABAJADORES, jefe, {}) is True
    assert item_is_available(ITEM_MI_CALENDARIO, jefe, {}) is False
    assert item_is_available(ITEM_MI_CALENDARIO, admin, {}) is False


def test_default_nav_groups_trabajadores_absorbs_ausencias():
    assert ITEM_AUSENCIAS in _GROUP_ABSORBS[ITEM_TRABAJADORES]
    sections = {s['id']: s for s in _default_sections_blueprint()}
    assert set(sections) >= {'sec_home', 'sec_plan', 'sec_gestion', 'sec_ops', 'sec_docs', 'sec_sys'}
    assert sections['sec_plan']['title']
    assert ITEM_TRABAJADORES in sections['sec_gestion']['items']
    assert ITEM_AUSENCIAS not in sections['sec_gestion']['items']
    assert ITEM_DOCUMENTACION not in sections['sec_gestion']['items']
    assert ITEM_DOCUMENTACION in sections['sec_docs']['items']
