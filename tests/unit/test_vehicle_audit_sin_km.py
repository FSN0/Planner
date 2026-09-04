"""Sin km no debe duplicar un conductor distinto (el planificado no usó el coche)."""
from datetime import date, timedelta
from types import SimpleNamespace

from app.services.vehicle_anomaly_service import filter_sin_km_explicados_por_mismatch


def _row(uid, vid, fecha, estado='sin_km'):
    return SimpleNamespace(
        planned_user_id=uid,
        vehiculo_id=vid,
        fecha=fecha,
        estado=estado,
    )


def test_sin_km_same_day_dropped_when_mismatch(app):
    d = date(2026, 9, 1)
    mismatch = [_row(10, 5, d, 'mismatch_driver')]
    sin_km = [_row(10, 5, d, 'sin_km'), _row(11, 8, d, 'sin_km')]
    kept = filter_sin_km_explicados_por_mismatch(sin_km, mismatch)
    assert [r.planned_user_id for r in kept] == [11]


def test_sin_km_other_days_same_vehicle_dropped(app):
    d0 = date(2026, 9, 1)
    d1 = d0 + timedelta(days=1)
    mismatch = [_row(10, 5, d0, 'mismatch_driver')]
    sin_km = [_row(10, 5, d1, 'sin_km'), _row(10, 9, d1, 'sin_km')]
    kept = filter_sin_km_explicados_por_mismatch(sin_km, mismatch)
    assert [(r.planned_user_id, r.vehiculo_id) for r in kept] == [(10, 9)]


def test_sin_km_untouched_without_mismatch(app):
    d = date(2026, 9, 1)
    sin_km = [_row(10, 5, d, 'sin_km')]
    assert filter_sin_km_explicados_por_mismatch(sin_km, []) == sin_km
    assert filter_sin_km_explicados_por_mismatch(sin_km, None) == sin_km


def test_sin_km_hides_today_keeps_yesterday(app):
    from app.services.vehicle_anomaly_service import filter_sin_km_solo_pasados
    hoy = date(2026, 9, 4)
    ayer = date(2026, 9, 3)
    manana = date(2026, 9, 5)
    rows = [
        _row(1, 1, ayer),
        _row(2, 2, hoy),
        _row(3, 3, manana),
    ]
    kept = filter_sin_km_solo_pasados(rows, hoy)
    assert [r.fecha for r in kept] == [ayer]
