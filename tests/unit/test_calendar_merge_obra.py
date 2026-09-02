"""Calendario universal: fusión de bloques y desasignación."""
from datetime import date, timedelta

from app.api.routes import merge_events_v2


def test_merge_no_fusiona_misma_obra_titulo_distinta_obra_id():
    day = date.today() + timedelta(days=1)
    day2 = day + timedelta(days=1)
    raw = [
        {
            'title': 'Reforma',
            'start_date': day,
            'end_date': day,
            'color': '#3b82f6',
            'obra_id': 100,
            'extendedProps': {'obra_id': 100},
        },
        {
            'title': 'Reforma',
            'start_date': day2,
            'end_date': day2,
            'color': '#3b82f6',
            'obra_id': 200,
            'extendedProps': {'obra_id': 200},
        },
    ]
    merged_old = merge_events_v2(raw, group_by=['title', 'color'])
    merged_new = merge_events_v2(raw, group_by=['title', 'color', 'obra_id'])

    assert len(merged_old) == 1
    assert merged_old[0]['extendedProps']['obra_id'] == 100

    assert len(merged_new) == 2
    obra_ids = {ev['extendedProps']['obra_id'] for ev in merged_new}
    assert obra_ids == {100, 200}


def test_merge_acumula_delete_refs():
    day = date.today() + timedelta(days=1)
    day2 = day + timedelta(days=1)
    raw = [
        {
            'title': 'Obra A',
            'start_date': day,
            'end_date': day,
            'color': '#3b82f6',
            'obra_id': 100,
            'delete_refs': [{'obra_id': 100, 'fecha': day.isoformat()}],
            'extendedProps': {'obra_id': 100},
        },
        {
            'title': 'Obra A',
            'start_date': day2,
            'end_date': day2,
            'color': '#3b82f6',
            'obra_id': 100,
            'delete_refs': [{'obra_id': 100, 'fecha': day2.isoformat()}],
            'extendedProps': {'obra_id': 100},
        },
    ]
    merged = merge_events_v2(raw, group_by=['title', 'color', 'obra_id'])
    assert len(merged) == 1
    refs = merged[0]['extendedProps']['delete_refs']
    assert len(refs) == 2
    assert refs[0]['fecha'] == day.isoformat()
    assert refs[1]['fecha'] == day2.isoformat()
