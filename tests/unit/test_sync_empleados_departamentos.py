from app.services.sync_config_service import (
    _normalize_import_role,
    parse_empleados_departamento_map,
    resolve_departamento_role,
)


def test_normalize_acepta_admin_y_alias():
    assert _normalize_import_role('admin') == 'admin'
    assert _normalize_import_role('Administrador') == 'admin'
    assert _normalize_import_role('administración') == 'admin'


def test_parse_mapa_con_admin():
    rows = parse_empleados_departamento_map(
        [{'department': 'Dirección', 'role': 'admin'}],
        use_defaults_if_empty=False,
    )
    assert rows == [{'department': 'Dirección', 'role': 'admin'}]
    assert resolve_departamento_role('Dirección general', rows) == 'admin'
