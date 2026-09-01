# tests/unit/test_worker_vehicle_rows.py

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.services.entity_panel_service import get_worker_vehicle_rows, get_worker_vehicle_today


def _fake_day_map(worker, start, end, end_exclusive=True):
    days = {}
    d = start
    while d <= end:
        days[d] = {
            'vehiculo_id': 1,
            'label': 'Furgón 1',
            'km': 100,
            'conductor': 'Juan',
            'source': 'plan',
        }
        d += timedelta(days=1)
    return days


@patch('app.services.entity_panel_service.get_worker_vehicle_day_map', side_effect=_fake_day_map)
@patch('app.services.entity_panel_service.today_local', return_value=date(2026, 9, 1))
def test_worker_vehicle_rows_pagination(mock_today, mock_map):
    worker = SimpleNamespace(id=1)
    page = get_worker_vehicle_rows(worker, days=10, offset=0, limit=3)
    assert page['total'] == 10
    assert len(page['rows']) == 3
    assert page['has_next'] is True
    assert page['has_prev'] is False

    page2 = get_worker_vehicle_rows(worker, days=10, offset=3, limit=3)
    assert page2['has_prev'] is True
    assert page2['offset'] == 3


@patch('app.services.entity_panel_service.get_worker_vehicle_day_map')
@patch('app.services.entity_panel_service.today_local', return_value=date(2026, 9, 1))
def test_worker_vehicle_today_none(mock_today, mock_map):
    mock_map.return_value = {}
    assert get_worker_vehicle_today(SimpleNamespace(id=1)) is None
