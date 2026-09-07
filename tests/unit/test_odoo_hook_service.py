import pytest

from app.services.odoo_hook_service import (
    HOOK_MODO,
    OdooHookError,
    extract_provided_key,
    keys_match,
    parse_hook_payload,
    resolve_resource,
    run_hook_resource,
)


def test_resolve_resource_known_models():
    assert resolve_resource({'model': 'res.partner'}) == 'subcontratas'
    assert resolve_resource({'model': 'hr.employee'}) == 'empleados'
    assert resolve_resource({'model': 'bim.project'}) == 'obras'
    assert resolve_resource({'model': 'hr.leave'}) == 'ausencias'
    assert resolve_resource({'model': 'hr.attendance'}) == 'fichajes'
    assert resolve_resource({'model': 'fleet.vehicle'}) == 'vehiculos'
    assert resolve_resource({'model': 'fleet.vehicle.odometer'}) == 'vehiculos'
    assert resolve_resource({'model': 'fleet.vehicle.model'}) == 'vehiculos'


def test_resolve_resource_aliases():
    assert resolve_resource({'resource': 'contactos'}) == 'subcontratas'
    assert resolve_resource({'module': 'employees'}) == 'empleados'
    assert resolve_resource({'model': 'mail.message'}) is None


def test_parse_payload_create_partner():
    parsed = parse_hook_payload({
        'event_id': 'abc',
        'action': 'create',
        'model': 'res.partner',
        'id': 12345,
        'parent_id': 998,
        'write_date': '2026-09-07T09:00:00+02:00',
    })
    assert parsed['ignored'] is False
    assert parsed['resource'] == 'subcontratas'
    assert parsed['odoo_id'] == 12345
    assert parsed['parent_id'] == 998
    assert parsed['action'] == 'create'


def test_parse_payload_refresh_without_id():
    parsed = parse_hook_payload({'model': 'hr.employee', 'action': 'refresh'})
    assert parsed['odoo_id'] is None
    assert parsed['action'] == 'refresh'
    assert parsed['resource'] == 'empleados'


def test_parse_payload_missing_id_is_422():
    with pytest.raises(OdooHookError) as err:
        parse_hook_payload({'model': 'hr.employee', 'action': 'write'})
    assert err.value.status == 422
    assert err.value.code == 'missing_id'


def test_parse_payload_unknown_model_is_ignored():
    parsed = parse_hook_payload({'model': 'mail.mail', 'id': 1, 'action': 'write'})
    assert parsed['ignored'] is True
    assert parsed['resource'] is None


def test_parse_payload_bad_id():
    with pytest.raises(OdooHookError) as err:
        parse_hook_payload({'model': 'bim.project', 'id': 'abc'})
    assert err.value.code == 'bad_id'


def test_keys_match_and_extract():
    secret = 'hook-secret-value-aaaaaaaa'
    assert keys_match(secret, secret) is True
    assert keys_match('nope', secret) is False
    assert keys_match('', secret) is False
    headers = {'X-Odoo-Sync-Key': secret}
    assert extract_provided_key(headers) == secret
    assert extract_provided_key({'Authorization': f'Bearer {secret}'}) == secret


def test_run_hook_resource_reuses_empleados_runner(
    session, tenant_soltec, app, mocker,
):
    from flask import g
    from sqlalchemy import text

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    runner = mocker.patch('app.services.sync_runner_service.run_auto_sync_empleados')
    with app.app_context():
        g.current_tenant = tenant_soltec
        result = run_hook_resource(
            'empleados',
            meta={'model': 'hr.employee', 'odoo_id': 9, 'action': 'write'},
        )
    assert result['ok'] is True
    runner.assert_called_once_with(modo=HOOK_MODO)


def test_run_hook_resource_fichajes_uses_existing_processor(
    session, tenant_soltec, app, mocker,
):
    from flask import g
    from sqlalchemy import text

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    proc = mocker.patch('app.services.sync_service.procesar_fichajes_diarios')
    mocker.patch(
        'app.services.sync_config_service.SyncConfigService.mark_fichajes_sync_done',
    )
    with app.app_context():
        g.current_tenant = tenant_soltec
        result = run_hook_resource(
            'fichajes',
            meta={'model': 'hr.attendance', 'odoo_id': 4, 'action': 'create'},
        )
    assert result['ok'] is True
    proc.assert_called_once_with()
