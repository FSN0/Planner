"""POST /api/v6/odoo/hooks/changed: Odoo avisa, SignaPlan no recibe la ficha."""
import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified

HOOK_KEY = 'test-odoo-hook-key-aaaaaaaaaaaaaaaa'
PATH = '/api/v6/odoo/hooks/changed'


def _enable_odoo(session, tenant):
    mods = dict(tenant.modulos_activos or {})
    mods['odoo'] = True
    tenant.modulos_activos = mods
    flag_modified(tenant, 'modulos_activos')
    session.add(tenant)
    session.commit()


def _set_hook_key(app, session, tenant, key=HOOK_KEY):
    from flask import g
    from app.services.config_service import set_tenant_config

    with app.test_request_context('/', base_url='http://soltec.localhost:5000'):
        g.current_tenant = tenant
        session.execute(text(f'SET search_path TO {tenant.schema_name}, public'))
        set_tenant_config('odoo_sync_hook_key', key, encriptar=True)


def _payload(**overrides):
    data = {
        'event_id': '00000000-0000-0000-0000-000000000001',
        'action': 'create',
        'model': 'res.partner',
        'id': 12345,
        'write_date': '2026-09-07T09:00:00+02:00',
        'parent_id': 998,
    }
    data.update(overrides)
    return data


def test_hook_without_tenant_is_404(client):
    response = client.post(
        PATH,
        json=_payload(),
        headers={'X-Odoo-Sync-Key': HOOK_KEY},
    )
    assert response.status_code == 404
    body = json.loads(response.data)
    assert body['code'] == 'no_tenant'


def test_hook_without_odoo_module_is_403(tenant_client, tenant_soltec):
    response = tenant_client.post(
        PATH,
        json=_payload(),
        headers={'X-Odoo-Sync-Key': HOOK_KEY},
    )
    assert response.status_code == 403
    body = json.loads(response.data)
    assert body['code'] == 'no_module'


def test_hook_wrong_key_is_401(app, session, tenant_soltec, tenant_client):
    _enable_odoo(session, tenant_soltec)
    _set_hook_key(app, session, tenant_soltec)
    response = tenant_client.post(
        PATH,
        json=_payload(),
        headers={'X-Odoo-Sync-Key': 'clave-incorrecta'},
    )
    assert response.status_code == 401
    body = json.loads(response.data)
    assert body['code'] == 'unauthorized'


def test_hook_accepts_and_schedules(
    app, session, tenant_soltec, tenant_client, mocker,
):
    _enable_odoo(session, tenant_soltec)
    _set_hook_key(app, session, tenant_soltec)
    scheduled = mocker.patch(
        'app.services.odoo_hook_service.schedule_resource_sync',
        return_value='scheduled',
    )
    response = tenant_client.post(
        PATH,
        json=_payload(),
        headers={'X-Odoo-Sync-Key': HOOK_KEY},
    )
    assert response.status_code == 202
    body = json.loads(response.data)
    assert body['accepted'] is True
    assert body['ignored'] is False
    assert body['resource'] == 'subcontratas'
    assert body['id'] == 12345
    scheduled.assert_called_once()
    assert scheduled.call_args[0][0] == 'subcontratas'


def test_hook_unknown_model_is_202_ignored(
    app, session, tenant_soltec, tenant_client, mocker,
):
    _enable_odoo(session, tenant_soltec)
    _set_hook_key(app, session, tenant_soltec)
    scheduled = mocker.patch(
        'app.services.odoo_hook_service.schedule_resource_sync',
        return_value='scheduled',
    )
    response = tenant_client.post(
        PATH,
        json=_payload(model='mail.mail', id=7),
        headers={'X-Odoo-Sync-Key': HOOK_KEY},
    )
    assert response.status_code == 202
    body = json.loads(response.data)
    assert body['ignored'] is True
    scheduled.assert_not_called()


def test_hook_missing_id_is_422(app, session, tenant_soltec, tenant_client):
    _enable_odoo(session, tenant_soltec)
    _set_hook_key(app, session, tenant_soltec)
    response = tenant_client.post(
        PATH,
        json={'model': 'hr.employee', 'action': 'write'},
        headers={'X-Odoo-Sync-Key': HOOK_KEY},
    )
    assert response.status_code == 422
    body = json.loads(response.data)
    assert body['code'] == 'missing_id'


def test_hook_bearer_and_employee_model(
    app, session, tenant_soltec, tenant_client, mocker,
):
    _enable_odoo(session, tenant_soltec)
    _set_hook_key(app, session, tenant_soltec)
    scheduled = mocker.patch(
        'app.services.odoo_hook_service.schedule_resource_sync',
        return_value='scheduled',
    )
    response = tenant_client.post(
        PATH,
        json=_payload(model='hr.employee', id=88, action='write'),
        headers={'Authorization': f'Bearer {HOOK_KEY}'},
    )
    assert response.status_code == 202
    body = json.loads(response.data)
    assert body['resource'] == 'empleados'
    scheduled.assert_called_once()


@pytest.mark.parametrize('model,resource', [
    ('res.partner', 'subcontratas'),
    ('hr.employee', 'empleados'),
    ('bim.project', 'obras'),
    ('hr.leave', 'ausencias'),
    ('hr.attendance', 'fichajes'),
    ('fleet.vehicle', 'vehiculos'),
    ('fleet.vehicle.odometer', 'vehiculos'),
])
def test_hook_maps_every_integrated_model(
    app, session, tenant_soltec, tenant_client, mocker, model, resource,
):
    _enable_odoo(session, tenant_soltec)
    _set_hook_key(app, session, tenant_soltec)
    scheduled = mocker.patch(
        'app.services.odoo_hook_service.schedule_resource_sync',
        return_value='scheduled',
    )
    response = tenant_client.post(
        PATH,
        json=_payload(model=model, id=42, action='write'),
        headers={'X-Odoo-Sync-Key': HOOK_KEY},
    )
    assert response.status_code == 202
    body = json.loads(response.data)
    assert body['resource'] == resource
    assert scheduled.call_args[0][0] == resource


def test_hook_accepts_sso_secret_via_alta_key(
    app, session, tenant_soltec, tenant_client, mocker,
):
    """Altas puede avisar con SSO_SECRET_KEY aunque la clave del panel sea otra."""
    _enable_odoo(session, tenant_soltec)
    _set_hook_key(app, session, tenant_soltec)
    app.config['SSO_SECRET_KEY'] = 'sso-alta-shared-secret'
    scheduled = mocker.patch(
        'app.services.odoo_hook_service.schedule_resource_sync',
        return_value='scheduled',
    )
    response = tenant_client.post(
        PATH,
        json=_payload(),
        headers={'X-Odoo-Alta-Key': 'sso-alta-shared-secret'},
    )
    assert response.status_code == 202
    body = json.loads(response.data)
    assert body['accepted'] is True
    assert body['resource'] == 'subcontratas'
    scheduled.assert_called_once()


def test_odoo_dashboard_shows_hook_brief(
    app, session, tenant_soltec, authenticated_client,
):
    _enable_odoo(session, tenant_soltec)
    _set_hook_key(app, session, tenant_soltec)
    response = authenticated_client.get('/sync/odoo')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert '/api/v6/odoo/hooks/changed' in html
    assert 'X-Odoo-Sync-Key' in html
    assert HOOK_KEY in html
    assert 'res.partner' in html
    assert 'hr.employee' in html
    assert 'bim.project' in html
    assert 'hr.leave' in html
    assert 'hr.attendance' in html
    assert 'fleet.vehicle' in html
