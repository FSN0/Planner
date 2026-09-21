"""Clasificación de fechas al desasignar desde auditoría."""
from datetime import date, timedelta

from app.services.audit_unassign_scope_service import classify_unassign_dates


def test_conflict_day_always_cut():
    hoy = date(2026, 9, 21)
    conflict = date(2026, 9, 10)
    out = classify_unassign_dates(
        conflict_fecha=conflict,
        hoy=hoy,
        assignment_dates=[conflict],
        open_audit_dates=[conflict],
        validated_dates=[],
        force=False,
    )
    assert conflict in out['cut_dates']


def test_validated_later_days_protected():
    hoy = date(2026, 9, 21)
    conflict = date(2026, 9, 10)
    ok = date(2026, 9, 11)
    out = classify_unassign_dates(
        conflict_fecha=conflict,
        hoy=hoy,
        assignment_dates=[conflict, ok, date(2026, 9, 22)],
        open_audit_dates=[conflict],
        validated_dates=[ok],
        force=False,
    )
    assert conflict in out['cut_dates']
    assert ok in out['protected_dates']
    assert ok not in out['cut_dates']
    assert date(2026, 9, 22) in out['cut_dates']  # plan futuro sin validar


def test_open_audit_later_days_cut():
    hoy = date(2026, 9, 21)
    conflict = date(2026, 9, 10)
    open_later = date(2026, 9, 15)
    out = classify_unassign_dates(
        conflict_fecha=conflict,
        hoy=hoy,
        assignment_dates=[conflict, open_later],
        open_audit_dates=[conflict, open_later],
        validated_dates=[],
        force=False,
    )
    assert open_later in out['cut_dates']
    assert open_later in out['open_audit_dates']


def test_force_includes_validated():
    hoy = date(2026, 9, 21)
    conflict = date(2026, 9, 10)
    ok = date(2026, 9, 11)
    out = classify_unassign_dates(
        conflict_fecha=conflict,
        hoy=hoy,
        assignment_dates=[conflict, ok, date(2026, 9, 25)],
        open_audit_dates=[conflict],
        validated_dates=[ok],
        force=True,
    )
    assert ok in out['cut_dates']
    assert not out['protected_dates']
    assert date(2026, 9, 25) in out['cut_dates']


def test_past_assignment_without_open_audit_not_cut():
    """Entre conflicto y hoy, sin incidencia abierta ni validación: no cortar."""
    hoy = date(2026, 9, 21)
    conflict = date(2026, 9, 10)
    ghost = date(2026, 9, 12)
    out = classify_unassign_dates(
        conflict_fecha=conflict,
        hoy=hoy,
        assignment_dates=[conflict, ghost],
        open_audit_dates=[conflict],
        validated_dates=[],
        force=False,
    )
    assert ghost not in out['cut_dates']


def test_pending_plan_from_today():
    hoy = date(2026, 9, 21)
    conflict = date(2026, 9, 10)
    fut = hoy + timedelta(days=3)
    out = classify_unassign_dates(
        conflict_fecha=conflict,
        hoy=hoy,
        assignment_dates=[conflict, fut],
        open_audit_dates=[conflict],
        validated_dates=[],
        force=False,
    )
    assert fut in out['cut_dates']
    assert fut in out['pending_plan_dates']


def test_open_audit_dates_include_later_ausencia():
    """Día conflicto + ausencia posterior → ambos en cut (para cerrar cola)."""
    hoy = date(2026, 9, 21)
    conflict = date(2026, 9, 10)
    ausencia = date(2026, 9, 12)
    out = classify_unassign_dates(
        conflict_fecha=conflict,
        hoy=hoy,
        assignment_dates=[conflict, ausencia],
        open_audit_dates=[conflict, ausencia],
        validated_dates=[],
        force=False,
    )
    assert conflict in out['cut_dates']
    assert ausencia in out['cut_dates']
    assert ausencia in out['open_audit_dates']
