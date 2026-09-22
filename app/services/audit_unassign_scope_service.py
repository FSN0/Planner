"""Alcance seguro al desasignar desde auditoría de fichajes.

Regla de producto:
- Siempre se puede cortar el día del conflicto (plan).
- «A futuro» (seguro): también días posteriores con incidencia ABIERTA
  en auditoría (misma persona + misma obra de plan) y plan futuro (≥ hoy)
  sin registro ya validado.
- Días ya validados / fuera de cola → protegidos (no se tocan).
- «Forzar» (permiso cuadrante_pasado): incluye protegidos y pasado.
- El libro de fichajes (marcas) es inmutable: aquí solo se toca Asignacion.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

ESTADOS_AUDITORIA_ABIERTA = frozenset({
    'Conflicto',
    'Disputa',
    'Paracaidista',
    'Ausencia',
    'Sin_Registro',
})


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return None


def classify_unassign_dates(
    *,
    conflict_fecha: date,
    hoy: date,
    assignment_dates: Iterable[date],
    open_audit_dates: Iterable[date],
    validated_dates: Iterable[date],
    force: bool = False,
) -> dict:
    """Clasifica fechas a cortar vs protegidas (sin I/O).

    ``assignment_dates``: días con asignación (o inercia) en la obra.
    ``open_audit_dates``: días con RegistroFichaje abierto (cola auditoría)
        para esa obra de plan.
    ``validated_dates``: días con registro cerrado/validado ligado a esa obra.
    """
    conflict_fecha = _as_date(conflict_fecha)
    hoy = _as_date(hoy) or conflict_fecha
    if not conflict_fecha:
        return {
            'cut_dates': [],
            'protected_dates': [],
            'open_audit_dates': [],
            'pending_plan_dates': [],
        }

    assigns = {d for d in (_as_date(x) for x in assignment_dates) if d}
    opens = {d for d in (_as_date(x) for x in open_audit_dates) if d and d >= conflict_fecha}
    validated = {d for d in (_as_date(x) for x in validated_dates) if d and d >= conflict_fecha}

    cut: set[date] = set()
    protected: set[date] = set()
    pending_plan: set[date] = set()

    # Día del conflicto: siempre candidato (el liberar del desvío también lo toca).
    cut.add(conflict_fecha)

    # Incidencias abiertas posteriores (o el mismo día ya incluido).
    for d in opens:
        if d >= conflict_fecha:
            cut.add(d)

    # Plan futuro sin validar: asignación ≥ hoy, no protegida.
    for d in assigns:
        if d < conflict_fecha:
            continue
        if d in validated and not force:
            protected.add(d)
            continue
        if d >= hoy and d not in opens:
            # Sin incidencia abierta: cortar solo si no está validado (o force).
            if force or d not in validated:
                cut.add(d)
                pending_plan.add(d)

    if force:
        # Todo assignment ≥ conflicto, más opens.
        for d in assigns:
            if d >= conflict_fecha:
                cut.add(d)
        for d in opens:
            if d >= conflict_fecha:
                cut.add(d)
        protected.clear()
    else:
        # Protegidos: validados que no sean el día del conflicto (ese sí se corta).
        for d in validated:
            if d == conflict_fecha:
                continue
            if d in cut and d not in opens:
                # Estaba en cut solo por pending plan — sacar si validado.
                cut.discard(d)
            if d not in opens:
                protected.add(d)
        # Si un día está abierto en auditoría, gana el corte aunque hubiera
        # otro registro raro: opens ya están en cut.

    cut_sorted = sorted(cut)
    return {
        'cut_dates': cut_sorted,
        'protected_dates': sorted(protected - set(cut_sorted)),
        'open_audit_dates': sorted(opens),
        'pending_plan_dates': sorted(pending_plan & set(cut_sorted)),
    }


def collect_audit_unassign_scope(
    *,
    user_id: int,
    obra_id: int,
    conflict_fecha: date,
    force: bool = False,
    hoy: date | None = None,
) -> dict:
    """Consulta BD y devuelve fechas a desasignar (solo plan; no toca ledger)."""
    from app.models import Asignacion, RegistroFichaje
    from app.utils.timezone_utils import today_local

    hoy = hoy or today_local()
    user_id = int(user_id)
    obra_id = int(obra_id)

    assigns = {
        a.fecha
        for a in Asignacion.query.filter(
            Asignacion.user_id == user_id,
            Asignacion.obra_id == obra_id,
            Asignacion.fecha >= conflict_fecha,
        ).all()
    }

    regs = (
        RegistroFichaje.query.filter(
            RegistroFichaje.user_id == user_id,
            RegistroFichaje.fecha >= conflict_fecha,
            RegistroFichaje.obra_planificada_id == obra_id,
        ).all()
    )
    open_dates = set()
    validated_dates = set()
    for r in regs:
        if (r.estado or '') in ESTADOS_AUDITORIA_ABIERTA:
            open_dates.add(r.fecha)
        else:
            # Cerrado / histórico / resuelto → protegido
            validated_dates.add(r.fecha)

    result = classify_unassign_dates(
        conflict_fecha=conflict_fecha,
        hoy=hoy,
        assignment_dates=assigns,
        open_audit_dates=open_dates,
        validated_dates=validated_dates,
        force=force,
    )
    result['assignment_dates'] = sorted(assigns)
    result['force'] = bool(force)
    result['open_registro_ids'] = [
        int(r.id)
        for r in regs
        if (r.estado or '') in ESTADOS_AUDITORIA_ABIERTA
        and r.fecha >= conflict_fecha
    ]
    return result


def aplicar_cierre_tras_desasignar_plan(reg, *, actor_id: int | None, nota: str, now=None) -> str:
    """Ajusta un ``RegistroFichaje`` abierto tras cortar el plan.

    - Conflicto/Disputa: solo ack del lado plan (como «Desasignar»).
      El fichaje real sigue pendiente → espejo «sin planificar».
      Si el lado real ya estaba aceptado, cierra del todo (Resuelto_Movido).
    - Paracaidista: no tocar (es lado real; no depende del plan cortado).
    - Ausencia / Sin_Registro / resto: Resuelto_Falta.

    Devuelve ``'plan_acked'`` | ``'closed'`` | ``'skipped'``.
    """
    from app.utils.timezone_utils import utc_now

    if now is None:
        now = utc_now()

    estado = (getattr(reg, 'estado', None) or '').strip()

    if estado == 'Paracaidista':
        return 'skipped'

    if estado in ('Conflicto', 'Disputa'):
        from app.services.desvio_fichaje_service import DECISION_LIBERAR

        if not getattr(reg, 'desvio_ack_plan_at', None):
            reg.desvio_decision_plan = DECISION_LIBERAR
            reg.desvio_ack_plan_at = now
            reg.desvio_ack_plan_by_id = actor_id

        prev_nota = (getattr(reg, 'notas_resolucion', None) or '').strip()
        reg.notas_resolucion = f"{prev_nota} {nota}".strip() if prev_nota else nota

        if getattr(reg, 'desvio_ack_real_at', None):
            prev = estado or None
            if prev and not (getattr(reg, 'estado_antes_resolucion', None) or '').strip():
                reg.estado_antes_resolucion = prev
            reg.estado = 'Resuelto_Movido'
            reg.resuelto_por_id = actor_id
            reg.fecha_auditoria = now
            return 'closed'

        # Plan liberado; real pendiente (sigue en cola como desvío parcial).
        return 'plan_acked'

    prev = estado or None
    if prev and not (getattr(reg, 'estado_antes_resolucion', None) or '').strip():
        reg.estado_antes_resolucion = prev
    reg.estado = 'Resuelto_Falta'
    reg.resuelto_por_id = actor_id
    reg.fecha_auditoria = now
    reg.notas_resolucion = nota
    return 'closed'


def cerrar_incidencias_abiertas_desasignadas(
    *,
    user_id: int,
    obra_id: int,
    desde_fecha: date,
    actor_id: int | None,
    exclude_registro_id: int | None = None,
    origen_fecha: date | None = None,
    notas_extra: str | None = None,
) -> list[int]:
    """Cierra / ack-plan en auditoría las incidencias abiertas de esa obra.

    No toca el libro de fichajes: solo cambia el ``RegistroFichaje``.
    En Conflicto/Disputa no mata el lado real (queda pendiente de aceptar).
    Devuelve IDs tocados (cerrados o con plan ack).
    """
    from app.models import RegistroFichaje
    from app.utils.timezone_utils import utc_now

    user_id = int(user_id)
    obra_id = int(obra_id)
    q = RegistroFichaje.query.filter(
        RegistroFichaje.user_id == user_id,
        RegistroFichaje.obra_planificada_id == obra_id,
        RegistroFichaje.fecha >= desde_fecha,
        RegistroFichaje.estado.in_(tuple(ESTADOS_AUDITORIA_ABIERTA)),
    )
    if exclude_registro_id:
        q = q.filter(RegistroFichaje.id != int(exclude_registro_id))

    origen = (origen_fecha or desde_fecha).strftime('%d/%m/%Y')
    nota = (
        f"Desasignado en lote desde la incidencia del {origen} "
        f"(mismo operario y obra de plan)."
    )
    if notas_extra:
        nota = f"{nota} Comentario: {notas_extra}".strip()

    touched = []
    now = utc_now()
    for reg in q.all():
        result = aplicar_cierre_tras_desasignar_plan(
            reg, actor_id=actor_id, nota=nota, now=now,
        )
        if result != 'skipped':
            touched.append(int(reg.id))
    return touched
