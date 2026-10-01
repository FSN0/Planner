"""Disponibilidad de flota: coches libres (sin plan o conductor de ausencia)."""
from __future__ import annotations

from datetime import date, timedelta

from app.models import (
    LEAVE_STATUS_APROBADA,
    AsignacionVehiculo,
    User,
    Vehiculo,
)
from app.services.leave_service import build_leaves_by_user, leave_covering
from app.utils.timezone_utils import today_local

# Colores ficha/calendario de vehículo (regla de negocio única):
#   Azul   = planificado (aún no hay dato Odoo; típico futuro / hoy)
#   Verde  = cumplido (planificado + km Odoo, misma persona)
#   Naranja = conflicto (km sin plan | plan pasado sin km | otro conductor)
#   Teal   = libre por ausencia (hay plan, pero el conductor está de vacaciones/baja;
#            el coche se puede usar — misma regla que «Coches libres»)
VEHICLE_COLOR_PLAN = '#0ea5e9'
VEHICLE_COLOR_CUMPLIDO = '#16a34a'
VEHICLE_COLOR_CONFLICTO = '#f59e0b'
VEHICLE_COLOR_AUSENCIA = '#0d9488'  # libre práctico (no es “ocupado”)
VEHICLE_COLOR_ODOO_EXT = '#64748b'  # conductor Odoo no matcheado en el programa

# Alias legados (imports antiguos)
VEHICLE_COLOR_PLAN_OK = VEHICLE_COLOR_PLAN
VEHICLE_COLOR_EFECTIVO = VEHICLE_COLOR_CUMPLIDO
VEHICLE_COLOR_PLAN_MUERTO = VEHICLE_COLOR_AUSENCIA
VEHICLE_COLOR_ODOO_SOLO = VEHICLE_COLOR_ODOO_EXT


HORIZON_MONTHS_ALLOWED = (1, 2, 3, 6)
DEFAULT_HORIZON_MONTHS = 2

MOTIVO_SIN_PLAN = 'sin_plan'
MOTIVO_AUSENCIA = 'ausencia'
MOTIVO_MIXTO = 'mixto'

MOTIVO_LABELS = {
    MOTIVO_SIN_PLAN: 'Sin planificar',
    MOTIVO_AUSENCIA: 'Ausencia',
    MOTIVO_MIXTO: 'Sin plan / Ausencia',
}


def parse_horizon_months(raw, default=DEFAULT_HORIZON_MONTHS):
    try:
        months = int(raw)
    except (TypeError, ValueError):
        return default
    if months not in HORIZON_MONTHS_ALLOWED:
        return default
    return months


def horizon_end(start: date, months: int) -> date:
    """Fin inclusivo aproximado: start + months*30 días − 1."""
    months = max(1, int(months))
    return start + timedelta(days=months * 30) - timedelta(days=1)


def _user_label(user):
    if not user:
        return None
    return f"{(user.name or '').strip()} {(user.lastname or '').strip()}".strip() or f"#{user.id}"


def _vehiculo_label(v):
    if not v:
        return '—'
    return v.label() if hasattr(v, 'label') else (v.matricula or v.nombre or f'#{v.id}')


def _day_free_info(av, leaves_idx, users):
    """
    Si el día está libre para el vehículo: (True, motivo, leave_tipo, user|None).
    Si está ocupado de verdad: (False, None, None, None).
    """
    if not av:
        return True, MOTIVO_SIN_PLAN, None, None
    leave = leave_covering(leaves_idx.get(av.user_id, []), av.fecha)
    if leave and leave.estado == LEAVE_STATUS_APROBADA:
        tipo = (leave.tipo or 'Ausencia').strip() or 'Ausencia'
        return True, MOTIVO_AUSENCIA, tipo, users.get(av.user_id)
    return False, None, None, None


def list_free_vehicle_stretches(fecha_desde=None, fecha_hasta=None, solo_activos=True):
    """
    Tramos consecutivos en los que un vehículo está libre.

    Libre un día = sin AsignacionVehiculo, o el conductor planificado tiene
    ausencia aprobada ese día.

    Si el tramo llega al fin del horizonte y sigue libre (sin más plan),
    se marca abierto=True: no hay «hasta» real, solo «desde».

    Returns list of dicts ordered by vehículo, luego fecha_inicio.
    """
    start = fecha_desde or today_local()
    end = fecha_hasta or horizon_end(start, DEFAULT_HORIZON_MONTHS)
    if end < start:
        start, end = end, start

    q = Vehiculo.query
    if solo_activos:
        q = q.filter_by(active=True)
    vehiculos = q.order_by(
        Vehiculo.matricula.asc().nullslast(), Vehiculo.nombre.asc()
    ).all()
    if not vehiculos:
        return []

    veh_ids = [v.id for v in vehiculos]
    veh_by_id = {v.id: v for v in vehiculos}

    asignaciones = AsignacionVehiculo.query.filter(
        AsignacionVehiculo.vehiculo_id.in_(veh_ids),
        AsignacionVehiculo.fecha >= start,
        AsignacionVehiculo.fecha <= end,
    ).all()
    planned = {(a.vehiculo_id, a.fecha): a for a in asignaciones}

    user_ids = {a.user_id for a in asignaciones if a.user_id}
    leaves_idx = build_leaves_by_user(list(user_ids), start, end) if user_ids else {}
    users = {
        u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    stretches = []

    for vid in veh_ids:
        cur = None

        def flush():
            nonlocal cur
            if not cur:
                return
            motivos = cur['motivos']
            if motivos == {MOTIVO_AUSENCIA}:
                motivo = MOTIVO_AUSENCIA
            elif motivos == {MOTIVO_SIN_PLAN}:
                motivo = MOTIVO_SIN_PLAN
            else:
                motivo = MOTIVO_MIXTO
            leave_tipos = sorted(t for t in cur['leave_tipos'] if t)
            conductor = cur.get('conductor')
            # Abierto = llega al fin del horizonte y no es solo ausencia acotada
            # (sigue libre «en adelante» dentro de lo que miramos).
            abierto = (
                cur['fecha_fin'] == end
                and motivo in (MOTIVO_SIN_PLAN, MOTIVO_MIXTO)
            )
            stretches.append({
                'vehiculo_id': vid,
                'vehiculo': veh_by_id[vid],
                'vehiculo_label': _vehiculo_label(veh_by_id[vid]),
                'fecha_inicio': cur['fecha_inicio'],
                'fecha_fin': cur['fecha_fin'],
                'dias': (cur['fecha_fin'] - cur['fecha_inicio']).days + 1,
                'abierto': abierto,
                'motivo': motivo,
                'motivo_label': MOTIVO_LABELS[motivo],
                'ausencia_tipos': leave_tipos,
                'conductor': conductor,
                'conductor_id': cur.get('conductor_id'),
                'conductor_label': _user_label(conductor) if conductor else None,
            })
            cur = None

        day = start
        while day <= end:
            av = planned.get((vid, day))
            free, motivo, leave_tipo, conductor = _day_free_info(av, leaves_idx, users)

            if not free:
                flush()
                day += timedelta(days=1)
                continue

            conductor_id = conductor.id if conductor else None
            if (
                cur is not None
                and day == cur['fecha_fin'] + timedelta(days=1)
                and (
                    cur['conductor_id'] is None
                    or conductor_id is None
                    or cur['conductor_id'] == conductor_id
                )
            ):
                cur['fecha_fin'] = day
                cur['motivos'].add(motivo)
                if leave_tipo:
                    cur['leave_tipos'].add(leave_tipo)
                if cur['conductor_id'] is None and conductor is not None:
                    cur['conductor'] = conductor
                    cur['conductor_id'] = conductor_id
            else:
                flush()
                cur = {
                    'fecha_inicio': day,
                    'fecha_fin': day,
                    'motivos': {motivo},
                    'leave_tipos': {leave_tipo} if leave_tipo else set(),
                    'conductor': conductor,
                    'conductor_id': conductor_id,
                }
            day += timedelta(days=1)
        flush()

    # Por fecha (próximos primero), luego coche
    stretches.sort(key=lambda s: (s['fecha_inicio'], s['vehiculo_label'] or ''))
    return stretches


def free_vehicle_summary(stretches):
    """KPIs ligeros sobre el listado."""
    vehiculos = {s['vehiculo_id'] for s in stretches}
    por_ausencia = sum(
        1 for s in stretches if s['motivo'] in (MOTIVO_AUSENCIA, MOTIVO_MIXTO)
    )
    sin_plan = sum(1 for s in stretches if s['motivo'] == MOTIVO_SIN_PLAN)
    return {
        'tramos': len(stretches),
        'vehiculos': len(vehiculos),
        'por_ausencia': por_ausencia,
        'sin_plan': sin_plan,
        'mixtos': sum(1 for s in stretches if s['motivo'] == MOTIVO_MIXTO),
        'dias_libres': sum(
            s['dias'] for s in stretches if not s.get('abierto')
        ),
    }
