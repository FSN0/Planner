"""Pintado de solicitudes: solo días pendientes."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.services.solicitud_service import (
    build_comentarios_config,
    collapse_dates_to_ranges,
    get_solicitud_pending_dates,
)


def test_collapse_dates_to_ranges_gaps():
    dates = [
        date(2026, 10, 13),
        date(2026, 10, 14),
        date(2026, 10, 16),
        date(2026, 10, 17),
        date(2026, 10, 20),
    ]
    assert collapse_dates_to_ranges(dates) == [
        (date(2026, 10, 13), date(2026, 10, 14)),
        (date(2026, 10, 16), date(2026, 10, 17)),
        (date(2026, 10, 20), date(2026, 10, 20)),
    ]


@patch('app.services.solicitud_service.Asignacion')
def test_asignar_concreta_omite_dias_ya_cubiertos(mock_asig):
    days = [date(2026, 10, 13), date(2026, 10, 14)]
    sol = SimpleNamespace(
        tipo='CONCRETA',
        accion='ASIGNAR',
        obra_id=10,
        empleado_id=55,
        fecha_inicio=days[0],
        fecha_fin=days[-1],
        comentarios=build_comentarios_config(days),
        cantidad_solicitada=1,
    )
    mock_asig.query.filter.return_value.all.return_value = [
        SimpleNamespace(fecha=date(2026, 10, 13)),
    ]
    assert get_solicitud_pending_dates(sol) == [date(2026, 10, 14)]


@patch('app.services.solicitud_service.Asignacion')
def test_desasignar_concreta_solo_dias_aun_asignados(mock_asig):
    days = [date(2026, 10, 13), date(2026, 10, 14)]
    sol = SimpleNamespace(
        tipo='CONCRETA',
        accion='DESASIGNAR',
        obra_id=10,
        empleado_id=55,
        fecha_inicio=days[0],
        fecha_fin=days[-1],
        comentarios=build_comentarios_config(days),
        cantidad_solicitada=1,
    )
    mock_asig.query.filter.return_value.all.return_value = [
        SimpleNamespace(fecha=date(2026, 10, 14)),
    ]
    assert get_solicitud_pending_dates(sol) == [date(2026, 10, 14)]


@patch('app.services.solicitud_service.compute_generica_coverage')
def test_generica_omite_dias_completos(mock_cov):
    days = [date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)]
    sol = SimpleNamespace(
        tipo='GENERICA',
        accion=None,
        obra_id=10,
        empleado_id=None,
        fecha_inicio=days[0],
        fecha_fin=days[-1],
        comentarios=build_comentarios_config(days),
        cantidad_solicitada=2,
    )
    mock_cov.return_value = {
        'requested': 2,
        'counts_by_day': {
            date(2026, 10, 13): 2,
            date(2026, 10, 14): 1,
            date(2026, 10, 15): 0,
        },
    }
    assert get_solicitud_pending_dates(sol) == [
        date(2026, 10, 14),
        date(2026, 10, 15),
    ]
