import importlib.util
from pathlib import Path
from types import SimpleNamespace

_SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'show_odoo_creds.py'
_spec = importlib.util.spec_from_file_location('show_odoo_creds', _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
match_tenants = _mod.match_tenants


def _t(sub, schema='tenant_x', nombre='X'):
    return SimpleNamespace(subdominio=sub, schema_name=schema, nombre=nombre)


def test_match_tenants_exact_subdomain_wins():
    tenants = [_t('soltec', 'tenant_soltec', 'SOLTEC'), _t('sara', 'tenant_sara', 'Sara')]
    assert [t.subdominio for t in match_tenants(tenants, 'soltec')] == ['soltec']


def test_match_tenants_schema_name():
    tenants = [_t('soltec', 'tenant_soltec', 'SOLTEC')]
    assert [t.subdominio for t in match_tenants(tenants, 'tenant_soltec')] == ['soltec']


def test_match_tenants_partial_name_when_unique():
    tenants = [_t('soltec', 'tenant_soltec', 'SOLTEC'), _t('sara', 'tenant_sara', 'Sara')]
    assert [t.subdominio for t in match_tenants(tenants, 'sol')] == ['soltec']


def test_match_tenants_ambiguous_partial():
    tenants = [_t('fresneda', 'tenant_fresneda', 'A'), _t('fresnedaa', 'tenant_fresnedaa', 'B')]
    assert {t.subdominio for t in match_tenants(tenants, 'fres')} == {'fresneda', 'fresnedaa'}
