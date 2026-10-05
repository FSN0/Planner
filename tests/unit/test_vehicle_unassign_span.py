"""Tramo de desasignación de vehículos."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.vehicle_assignment_service import last_vehicle_assignment_end


class _Col:
    def __ge__(self, other):
        return ('ge', other)

    def desc(self):
        return 'desc'


def _patch_av(query):
    AV = MagicMock()
    AV.query = query
    AV.vehiculo_id = 'vehiculo_id'
    AV.user_id = 'user_id'
    AV.fecha = _Col()
    return AV


def test_last_vehicle_assignment_end_returns_max():
    row = SimpleNamespace(fecha=date(2026, 6, 30))
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.first.return_value = row

    with patch('app.services.vehicle_assignment_service.AsignacionVehiculo', _patch_av(query)):
        end = last_vehicle_assignment_end(10, 20, date(2026, 1, 1))

    assert end == date(2026, 6, 30)
    query.filter.assert_called_once()


def test_last_vehicle_assignment_end_none_when_empty():
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.first.return_value = None

    with patch('app.services.vehicle_assignment_service.AsignacionVehiculo', _patch_av(query)):
        end = last_vehicle_assignment_end(10, 20, date(2026, 1, 1))

    assert end is None


def test_last_vehicle_assignment_end_requires_ids():
    assert last_vehicle_assignment_end(None, 1, date(2026, 1, 1)) is None
    assert last_vehicle_assignment_end(1, None, date(2026, 1, 1)) is None
    assert last_vehicle_assignment_end(1, 1, None) is None
