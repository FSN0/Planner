"""Permiso «Entrar como otro usuario»."""
from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL
from app.services.permission_catalog import (
    BINARY_TICK_MODULES,
    MODULE_READ_HINTS,
    default_actions,
    normalize_module,
)


def test_entrar_como_module_is_binary_tick():
    assert 'entrar_como' in BINARY_TICK_MODULES
    assert normalize_module('entrar_como') == 'entrar_como'
    assert MODULE_READ_HINTS.get('entrar_como')


def test_entrar_como_defaults_admin_only():
    assert 'r' in default_actions(ROLE_ADMIN, 'entrar_como')
    assert 'w' in default_actions(ROLE_ADMIN, 'entrar_como')
    assert not default_actions(ROLE_JEFE, 'entrar_como')
    assert not default_actions(ROLE_LABORAL, 'entrar_como')
