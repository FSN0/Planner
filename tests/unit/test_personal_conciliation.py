"""Tests conciliación DNI y permisos de sync por módulo."""
from app.services.personal_conciliation_service import (
    normalize_dni,
    _looks_like_person_dni,
)
from app.services.permission_guard import _SYNC_API_RUN_MODULE, match_request_permission


def test_normalize_dni_strips_ext_and_odoo_suffixes():
    assert normalize_dni('12345678A-EXT99') == '12345678A'
    assert normalize_dni('12345678A-Odoo12') == '12345678A'
    assert normalize_dni('12345678A') == '12345678A'
    assert normalize_dni(None) == ''


def test_looks_like_person_dni_rejects_company_cif():
    assert _looks_like_person_dni('12345678A') is True
    assert _looks_like_person_dni('X1234567L') is True
    assert _looks_like_person_dni('B12345678') is False
    assert _looks_like_person_dni('EXT-99') is False
    assert _looks_like_person_dni('A1234567B') is False


def test_sync_api_run_module_map_covers_panels():
    assert _SYNC_API_RUN_MODULE['vehiculos'] == 'auditoria_vehiculos'
    assert _SYNC_API_RUN_MODULE['fichajes'] == 'auditoria_fichajes'
    assert _SYNC_API_RUN_MODULE['empleados'] == 'trabajadores'
    assert _SYNC_API_RUN_MODULE['subcontratas'] == 'subcontratas'
    assert _SYNC_API_RUN_MODULE['obras'] == 'directorio'


def test_match_request_permission_api_run_vehiculos(app):
    with app.test_request_context('/sync/api/run/vehiculos', method='POST'):
        matched = match_request_permission()
        assert matched == ('auditoria_vehiculos', 'w')
