"""Defaults y helpers de la matriz de permisos por rol."""
from types import SimpleNamespace

from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_OPERARIO, ROLE_RRHH
from app.services.permission_catalog import (
    ADMIN_LOCKED_MODULES,
    default_actions,
    default_matrix_rows,
    module_keys,
    normalize_module,
    visible_permission_keys,
)


def test_admin_locked_modules():
    assert 'configuracion' in ADMIN_LOCKED_MODULES
    assert 'permisos' in ADMIN_LOCKED_MODULES


def test_admin_has_all_modules_rw():
    for module in module_keys():
        assert default_actions(ROLE_ADMIN, module) == frozenset('rw')


def test_operario_portal_defaults():
    assert 'r' in default_actions(ROLE_OPERARIO, 'operario_calendario')
    assert 'w' in default_actions(ROLE_OPERARIO, 'operario_fichaje')
    assert not default_actions(ROLE_OPERARIO, 'operario_web')


def test_modules_for_role_same_list_includes_portal():
    from app.services.permission_catalog import modules_for_role

    operario_keys = {m for m, _, _ in modules_for_role(ROLE_OPERARIO)}
    jefe_keys = {m for m, _, _ in modules_for_role(ROLE_JEFE)}
    # Misma base: oficina + portal propio (calendario/ausencias siempre; fichar si módulo)
    assert 'tablero' in operario_keys
    assert 'operario_calendario' in operario_keys
    assert 'operario_ausencias' in operario_keys
    assert 'tablero' in jefe_keys
    assert 'operario_calendario' in jefe_keys
    assert 'operario_ausencias' in jefe_keys


def test_laboral_and_rrhh_share_core_acl():
    for role in (ROLE_LABORAL, ROLE_RRHH):
        assert 'w' in default_actions(role, 'ausencias')
        assert 'r' in default_actions(role, 'tablero')
        assert not default_actions(role, 'configuracion')


def test_jefe_keeps_tablero_and_directorio():
    assert 'w' in default_actions(ROLE_JEFE, 'tablero')
    assert 'r' in default_actions(ROLE_JEFE, 'directorio')
    assert not default_actions(ROLE_JEFE, 'permisos')


def test_jefe_soltec_shortcuts_without_integraciones_hub():
    assert not default_actions(ROLE_JEFE, 'integraciones')
    assert not default_actions(ROLE_JEFE, 'sync_odoo')
    assert 'r' in default_actions(ROLE_JEFE, 'soltec_alta_odoo')
    assert 'r' in default_actions(ROLE_JEFE, 'soltec_portal')


def test_timeline_dia_uses_auditoria_not_integraciones():
    from app.services.permission_guard import _SYNC_RULES, _match_rule

    matched = _match_rule(_SYNC_RULES, '/sync/timeline_dia/12/2026-08-10', 'GET')
    assert matched == ('auditoria_fichajes', 'r')


def test_integration_modules_in_catalog():
    keys = set(module_keys())
    assert 'integraciones' in keys
    assert 'sync_odoo' in keys
    assert 'soltec_alta_odoo' in keys
    assert 'soltec_portal' in keys


def test_normalize_legacy_aliases():
    assert normalize_module('worker_panel') == 'trabajadores'
    assert normalize_module('vehicle_panel') == 'vehiculos'


def test_default_matrix_rows_cover_all_roles_and_modules():
    rows = default_matrix_rows()
    assert len(rows) == len(module_keys()) * 5


def _keys_for(monkeypatch, sub, mods, jefes_directo):
    monkeypatch.setattr(
        'app.services.tenant_modules.jefes_asignan_directo',
        lambda: jefes_directo,
    )
    tenant = SimpleNamespace(subdominio=sub, modulos_activos=mods)
    return set(visible_permission_keys(tenant))


def test_portal_calendar_visible_without_fichaje_module(monkeypatch):
    keys = _keys_for(
        monkeypatch, 'lopez',
        {
            'fichaje_operario': False,
            'registro_jornada': True,
            'onboarding': False,
            'notas': False,
            'auditoria_vehiculos': False,
        },
        jefes_directo=True,
    )
    assert 'operario_calendario' in keys
    assert 'operario_ausencias' in keys
    assert 'operario_fichaje' not in keys


def test_generic_selfserve_hides_soltec_and_odoo_rows(monkeypatch):
    keys = _keys_for(
        monkeypatch, 'lopez',
        {
            'fichaje_operario': True,
            'registro_jornada': True,
            'onboarding': True,
            'notas': False,
            'auditoria_vehiculos': False,
        },
        jefes_directo=True,
    )
    assert 'tablero' in keys
    assert 'trabajadores' in keys
    assert 'operario_calendario' in keys
    assert 'operario_ausencias' in keys
    assert 'operario_fichaje' in keys
    assert 'auditoria_fichajes' in keys
    assert 'registro_jornada' in keys
    assert 'primeros_pasos' in keys
    assert 'solicitudes' in keys
    for extra in (
        'soltec_portal', 'soltec_alta_odoo', 'sync_odoo', 'integraciones',
        'reuniones', 'auditoria_vehiculos',
    ):
        assert extra not in keys


def test_soltec_with_odoo_shows_custom_rows(monkeypatch):
    keys = _keys_for(
        monkeypatch, 'soltec',
        {
            'odoo': True,
            'odoo_alta': True,
            'fichaje_operario': True,
            'notas': True,
            'auditoria_vehiculos': True,
            'onboarding': False,
        },
        jefes_directo=False,
    )
    assert 'soltec_portal' in keys
    assert 'soltec_alta_odoo' in keys
    assert 'sync_odoo' in keys
    assert 'integraciones' in keys
    assert 'reuniones' in keys
    assert 'auditoria_vehiculos' in keys
    assert 'solicitudes' in keys
    assert 'primeros_pasos' not in keys


def test_odoo_client_that_is_not_soltec_does_not_see_portal(monkeypatch):
    keys = _keys_for(
        monkeypatch, 'otra',
        {'odoo': True, 'odoo_alta': False},
        jefes_directo=True,
    )
    assert 'sync_odoo' in keys
    assert 'integraciones' in keys
    assert 'soltec_portal' not in keys
    assert 'soltec_alta_odoo' not in keys
