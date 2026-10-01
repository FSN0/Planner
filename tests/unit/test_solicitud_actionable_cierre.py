"""Cierre por días accionables (hoy+) y CERRADA_PARCIAL / vencida."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.solicitud_service import (
    build_comentarios_config,
    get_solicitud_actionable_dates,
    _recalculate_solicitud_coverage,
)


def _concreta_desasignar(**kwargs):
    days = kwargs.pop('days', [
        date(2026, 9, 28),
        date(2026, 9, 29),
        date(2026, 9, 30),
        date(2026, 10, 1),
        date(2026, 10, 2),
    ])
    base = dict(
        id=7,
        obra_id=10,
        empleado_id=55,
        tipo='CONCRETA',
        accion='DESASIGNAR',
        fecha_inicio=days[0],
        fecha_fin=days[-1],
        cantidad_solicitada=1,
        cantidad_cubierta=0,
        comentarios=build_comentarios_config(days),
        estado='EN_PROCESO',
        auto_fulfilled=False,
        resolved_at=None,
        resolved_by_id=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _asig(fecha):
    return SimpleNamespace(fecha=fecha, obra_id=10, user_id=55)


@patch('app.services.solicitud_service.db')
@patch('app.services.solicitud_service.Asignacion')
@patch('app.services.solicitud_service.today_local', return_value=date(2026, 10, 1))
def test_desasignar_limpia_accionable_con_pasado_queda_parcial(mock_hoy, mock_asig, mock_db):
    """Caso real: 28–2; solo se pueden tocar 1–2; tras desasignar → CERRADA_PARCIAL."""
    sol = _concreta_desasignar()
    # Sigue asignado en pasado; limpio en 1 y 2.
    mock_asig.query.filter.return_value.all.return_value = [
        _asig(date(2026, 9, 28)),
        _asig(date(2026, 9, 29)),
        _asig(date(2026, 9, 30)),
    ]
    _recalculate_solicitud_coverage(sol)
    assert sol.estado == 'CERRADA_PARCIAL'
    assert sol.auto_fulfilled is True
    assert mock_db.session.add.called


@patch('app.services.solicitud_service.db')
@patch('app.services.solicitud_service.Asignacion')
@patch('app.services.solicitud_service.today_local', return_value=date(2026, 10, 1))
def test_desasignar_limpia_todo_es_cumplida(mock_hoy, mock_asig, mock_db):
    sol = _concreta_desasignar()
    mock_asig.query.filter.return_value.all.return_value = []
    _recalculate_solicitud_coverage(sol)
    assert sol.estado == 'CUMPLIDA'
    assert sol.auto_fulfilled is True


@patch('app.services.solicitud_service.db')
@patch('app.services.solicitud_service.Asignacion')
@patch('app.services.solicitud_service.today_local', return_value=date(2026, 10, 1))
def test_desasignar_sigue_en_accionable_en_proceso(mock_hoy, mock_asig, mock_db):
    sol = _concreta_desasignar()
    mock_asig.query.filter.return_value.all.return_value = [
        _asig(date(2026, 9, 28)),
        _asig(date(2026, 10, 1)),  # aún hoy
    ]
    _recalculate_solicitud_coverage(sol)
    assert sol.estado == 'EN_PROCESO'
    assert not sol.auto_fulfilled


@patch('app.services.solicitud_service.db')
@patch('app.services.solicitud_service.Asignacion')
@patch('app.services.solicitud_service.today_local', return_value=date(2026, 10, 3))
def test_desasignar_vencida_sin_accionables(mock_hoy, mock_asig, mock_db):
    sol = _concreta_desasignar(estado='PENDIENTE')
    mock_asig.query.filter.return_value.all.return_value = [
        _asig(date(2026, 9, 28)),
    ]
    _recalculate_solicitud_coverage(sol)
    assert sol.estado == 'CERRADA_PARCIAL'
    assert sol.auto_fulfilled is True


@patch('app.services.solicitud_service.db')
@patch('app.services.solicitud_service.Asignacion')
@patch('app.services.solicitud_service.today_local', return_value=date(2026, 10, 3))
def test_asignar_vencida_sin_atender(mock_hoy, mock_asig, mock_db):
    days = [date(2026, 9, 28), date(2026, 9, 29)]
    sol = _concreta_desasignar(
        accion='ASIGNAR',
        estado='PENDIENTE',
        days=days,
        fecha_inicio=days[0],
        fecha_fin=days[-1],
        comentarios=build_comentarios_config(days),
    )
    mock_asig.query.filter.return_value.all.return_value = []
    _recalculate_solicitud_coverage(sol)
    assert sol.estado == 'CERRADA_PARCIAL'
    assert sol.auto_fulfilled is True


@patch('app.services.solicitud_service.today_local', return_value=date(2026, 10, 1))
def test_actionable_dates_filtra_pasado(mock_hoy):
    sol = _concreta_desasignar()
    assert get_solicitud_actionable_dates(sol) == [
        date(2026, 10, 1),
        date(2026, 10, 2),
    ]


@patch('app.services.solicitud_service.db')
@patch('app.services.solicitud_service.compute_generica_coverage')
@patch('app.services.solicitud_service.today_local', return_value=date(2026, 10, 3))
def test_generica_vencida_sin_atender(mock_hoy, mock_cov, mock_db):
    days = [date(2026, 9, 28), date(2026, 9, 29)]
    sol = SimpleNamespace(
        id=9,
        obra_id=10,
        tipo='GENERICA',
        accion=None,
        fecha_inicio=days[0],
        fecha_fin=days[-1],
        cantidad_solicitada=2,
        cantidad_cubierta=0,
        comentarios=build_comentarios_config(days),
        estado='PENDIENTE',
        auto_fulfilled=False,
        resolved_at=None,
        resolved_by_id=None,
    )
    mock_cov.return_value = {
        'requested': 2,
        'counts_by_day': {days[0]: 0, days[1]: 0},
        'min_coverage': 0,
        'total_assignments': 0,
        'pct': 0,
        'jornadas_filled': 0,
        'jornadas_needed': 4,
    }
    _recalculate_solicitud_coverage(sol)
    assert sol.estado == 'CERRADA_PARCIAL'
    assert sol.auto_fulfilled is True
