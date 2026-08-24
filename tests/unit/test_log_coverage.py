from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.services.core_assignment_service import CoreAssignmentService
from app.services.i18n_service import translate_log_detail
from app.services.log_coverage import planif_detail_covers_day, strip_coverage


def test_translate_log_detail_hides_coverage_marker():
    raw = (
        "Asignado David Álvarez → 'OFICINA — Oficina' "
        "(10/08/2026 → 17/08/2026, 6 días). "
        "[[cov:2026-08-10,2026-08-11,2026-08-12,2026-08-13,2026-08-14,2026-08-17]]"
    )
    en = translate_log_detail(raw, "en")
    assert "[[cov:" not in en
    assert "Assigned" in en
    assert "David Álvarez" in en


@patch("app.services.core_assignment_service.Obra")
@patch("app.services.core_assignment_service.User")
@patch("app.services.core_assignment_service.db")
def test_registrar_log_rango_writes_one_grouped_log(db, User, Obra, app):
    Obra.query.get.return_value = SimpleNamespace(
        id=6, codigo="S25/006", nombre="CEE GARGASINDI"
    )
    User.query.get.return_value = SimpleNamespace(name="David", lastname="Álvarez")
    days = [date(2026, 8, 10) + timedelta(days=i) for i in range(11)]

    with app.app_context():
        CoreAssignmentService.registrar_log_rango(
            10, 6, days[0], days[-1], len(days),
            1, "Planificación Manual", True,
            fechas=days,
        )

    assert db.session.add.call_count == 1
    log = db.session.add.call_args[0][0]
    assert log.category == "planificacion"
    assert log.target_user_id == 10
    assert log.target_date == days[0]
    assert log.user_id == 1
    assert "[[cov:" not in (log.detail or "")
    assert "10/08/2026 → 20/08/2026" in log.detail
    assert ", 11 días" in log.detail
    assert planif_detail_covers_day(log.detail, date(2026, 8, 15))


@patch("app.services.core_assignment_service.Obra")
@patch("app.services.core_assignment_service.User")
@patch("app.services.core_assignment_service.db")
def test_registrar_log_rango_sparse_keeps_one_log_and_skips_gaps(db, User, Obra, app):
    Obra.query.get.return_value = SimpleNamespace(
        id=6, codigo="S25/006", nombre="CEE GARGASINDI"
    )
    User.query.get.return_value = SimpleNamespace(name="David", lastname="Álvarez")
    days = [
        date(2026, 8, 10),
        date(2026, 8, 11),
        date(2026, 8, 12),
        date(2026, 8, 13),
        date(2026, 8, 14),
        date(2026, 8, 17),
    ]

    with app.app_context():
        CoreAssignmentService.registrar_log_rango(
            10, 6, days[0], days[-1], len(days),
            1, "Planificación Manual", True,
            fechas=days,
        )

    assert db.session.add.call_count == 1
    log = db.session.add.call_args[0][0]
    assert "[[cov:" in log.detail
    assert planif_detail_covers_day(log.detail, date(2026, 8, 14))
    assert planif_detail_covers_day(log.detail, date(2026, 8, 17))
    assert not planif_detail_covers_day(log.detail, date(2026, 8, 15))
    assert not planif_detail_covers_day(log.detail, date(2026, 8, 16))
    assert "[[cov:" not in strip_coverage(log.detail)
    assert "6 días" in strip_coverage(log.detail)
