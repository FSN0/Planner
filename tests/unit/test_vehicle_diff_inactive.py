"""Diff de flota: vehículos archivados en Odoo deben bajar active en SignaPlan."""
from unittest.mock import Mock

import pytest
from flask import g
from sqlalchemy import text

from app.models import Vehiculo


@pytest.fixture
def vehicle_adapter(tenant_soltec, app, session):
    from app.sync.adapters.odoo_soltec import Adapter

    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        Vehiculo.query.delete()
        session.commit()

        adapter = Adapter.__new__(Adapter)
        adapter.tenant_id = tenant_soltec.id
        adapter.db_name = 'db'
        adapter.uid = 2
        adapter.pwd = 'x'
        adapter.models = Mock()
        yield adapter


def _fleet_fields():
    return {
        'id': {'type': 'integer'},
        'name': {'type': 'char'},
        'license_plate': {'type': 'char'},
        'model_id': {'type': 'many2one'},
        'brand_id': {'type': 'many2one'},
        'active': {'type': 'boolean'},
        'driver_id': {'type': 'many2one'},
    }


def _mock_fleet(active_rows, archived_rows=None):
    """Simula search_read activo + archivado (+ active_map)."""
    archived_rows = list(archived_rows or [])
    active_rows = list(active_rows or [])
    all_rows = {int(r['id']): r for r in active_rows + archived_rows}

    def execute_kw(*args, **kwargs):
        model, method = args[3], args[4]
        if model == 'ir.model' and method == 'search_count':
            return 1
        if model == 'fleet.vehicle' and method == 'fields_get':
            return _fleet_fields()
        if model == 'fleet.vehicle' and method == 'search_read':
            domain = args[5][0] if len(args) > 5 else []
            opts = args[6] if len(args) > 6 else kwargs
            # active_map: [['id', 'in', ...]]
            if domain and isinstance(domain[0], (list, tuple)) and domain[0][0] == 'id':
                ids = set(int(x) for x in domain[0][2])
                return [all_rows[i] for i in ids if i in all_rows]
            # Lectura explícita de archivados
            if domain == [['active', '=', False]]:
                return list(archived_rows)
            # Lectura general / activos
            if opts.get('context', {}).get('active_test') is False and not domain:
                return list(all_rows.values())
            return list(active_rows)
        return []

    return execute_kw


def test_diff_desactiva_archivado_por_odoo_id(vehicle_adapter, session, app, tenant_soltec):
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        local = Vehiculo(
            nombre='Furgoneta A',
            matricula='1234ABC',
            active=True,
            external_ids={'odoo': '501'},
        )
        session.add(local)
        session.commit()

        vehicle_adapter.models.execute_kw.side_effect = _mock_fleet(
            active_rows=[],
            archived_rows=[{
                'id': 501,
                'name': 'Furgoneta A',
                'license_plate': '1234ABC',
                'model_id': False,
                'brand_id': False,
                'active': False,
                'driver_id': False,
            }],
        )
        diff = vehicle_adapter.get_diff_vehiculos()

        assert not diff.get('error')
        assert len(diff['actualizados']) == 1
        row = diff['actualizados'][0]
        assert row['local_id'] == local.id
        assert row['active'] is False
        assert 'Activo' in row['cambios']


def test_diff_desactiva_archivado_por_matricula_sin_link(
    vehicle_adapter, session, app, tenant_soltec,
):
    """Sin external_ids.odoo: el código viejo no lo bajaba; el nuevo sí por matrícula."""
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        local = Vehiculo(
            nombre='Pick-up',
            matricula='9999XYZ',
            active=True,
            external_ids={},
        )
        session.add(local)
        session.commit()

        vehicle_adapter.models.execute_kw.side_effect = _mock_fleet(
            active_rows=[],
            archived_rows=[{
                'id': 777,
                'name': 'Pick-up Odoo',
                'license_plate': '9999XYZ',
                'model_id': False,
                'brand_id': False,
                'active': False,
                'driver_id': False,
            }],
        )
        diff = vehicle_adapter.get_diff_vehiculos()

        assert len(diff['actualizados']) == 1
        assert diff['actualizados'][0]['local_id'] == local.id
        assert diff['actualizados'][0]['active'] is False
        assert diff['nuevos'] == []


def test_diff_desactiva_matricula_con_guiones(
    vehicle_adapter, session, app, tenant_soltec,
):
    """9431-XXX local vs 9431XXX en Odoo archivado."""
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        local = Vehiculo(
            nombre='Furgoneta 9431',
            matricula='9431-ABC',
            active=True,
            external_ids={},
        )
        session.add(local)
        session.commit()

        vehicle_adapter.models.execute_kw.side_effect = _mock_fleet(
            active_rows=[],
            archived_rows=[{
                'id': 88,
                'name': 'Furgoneta 9431',
                'license_plate': '9431 ABC',
                'active': False,
                'driver_id': False,
            }],
        )
        diff = vehicle_adapter.get_diff_vehiculos()
        assert len(diff['actualizados']) == 1
        assert diff['actualizados'][0]['local_id'] == local.id
        assert diff['actualizados'][0]['active'] is False


def test_diff_alta_archivados_como_inactivos(vehicle_adapter, session, app, tenant_soltec):
    """Archivado solo en Odoo: se importa en SignaPlan como nuevo inactivo."""
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        vehicle_adapter.models.execute_kw.side_effect = _mock_fleet(
            active_rows=[],
            archived_rows=[{
                'id': 12,
                'name': 'Archivado solo Odoo',
                'license_plate': '0000ZZZ',
                'active': False,
                'driver_id': False,
            }],
        )
        diff = vehicle_adapter.get_diff_vehiculos()
        assert len(diff['nuevos']) == 1
        assert diff['nuevos'][0]['active'] is False
        assert diff['nuevos'][0]['matricula'] == '0000ZZZ'
        assert diff['actualizados'] == []
