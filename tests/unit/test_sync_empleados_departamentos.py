from app.services.sync_config_service import (
    SyncConfigService,
    _normalize_import_role,
    parse_empleados_departamento_map,
    resolve_departamento_role,
)
from app.services.sync_preview_cache_service import count_pending_actions
from app.services.sync_preview_service import analyze_empleados_preview


def test_normalize_acepta_admin_y_alias():
    assert _normalize_import_role('admin') == 'admin'
    assert _normalize_import_role('Administrador') == 'admin'
    assert _normalize_import_role('administración') == 'admin'
    assert _normalize_import_role('rol_que_no_existe') == 'operario'


def test_normalize_acepta_rol_creado_en_signaplan(app, session, tenant_soltec):
    from flask import g
    from sqlalchemy import text

    from app.models import TenantRole
    from app.services.role_registry_service import ensure_tenant_roles
    from app.services.sync_config_service import list_empleados_import_roles

    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        ensure_tenant_roles()
        session.add(TenantRole(
            key='encargado_zona',
            label='Encargado de zona',
            is_system=False,
            is_locked=False,
            sort_order=80,
        ))
        session.commit()
        assert _normalize_import_role('encargado_zona') == 'encargado_zona'
        assert _normalize_import_role('Encargado Zona') == 'encargado_zona'
        keys = [row['key'] for row in list_empleados_import_roles()]
        assert 'encargado_zona' in keys
        assert 'operario' in keys
        assert 'admin' in keys


def test_parse_mapa_con_admin():
    rows = parse_empleados_departamento_map(
        [{'department': 'Dirección', 'role': 'admin'}],
        use_defaults_if_empty=False,
    )
    assert rows == [{'department': 'Dirección', 'role': 'admin'}]
    assert resolve_departamento_role('Dirección general', rows) == 'admin'


def test_analyze_empleados_separa_omitidos_decision():
    diff = {
        'nuevos': [],
        'actualizados': [],
        'desactivados': [],
        'sin_cambios': [],
        'omitidos': [{
            'odoo_id': 165,
            'nombre': 'tecnicosoltec',
            'departamento': '',
            'motivo': 'Sin DNI en Odoo',
        }],
        'omitidos_decision': [{
            'odoo_id': 126,
            'nombre': 'ESPINOS FRANCES JOSE MARIA',
            'departamento': 'JO SOLTEC',
            'motivo': 'Departamento no autorizado: «JO SOLTEC»',
            'local_id': 9,
            'local_name': 'JOSE MARIA',
            'local_lastname': 'ESPINOS',
            'local_role': 'jefe_obra',
            'dni': '12345678A',
            'role_sugerido': 'jefe_obra',
            'tipo_aviso': 'departamento',
        }],
    }
    preview = analyze_empleados_preview(diff)
    assert preview['stats']['omitidos_odoo'] == 1
    assert preview['stats']['omitidos_decision'] == 1
    assert preview['omitidos_decision'][0]['accion'] == 'omitido_decision'
    assert 'Ya está en la app' in preview['omitidos_decision'][0]['razones'][0]
    assert count_pending_actions(preview) == 1


def test_analyze_subcontratas_omitidos_decision_cuenta_pendientes():
    from app.services.sync_preview_service import analyze_subcontratas_preview

    diff = {
        'empresas': {
            'nuevas': [], 'actualizadas': [], 'sin_cambios': [], 'rellenar_cif': [],
        },
        'empleados': {
            'nuevos': [],
            'actualizados': [],
            'desactivados': [{
                'odoo_id': 1, 'local_id': 2, 'name': 'A', 'lastname': 'B',
                'motivo': 'inactivo_odoo',
            }],
            'omitidos_decision': [{
                'odoo_id': 9, 'local_id': 3, 'name': 'X', 'lastname': 'Y',
                'dni': 'EXT-9', 'motivo': 'No aparece en Odoo (res.partner)',
                'tipo_aviso': 'no_encontrado',
            }],
        },
        'meta': {'empresas_odoo': 1},
    }
    preview = analyze_subcontratas_preview(diff)
    assert preview['stats']['omitidos_decision'] == 1
    assert preview['stats']['desactivados'] == 1
    assert count_pending_actions(preview) == 2


def test_authorize_empleados_departamento(app, session, tenant_soltec):
    from flask import g
    from sqlalchemy import text

    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        SyncConfigService.save_config({
            'sync_empleados_departamentos': [
                {'department': 'JO clima', 'role': 'jefe_obra'},
            ],
        })
        result = SyncConfigService.authorize_empleados_departamento(
            'JO SOLTEC', 'jefe_obra',
        )
        assert result['department'] == 'JO SOLTEC'
        assert result['role'] == 'jefe_obra'
        assert result['updated'] is False
        rows = SyncConfigService.get_empleados_departamento_map()
        assert any(r['department'] == 'JO SOLTEC' for r in rows)
        assert resolve_departamento_role('JO SOLTEC', rows) == 'jefe_obra'

        again = SyncConfigService.authorize_empleados_departamento(
            'JO SOLTEC', 'operario',
        )
        assert again['updated'] is True
        rows2 = SyncConfigService.get_empleados_departamento_map()
        assert resolve_departamento_role('JO SOLTEC', rows2) == 'operario'
