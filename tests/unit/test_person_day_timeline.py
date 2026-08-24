from datetime import date
from unittest.mock import patch

from app.services.log_coverage import (
    attach_coverage,
    dates_are_contiguous,
    planif_detail_covers_day,
    strip_coverage,
)
from app.services.person_day_timeline_service import _synthetic_asignacion_hito


def test_planif_range_log_covers_days_inside():
    detail = (
        "Asignado David Álvarez Cortes → 'S25/006 — CEE GARGASINDI ( CALPE )' "
        "(01/08/2026 → 17/08/2026, 12 días)."
    )
    assert planif_detail_covers_day(detail, date(2026, 8, 1))
    assert planif_detail_covers_day(detail, date(2026, 8, 11))
    assert planif_detail_covers_day(detail, date(2026, 8, 17))
    assert not planif_detail_covers_day(detail, date(2026, 8, 18))
    assert not planif_detail_covers_day(detail, date(2026, 7, 31))


def test_planif_single_day_log_does_not_cover_neighbours():
    detail = (
        "Asignado David Álvarez Cortes → 'S25/006 — CEE GARGASINDI ( CALPE )' "
        "(10/08/2026)."
    )
    assert planif_detail_covers_day(detail, date(2026, 8, 10))
    assert not planif_detail_covers_day(detail, date(2026, 8, 11))


@patch("app.services.person_day_timeline_service._obra_panel_url", return_value="/obra/6")
def test_synthetic_planificacion_without_timestamp_has_no_clock(_url):
    class _U:
        name = "David"
        lastname = "Álvarez Cortes"

    class _O:
        id = 6
        codigo = "S25/006"
        nombre = "CEE GARGASINDI ( CALPE )"

    hito = _synthetic_asignacion_hito(_U(), _O(), date(2026, 8, 10), created_at=None)
    assert hito["fecha"] == "10/08"
    assert "08:00" not in hito["fecha"]
    assert hito["fecha"].count(":") == 0


def test_sparse_coverage_skips_gaps():
    days = [
        date(2026, 8, 10),
        date(2026, 8, 11),
        date(2026, 8, 12),
        date(2026, 8, 13),
        date(2026, 8, 14),
        date(2026, 8, 17),
    ]
    assert not dates_are_contiguous(days)
    detail = attach_coverage(
        "Asignado David → 'Gargasindi' (10/08/2026 → 17/08/2026, 6 días).",
        days,
    )
    assert "[[cov:" in detail
    assert planif_detail_covers_day(detail, date(2026, 8, 14))
    assert planif_detail_covers_day(detail, date(2026, 8, 17))
    assert not planif_detail_covers_day(detail, date(2026, 8, 15))
    assert not planif_detail_covers_day(detail, date(2026, 8, 16))
    assert "[[cov:" not in strip_coverage(detail)


def test_contiguous_range_does_not_need_marker():
    days = [date(2026, 8, d) for d in range(10, 21)]
    detail = attach_coverage(
        "Asignado David → 'Gargasindi' (10/08/2026 → 20/08/2026, 11 días).",
        days,
    )
    assert "[[cov:" not in detail
    assert planif_detail_covers_day(detail, date(2026, 8, 15))
