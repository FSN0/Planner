"""Badges de solicitudes abiertas (personal / vehículos)."""
from types import SimpleNamespace
from unittest.mock import patch

from app.services.solicitud_badge_service import count_open_solicitud_badges


def test_count_open_badges_anonimo():
    assert count_open_solicitud_badges(None) == {
        'personal': 0, 'vehiculos': 0, 'total': 0,
    }


@patch('app.services.solicitud_badge_service.SolicitudVehiculo')
@patch('app.services.solicitud_badge_service.Solicitud')
@patch('app.services.solicitud_badge_service.user_panel_mode', return_value='office')
@patch('app.services.solicitud_badge_service.user_can')
def test_count_open_badges_office_suma(mock_can, mock_mode, mock_sol, mock_veh):
    mock_can.side_effect = lambda u, mod, _w: True
    mock_sol.query.filter.return_value.count.return_value = 3
    mock_veh.query.filter.return_value.count.return_value = 1
    user = SimpleNamespace(is_authenticated=True, id=1)
    out = count_open_solicitud_badges(user)
    assert out == {'personal': 3, 'vehiculos': 1, 'total': 4}
