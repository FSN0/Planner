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


class _FakeReg:
    def __init__(self, **kwargs):
        self.estado = kwargs.get('estado')
        self.estado_antes_resolucion = kwargs.get('estado_antes_resolucion')
        self.desvio_decision_plan = kwargs.get('desvio_decision_plan')
        self.desvio_decision_real = kwargs.get('desvio_decision_real')
        self.desvio_ack_plan_at = kwargs.get('desvio_ack_plan_at')
        self.desvio_ack_real_at = kwargs.get('desvio_ack_real_at')
        self.desvio_ack_plan_by_id = kwargs.get('desvio_ack_plan_by_id')
        self.desvio_ack_real_by_id = kwargs.get('desvio_ack_real_by_id')
        self.resuelto_por_id = kwargs.get('resuelto_por_id')
        self.fecha_auditoria = kwargs.get('fecha_auditoria')
        self.notas_resolucion = kwargs.get('notas_resolucion')


def test_cierre_conflicto_solo_ack_plan():
    from datetime import datetime
    from app.services.audit_unassign_scope_service import aplicar_cierre_tras_desasignar_plan

    reg = _FakeReg(estado='Conflicto')
    now = datetime(2026, 9, 21, 12, 0, 0)
    result = aplicar_cierre_tras_desasignar_plan(
        reg, actor_id=7, nota='lote', now=now,
    )
    assert result == 'plan_acked'
    assert reg.estado == 'Conflicto'
    assert reg.desvio_ack_plan_at == now
    assert reg.desvio_ack_plan_by_id == 7
    assert reg.desvio_decision_plan == 'liberar'
    assert reg.desvio_ack_real_at is None


def test_cierre_conflicto_con_real_ya_ack_resuelve():
    from datetime import datetime
    from app.services.audit_unassign_scope_service import aplicar_cierre_tras_desasignar_plan

    now = datetime(2026, 9, 21, 12, 0, 0)
    reg = _FakeReg(
        estado='Conflicto',
        desvio_ack_real_at=now,
        desvio_ack_real_by_id=3,
    )
    result = aplicar_cierre_tras_desasignar_plan(
        reg, actor_id=7, nota='lote', now=now,
    )
    assert result == 'closed'
    assert reg.estado == 'Resuelto_Movido'
    assert reg.desvio_ack_plan_at == now


def test_cierre_ausencia_resuelto_falta():
    from datetime import datetime
    from app.services.audit_unassign_scope_service import aplicar_cierre_tras_desasignar_plan

    now = datetime(2026, 9, 21, 12, 0, 0)
    reg = _FakeReg(estado='Ausencia')
    result = aplicar_cierre_tras_desasignar_plan(
        reg, actor_id=7, nota='lote', now=now,
    )
    assert result == 'closed'
    assert reg.estado == 'Resuelto_Falta'
    assert reg.estado_antes_resolucion == 'Ausencia'


def test_cierre_paracaidista_skipped():
    from datetime import datetime
    from app.services.audit_unassign_scope_service import aplicar_cierre_tras_desasignar_plan

    reg = _FakeReg(estado='Paracaidista')
    result = aplicar_cierre_tras_desasignar_plan(
        reg, actor_id=7, nota='lote', now=datetime(2026, 9, 21),
    )
    assert result == 'skipped'
    assert reg.estado == 'Paracaidista'
