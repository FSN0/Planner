"""Calendario universal: fusión de bloques y desasignación."""
from datetime import date, timedelta
from types import SimpleNamespace

from app.api.routes import merge_events_v2, procesar_bloques_obra


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


def _asig(worker, obra, day):
    return SimpleNamespace(
        user=worker,
        user_id=worker.id,
        obra=obra,
        obra_id=obra.id,
        fecha=day,
    )


def test_procesar_bloques_obra_agrupa_empleados_en_tooltip():
    day = date.today() + timedelta(days=1)
    obra = SimpleNamespace(id=10, codigo='OBR001', nombre='Reforma Hotel', color='#3b82f6')
    ana = SimpleNamespace(id=1, name='Ana', lastname='Uno')
    luis = SimpleNamespace(id=2, name='Luis', lastname='Dos')
    events = procesar_bloques_obra([
        _asig(ana, obra, day),
        _asig(luis, obra, day),
    ])
    assert len(events) == 1
    ev = events[0]
    assert ev['extendedProps']['type'] == 'obra_group'
    assert ev['extendedProps']['obra_id'] == 10
    assert ev['title'].startswith('(2)')
    tip = ev['extendedProps']['tooltipContent']
    assert 'Ana Uno' in tip
    assert 'Luis Dos' in tip
    assert 'empleados' in tip


def test_procesar_bloques_obra_separa_obras_y_fusiona_dias():
    day = date.today() + timedelta(days=1)
    day2 = day + timedelta(days=1)
    obra_a = SimpleNamespace(id=10, codigo='A', nombre='Obra A', color='#111111')
    obra_b = SimpleNamespace(id=20, codigo='B', nombre='Obra B', color='#222222')
    ana = SimpleNamespace(id=1, name='Ana', lastname='Uno')
    events = procesar_bloques_obra([
        _asig(ana, obra_a, day),
        _asig(ana, obra_a, day2),
        _asig(ana, obra_b, day),
    ])
    assert len(events) == 2
    by_obra = {ev['extendedProps']['obra_id']: ev for ev in events}
    assert set(by_obra) == {10, 20}
    assert by_obra[10]['start'] == day.isoformat()
    assert by_obra[10]['end'] == (day2 + timedelta(days=1)).isoformat()
    assert by_obra[20]['start'] == day.isoformat()
    assert by_obra[20]['end'] == (day + timedelta(days=1)).isoformat()


def test_procesar_bloques_obra_mismo_order_si_cambia_el_recuento():
    day = date.today() + timedelta(days=1)
    day2 = day + timedelta(days=1)
    day3 = day2 + timedelta(days=1)
    obra = SimpleNamespace(id=42, codigo='X', nombre='Obra X', color='#333333')
    ana = SimpleNamespace(id=1, name='Ana', lastname='Uno')
    luis = SimpleNamespace(id=2, name='Luis', lastname='Dos')
    pepe = SimpleNamespace(id=3, name='Pepe', lastname='Tres')
    events = procesar_bloques_obra([
        _asig(ana, obra, day),
        _asig(ana, obra, day2),
        _asig(luis, obra, day2),
        _asig(ana, obra, day3),
        _asig(luis, obra, day3),
        _asig(pepe, obra, day3),
    ])
    assert len(events) == 3
    assert {ev['order'] for ev in events} == {42}
    assert all(ev['extendedProps']['lane'] == 42 for ev in events)
