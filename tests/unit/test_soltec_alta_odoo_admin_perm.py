"""Permiso Alta Odoo · entrar como admin."""
from app.services.permission_catalog import (
    BINARY_TICK_MODULES,
    MODULE_READ_HINTS,
    default_actions,
    normalize_module,
)
from app.models import ROLE_ADMIN, ROLE_JEFE


def test_alta_admin_module_is_binary_tick():
    assert 'soltec_alta_odoo_admin' in BINARY_TICK_MODULES
    assert normalize_module('soltec_alta_odoo_admin') == 'soltec_alta_odoo_admin'
    assert MODULE_READ_HINTS.get('soltec_alta_odoo_admin')


def test_alta_admin_defaults_admin_only():
    assert 'r' in default_actions(ROLE_ADMIN, 'soltec_alta_odoo_admin')
    assert 'w' in default_actions(ROLE_ADMIN, 'soltec_alta_odoo_admin')
    assert not default_actions(ROLE_JEFE, 'soltec_alta_odoo_admin')
