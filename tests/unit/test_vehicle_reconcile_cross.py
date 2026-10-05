"""Reasignación autónoma plan A → uso Odoo en B."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.vehicle_reconcile_service import reconcile_vehicle_assignments_from_usage
from app.models import AsignacionVehiculo


def _user(uid=7, name='Martín'):
    return SimpleNamespace(id=uid, name=name, lastname='Test')


@patch('app.services.vehicle_reconcile_service.Vehiculo')
@patch('app.services.vehicle_reconcile_service.AsignacionVehiculo')
@patch('app.services.vehicle_reconcile_service.Core')
def test_cross_swap_deixa_fantasma_en_a_y_efectiva_en_b(mock_core, mock_asig, mock_veh):
    user = _user()
    fecha = date(2026, 10, 1)
    mock_veh.query.get.side_effect = lambda i: SimpleNamespace(
        id=i, label=lambda: f'Veh-{i}'
    )

    efectiva_a = SimpleNamespace(
        id=1, vehiculo_id=10, user_id=user.id, fecha=fecha, estado='efectiva', notas=None,
    )
    mock_core.get_efectiva_user.return_value = efectiva_a
    mock_asig.query.filter_by.return_value.all.return_value = []  # nadie más en B
    mock_asig.query.filter_by.return_value.first.return_value = None

    covered = {
        (20, '2026-10-01'): {
            'driver_partner_id': 99,
            'driver_name': 'Martín Test',
        }
    }

    def match_fn(*a, **k):
        return user

    stats = reconcile_vehicle_assignments_from_usage(
        covered, {}, {}, autor_id=1, match_driver_fn=match_fn,
    )
    assert stats['cross_swaps'] == 1
    mock_core.marcar_no_usada.assert_called_once()
    args, kwargs = mock_core.marcar_no_usada.call_args
    assert args[0] == 10  # A
    assert args[1] == user.id
    mock_core.asignar.assert_called()
    a_args, a_kwargs = mock_core.asignar.call_args
    assert a_args[0] == 20  # B
    assert a_kwargs.get('estado') == AsignacionVehiculo.ESTADO_EFECTIVA
    assert 'planificado' in (a_kwargs.get('notas') or '').lower() or 'Planificado' in (a_kwargs.get('notas') or '')


@patch('app.services.vehicle_reconcile_service.Vehiculo')
@patch('app.services.vehicle_reconcile_service.AsignacionVehiculo')
@patch('app.services.vehicle_reconcile_service.Core')
def test_otro_conductor_limpia_fantasma_en_b(mock_core, mock_asig, mock_veh):
    user = _user(8, 'Pedro')
    fecha = date(2026, 10, 1)
    mock_veh.query.get.side_effect = lambda i: SimpleNamespace(
        id=i, label=lambda: f'Veh-{i}'
    )
    ghost = SimpleNamespace(
        id=2, vehiculo_id=10, user_id=7, fecha=fecha, estado='no_usada',
    )
    mock_asig.query.filter_by.return_value.all.return_value = [ghost]
    mock_core.get_efectiva_user.return_value = None
    mock_asig.query.filter_by.return_value.first.return_value = None

    covered = {(10, '2026-10-01'): {'driver_name': 'Pedro Test'}}

    stats = reconcile_vehicle_assignments_from_usage(
        covered, {}, {}, autor_id=1, match_driver_fn=lambda *a, **k: user,
    )
    assert stats['ghosts_cleared'] >= 1
    mock_core.desasignar.assert_called()
    assert stats['claimed_free'] == 1
