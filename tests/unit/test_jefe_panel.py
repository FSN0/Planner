"""Ficha y calendario de jefe de obra: indicadores y plantilla de sus obras."""
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import text

from app.models import ROLE_JEFE, Asignacion
from app.services.entity_panel_service import get_jefe_panel_stats, get_worker_panel_stats
from app.utils.timezone_utils import today_local


def test_jefe_stats_count_people_on_managed_sites(
    app, session, tenant_soltec, user_jefe, user_operario, obra_activa
):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    today = today_local()
    session.add(Asignacion(
        user_id=user_operario.id,
        obra_id=obra_activa.id,
        fecha=today,
        company_id=user_operario.company_id,
    ))
    session.commit()

    with app.test_request_context('/'):
        stats = get_jefe_panel_stats(user_jefe)

    keys = {s['key'] for s in stats['stats']}
    assert 'obras_cargo' in keys
    assert 'personas_hoy' in keys
    assert 'fichajes' not in keys
    assert 'reputacion' not in keys
    personas = next(s for s in stats['stats'] if s['key'] == 'personas_hoy')
    assert personas['value'] == 1
    obras_hoy = next(s for s in stats['stats'] if s['key'] == 'obras_hoy')
    assert str(obras_hoy['value']).startswith('1/')


def test_worker_panel_stats_routes_jefe(app, monkeypatch):
    called = {'jefe': False}

    def fake_jefe(worker):
        called['jefe'] = True
        return {'stats': [], 'chart_14d': [], 'chart_14d_max': 1}

    monkeypatch.setattr(
        'app.services.entity_panel_service.get_jefe_panel_stats', fake_jefe
    )
    worker = SimpleNamespace(role=ROLE_JEFE, id=9)
    get_worker_panel_stats(worker)
    assert called['jefe'] is True


def test_jefe_calendar_events_list_workers(
    app, session, tenant_soltec, user_jefe, user_operario, obra_activa
):
    from sqlalchemy import text
    from app.api.routes import _jefe_managed_obra_events

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    today = date.today()
    session.add(Asignacion(
        user_id=user_operario.id,
        obra_id=obra_activa.id,
        fecha=today,
        company_id=user_operario.company_id,
    ))
    session.commit()

    events = _jefe_managed_obra_events(
        user_jefe.id, today, today + timedelta(days=1)
    )
    assert events
    assert events[0]['extendedProps']['type'] == 'jefe_obra_dia'
    assert 'Juan Operario' in events[0]['extendedProps']['tooltipText']
    assert events[0]['editable'] is False
