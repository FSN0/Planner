import json

from app.services.external_auth_providers.base import ExternalAuthDecision
from app.services.external_auth_providers.odoo_soltec import OdooSoltecProvider


def _provider():
    provider = OdooSoltecProvider.__new__(OdooSoltecProvider)
    provider.provider_name = 'odoo_soltec'
    provider.base_url = 'https://odoo.example.com'
    provider.timeout = 12.0
    return provider


def test_odoo_provider_accepts_dict_success():
    provider = _provider()
    res = provider._parse_success_payload(json.dumps({'result': {'success': True}}), 200)
    assert res.decision == ExternalAuthDecision.VALID


def test_odoo_provider_accepts_scalar_false():
    provider = _provider()
    res = provider._parse_success_payload(json.dumps({'result': False}), 200)
    assert res.decision == ExternalAuthDecision.INVALID


def test_odoo_provider_marks_missing_endpoint_unavailable():
    provider = _provider()
    res = provider._parse_success_payload(
        json.dumps({'error': {'message': 'Route does not exist: /portal/soltec/login'}}),
        200,
    )
    assert res.decision == ExternalAuthDecision.UNAVAILABLE
    assert res.reason == 'endpoint_missing'
