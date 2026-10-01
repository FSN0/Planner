"""Cobertura / progreso de solicitudes GENERICA."""
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.solicitud_service import (
    get_solicitud_valid_dates,
    compute_generica_coverage,
    build_comentarios_config,
)


def _sol(**kwargs):
    base = dict(
        id=1,
        obra_id=10,
        tipo='GENERICA',
        fecha_inicio=date(2026, 9, 14),  # lun
        fecha_fin=date(2026, 9, 18),    # vie
        cantidad_solicitada=2,
        cantidad_cubierta=0,
        comentarios=build_comentarios_config([
            date(2026, 9, 14),
            date(2026, 9, 15),
            date(2026, 9, 16),
            date(2026, 9, 17),
            date(2026, 9, 18),
        ]),
        estado='PENDIENTE',
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_valid_dates_usa_original_dates_no_fin_de_semana():
    sol = _sol()
    dates = get_solicitud_valid_dates(sol)
    assert dates == [
        date(2026, 9, 14),
        date(2026, 9, 15),
        date(2026, 9, 16),
        date(2026, 9, 17),
        date(2026, 9, 18),
    ]


def test_valid_dates_prioriza_original_sobre_dates_incompletos():
    cfg = json.loads(_sol().comentarios)
    cfg['dates'] = ['2026-09-18']  # solo viernes incompleto
    sol = _sol(comentarios=json.dumps(cfg))
    dates = get_solicitud_valid_dates(sol)
    assert len(dates) == 5
    assert date(2026, 9, 14) in dates


def test_progreso_es_minimo_por_dia_y_pct_jornadas():
    """1 persona lun-vie → progreso 1/2 y cobertura 50%."""
    sol = _sol()
    days = get_solicitud_valid_dates(sol)
    counts = {d: 1 for d in days}
    cov = compute_generica_coverage(sol, counts_by_day=counts)
    assert cov['min_coverage'] == 1
    assert cov['pct'] == 50
    assert cov['jornadas_filled'] == 5
    assert cov['jornadas_needed'] == 10


def test_cobertura_parcial_segundo_trabajador():
    """2º tío 4 días → progreso sigue 1/2, cobertura 90%."""
    sol = _sol()
    days = get_solicitud_valid_dates(sol)
    counts = {d: 2 for d in days}
    counts[date(2026, 9, 18)] = 1  # viernes solo 1
    cov = compute_generica_coverage(sol, counts_by_day=counts)
    assert cov['min_coverage'] == 1
    assert cov['pct'] == 90
    assert cov['jornadas_filled'] == 9


def test_cobertura_completa_cierra_mental_model():
    sol = _sol()
    days = get_solicitud_valid_dates(sol)
    counts = {d: 2 for d in days}
    cov = compute_generica_coverage(sol, counts_by_day=counts)
    assert cov['min_coverage'] == 2
    assert cov['pct'] == 100


def test_pct_no_usa_span_calendario_con_finde(monkeypatch):
    """El % erróneo ~71% venía de contar sáb/dom en el denominador."""
    sol = _sol(
        fecha_inicio=date(2026, 9, 14),
        fecha_fin=date(2026, 9, 20),  # lun–dom
    )
    days = get_solicitud_valid_dates(sol)
    assert date(2026, 9, 19) not in days  # sábado fuera vía original_dates
    counts = {d: 2 for d in days}
    cov = compute_generica_coverage(sol, counts_by_day=counts)
    assert cov['pct'] == 100
    # Si se usara el span calendario (7 días × 2): 10/14 ≈ 71%
    wrong = int((10 / 14) * 100)
    assert wrong == 71
    assert cov['pct'] != wrong


def test_baseline_no_cuenta_gente_ya_en_obra(monkeypatch):
    """Con baseline, quien ya estaba al pedir no infla el progreso."""
    days = [
        date(2026, 9, 14),
        date(2026, 9, 15),
        date(2026, 9, 16),
        date(2026, 9, 17),
        date(2026, 9, 18),
    ]
    baseline = {d.strftime('%Y-%m-%d'): [101, 102] for d in days}
    sol = _sol(comentarios=build_comentarios_config(days, baseline_users_by_day=baseline))

    class _A:
        def __init__(self, user_id, fecha, solicitud_id=None):
            self.user_id = user_id
            self.fecha = fecha
            self.solicitud_id = solicitud_id

    rows = [_A(101, d) for d in days] + [_A(102, d) for d in days]

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return rows

    class _Col:
        def __eq__(self, other):
            return self

        def in_(self, other):
            return self

    class _Asig:
        obra_id = _Col()
        user_id = _Col()
        fecha = _Col()
        solicitud_id = _Col()
        query = _Q()

    import app.services.solicitud_service as svc
    monkeypatch.setattr(svc, 'Asignacion', _Asig)
    cov = compute_generica_coverage(sol)
    assert cov['has_baseline'] is True
    assert cov['min_coverage'] == 0
    assert cov['pct'] == 0


def test_baseline_cuenta_nuevos_y_cierra_mental(monkeypatch):
    days = [
        date(2026, 9, 14),
        date(2026, 9, 15),
        date(2026, 9, 16),
        date(2026, 9, 17),
        date(2026, 9, 18),
    ]
    baseline = {d.strftime('%Y-%m-%d'): [101] for d in days}
    sol = _sol(
        cantidad_solicitada=2,
        comentarios=build_comentarios_config(days, baseline_users_by_day=baseline),
    )

    class _A:
        def __init__(self, user_id, fecha, solicitud_id=None):
            self.user_id = user_id
            self.fecha = fecha
            self.solicitud_id = solicitud_id

    rows = []
    for d in days:
        rows.extend([_A(101, d), _A(201, d), _A(202, d)])

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return rows

    class _Col:
        def __eq__(self, other):
            return self

        def in_(self, other):
            return self

    class _Asig:
        obra_id = _Col()
        user_id = _Col()
        fecha = _Col()
        solicitud_id = _Col()
        query = _Q()

    import app.services.solicitud_service as svc
    monkeypatch.setattr(svc, 'Asignacion', _Asig)
    cov = compute_generica_coverage(sol)
    assert cov['min_coverage'] == 2
    assert cov['pct'] == 100
