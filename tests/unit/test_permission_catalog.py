"""Defaults y helpers de la matriz de permisos por rol."""
from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_OPERARIO, ROLE_RRHH
from app.services.permission_catalog import (
    ADMIN_LOCKED_MODULES,
    default_actions,
    default_matrix_rows,
    module_keys,
    normalize_module,
)


def test_admin_locked_modules():
    assert 'configuracion' in ADMIN_LOCKED_MODULES
    assert 'permisos' in ADMIN_LOCKED_MODULES


def test_admin_has_all_modules_rwx():
    for module in module_keys():
        assert default_actions(ROLE_ADMIN, module) == frozenset('rwx')


def test_operario_web_on_by_default_with_web_access_gate():
    assert 'r' in default_actions(ROLE_OPERARIO, 'operario_web')
    assert 'r' in default_actions(ROLE_OPERARIO, 'operario_calendario')
    assert 'x' in default_actions(ROLE_OPERARIO, 'operario_fichaje')


def test_laboral_and_rrhh_share_core_acl():
    for role in (ROLE_LABORAL, ROLE_RRHH):
        assert 'x' in default_actions(role, 'ausencias')
        assert 'r' in default_actions(role, 'tablero')
        assert not default_actions(role, 'configuracion')


def test_jefe_keeps_tablero_and_directorio():
    assert 'w' in default_actions(ROLE_JEFE, 'tablero')
    assert 'r' in default_actions(ROLE_JEFE, 'directorio')
    assert not default_actions(ROLE_JEFE, 'permisos')


def test_legacy_aliases():
    assert normalize_module('worker_panel') == 'trabajadores'
    assert normalize_module('obra_panel') == 'tablero'


def test_default_matrix_rows_cover_all_roles_modules():
    rows = default_matrix_rows()
    assert len(rows) == 5 * len(module_keys())
    assert all('role' in r and 'module' in r for r in rows)
