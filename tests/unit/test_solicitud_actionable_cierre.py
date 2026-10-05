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
@patch('app.services.solicitud_service.today_local', return_value=date(2026, 10, 5))
def test_asignar_concreta_cubre_dia_es_cumplida(mock_hoy, mock_asig, mock_db):
    """Asignar en cuadrante el día pedido cierra la concreta."""
    day = date(2026, 10, 19)
    sol = _concreta_desasignar(
        accion='ASIGNAR',
        estado='PENDIENTE',
        days=[day],
        fecha_inicio=day,
        fecha_fin=day,
        comentarios=build_comentarios_config([day]),
    )
    mock_asig.query.filter.return_value.all.return_value = [
        SimpleNamespace(fecha=day),
    ]
    _recalculate_solicitud_coverage(sol, resolved_by_id=1)
    assert sol.estado == 'CUMPLIDA'
    assert sol.auto_fulfilled is True


@patch('app.services.solicitud_service.notificar_resolucion_solicitud', create=True)
@patch('app.services.solicitud_service.get_solicitud_pending_dates')
@patch('app.services.solicitud_service._recalculate_solicitud_coverage')
@patch('app.services.solicitud_service._link_concreta_assignment')
@patch('app.services.solicitud_service.User')
@patch('app.services.solicitud_service.Solicitud')
@patch('app.services.solicitud_service.today_local', return_value=date(2026, 10, 5))
def test_update_cierra_si_pending_vacio(
    mock_hoy, mock_sol_model, mock_user, mock_link, mock_recalc, mock_pending, mock_notif,
):
    """Red de seguridad: sin días pendientes → CUMPLIDA aunque recalc no lo marque."""
    from app.services.solicitud_service import (
        update_solicitudes_for_assignment,
    )

    day = date(2026, 10, 19)
    sol = _concreta_desasignar(
        accion='ASIGNAR',
        estado='PENDIENTE',
        days=[day],
        fecha_inicio=day,
        fecha_fin=day,
        comentarios=build_comentarios_config([day]),
    )
    mock_user.query.get.return_value = SimpleNamespace(id=55, name='A', lastname='B')
    mock_sol_model.query.filter.return_value.all.return_value = [sol]
    mock_pending.return_value = []

    def _noop_recalc(s, *a, **k):
        # Simula un recalc que se deja la solicitud abierta por bug.
        s.estado = 'PENDIENTE'

    mock_recalc.side_effect = _noop_recalc

    with patch('app.services.solicitud_service._mark_auto_cumplida') as mock_mark:
        update_solicitudes_for_assignment(10, 55, day, resolved_by_id=1)
        mock_mark.assert_called_once()
        assert mock_mark.call_args.kwargs.get('automatico') is True


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
