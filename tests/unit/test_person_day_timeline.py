from datetime import date
from unittest.mock import patch

from app.services.log_coverage import (
    attach_coverage,
    dates_are_contiguous,
    planif_detail_covers_day,
    strip_coverage,
)
from app.services.person_day_timeline_service import (
    _append_missing_fichaje_hitos,
    _day_fichaje_times,
    _enrich_fichaje_app_from_registro,
    _rebuild_fichaje_times_in_detail,
    _sync_fichaje_times_from_registro,
    _synthetic_asignacion_hito,
)


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


def test_enrich_fichaje_app_adds_planned_obra_on_conflict():
    class _Log:
        category = 'fichaje_app'
        target_user_id = 7
        target_date = date(2026, 8, 10)

    class _Reg:
        estado = 'Conflicto'
        obra_real_id = 2
        obra_planificada_id = 1

    class _Obra:
        def __init__(self, oid, codigo, nombre):
            self.id = oid
            self.codigo = codigo
            self.nombre = nombre

    obras = {
        1: _Obra(1, 'SOL-01', 'Viviendas Calle del Sol'),
        2: _Obra(2, 'OF-02', 'Oficinas Central'),
    }

    with patch('app.services.person_day_timeline_service.Obra') as ObraMock, patch(
        'app.services.person_day_timeline_service.RegistroFichaje'
    ) as RegMock:
        ObraMock.query.get.side_effect = lambda oid: obras.get(oid)
        RegMock.query.filter_by.return_value.first.return_value = _Reg()
        detail = _enrich_fichaje_app_from_registro(
            _Log(),
            'El operario fichó en OF-02 — Oficinas Central. Entrada: 07:45 / Salida: 16:10',
        )
    assert 'planificado' in detail
    assert 'Viviendas Calle del Sol' in detail


def test_rebuild_fichaje_times_updates_salida():
    detail = "El operario fichó en OF-02 — Oficinas Central. Entrada: 07:45 / Salida: -"
    updated = _rebuild_fichaje_times_in_detail(detail, "07:45", "16:10")
    assert "Entrada: 07:45 / Salida: 16:10" in updated


def test_sync_fichaje_times_from_registro_uses_check_out():
    from datetime import datetime

    class _Log:
        category = "fichaje_app"
        target_user_id = 7
        target_date = date(2026, 8, 10)

    class _Reg:
        check_in = datetime(2026, 8, 10, 7, 45)
        check_out = datetime(2026, 8, 10, 16, 10)
        obra_real_id = 2
        obra_planificada_id = 2

    class _Obra:
        id = 2
        codigo = "OF-02"
        nombre = "Oficinas Central"

    detail = "El operario fichó en OF-02 — Oficinas Central. Entrada: 07:45 / Salida: -"
    with patch("app.services.person_day_timeline_service.Obra") as ObraMock, patch(
        "app.services.person_day_timeline_service.RegistroFichaje"
    ) as RegMock:
        ObraMock.query.get.return_value = _Obra()
        RegMock.query.filter_by.return_value.all.return_value = [_Reg()]
        updated = _sync_fichaje_times_from_registro(_Log(), detail)
    assert "Salida: 16:10" in updated


def test_day_fichaje_times_picks_earliest_and_latest():
    from datetime import datetime

    class _R:
        def __init__(self, entrada, salida):
            self.check_in = entrada
            self.check_out = salida

    regs = [
        _R(datetime(2026, 8, 10, 8, 0), datetime(2026, 8, 10, 17, 0)),
        _R(datetime(2026, 8, 10, 7, 30), datetime(2026, 8, 10, 16, 30)),
    ]
    entrada, salida = _day_fichaje_times(regs)
    assert entrada == "07:30"
    assert salida == "17:00"


def test_append_missing_fichaje_hitos_adds_registro_without_log():
    class _User:
        id = 3
        name = "Ana"
        lastname = "López"

    class _Reg:
        id = 99
        check_in = None
        check_out = None
        obra_real_id = 5
        obra_planificada_id = 5
        estado = "Correcto_Automatico"
        nota_odoo = None

    class _Obra:
        id = 5
        codigo = "S25/001"
        nombre = "Obra Norte"

    hitos = [{
        "titulo": "Planificación",
        "descripcion": "Asignado Ana López → 'S25/001 — Obra Norte' (04/06/2026).",
    }]

    with patch("app.services.person_day_timeline_service.Obra") as ObraMock, patch(
        "app.services.person_day_timeline_service.RegistroFichaje"
    ) as RegMock, patch(
        "app.services.person_day_timeline_service._build_detail_html",
        side_effect=lambda text, *args, **kwargs: (text, text),
    ):
        from datetime import datetime

        _Reg.check_in = datetime(2026, 6, 4, 8, 15)
        _Reg.check_out = datetime(2026, 6, 4, 17, 5)
        ObraMock.query.get.return_value = _Obra()
        RegMock.query.filter_by.return_value.all.return_value = [_Reg()]
        out = _append_missing_fichaje_hitos(hitos, _User(), date(2026, 6, 4), {})
    assert len(out) == 2
    assert any("fichó" in (h.get("descripcion") or "").lower() for h in out)
    assert any("17:05" in (h.get("descripcion") or "") for h in out)

