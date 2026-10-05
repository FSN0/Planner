# app/services/solicitud_service.py
from datetime import datetime, timedelta, date
from collections import defaultdict
import json
import logging
from app import db
from app.utils.timezone_utils import utc_now, today_local
from app.models import Solicitud, Asignacion, User, Festivo
from app.services.email_service import notificar_nueva_solicitud

logger = logging.getLogger(__name__)

_AUTO_COMENTARIO_MARKERS = (
    'Petición automática',
    'Creado desde Planificador',
    'Rango ampliado',
)


def _dates_to_str(dates):
    result = []
    for d in dates:
        if isinstance(d, str):
            result.append(d)
        elif isinstance(d, date):
            result.append(d.strftime('%Y-%m-%d'))
    return sorted(set(result))


def build_comentarios_config(dates, mode='selected', baseline_users_by_day=None):
    dates_str = _dates_to_str(dates)
    payload = {
        'mode': mode,
        'dates': dates_str,
        'original_dates': dates_str,
    }
    if baseline_users_by_day is not None:
        payload['baseline_users_by_day'] = baseline_users_by_day
    return json.dumps(payload)


def snapshot_generica_baseline(obra_id, dates):
    """Quiénes ya estaban en la obra esos días al crear la solicitud."""
    dates = [d for d in (dates or []) if d]
    if not obra_id or not dates:
        return {}
    rows = (
        Asignacion.query.filter(
            Asignacion.obra_id == int(obra_id),
            Asignacion.fecha.in_(dates),
        ).all()
    )
    by_day = defaultdict(set)
    for a in rows:
        by_day[a.fecha.strftime('%Y-%m-%d')].add(int(a.user_id))
    return {day: sorted(uids) for day, uids in by_day.items()}


def _parse_solicitud_config(solicitud):
    raw = (getattr(solicitud, 'comentarios', None) or '').strip()
    if not raw.startswith('{'):
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_solicitud_config(solicitud, config):
    plain = None
    raw = (getattr(solicitud, 'comentarios', None) or '').strip()
    if raw and not raw.startswith('{'):
        if not any(marker in raw for marker in _AUTO_COMENTARIO_MARKERS):
            plain = raw
    if plain and 'mensaje_original' not in config:
        config['mensaje_original'] = plain
    solicitud.comentarios = json.dumps(config)


def merge_comentarios_dates(existing_comentarios, new_dates, mode='selected'):
    dates_str = _dates_to_str(new_dates)
    try:
        if existing_comentarios and existing_comentarios.strip().startswith('{'):
            config = json.loads(existing_comentarios)
        else:
            config = {}
    except Exception:
        config = {}

    merged = sorted(set(config.get('dates', []) + dates_str))
    config['mode'] = config.get('mode', mode)
    config['dates'] = merged
    if not config.get('original_dates'):
        config['original_dates'] = merged
    else:
        config['original_dates'] = sorted(set(config.get('original_dates', []) + dates_str))
    return json.dumps(config)


def merge_notas(existing_notas, new_notas):
    new_notas = (new_notas or '').strip()
    if not new_notas:
        return existing_notas
    existing = (existing_notas or '').strip()
    if not existing:
        return new_notas
    if new_notas in existing:
        return existing
    return f"{existing}\n---\n{new_notas}"


def log_nueva_solicitud(solicitud):
    """Registra en SystemLog la creación de una solicitud (solo altas nuevas)."""
    from app.utils import register_log
    from app.models import Obra

    tipo = (solicitud.tipo or '').upper()
    accion = (getattr(solicitud, 'accion', None) or 'ASIGNAR').upper()
    if tipo == 'GENERICA':
        action = 'Nueva solicitud GENERICA'
    elif accion == 'DESASIGNAR':
        action = 'Nueva solicitud DESASIGNAR'
    else:
        action = 'Nueva solicitud ASIGNAR'

    obra = getattr(solicitud, 'obra', None)
    if obra is None and solicitud.obra_id:
        obra = Obra.query.get(solicitud.obra_id)
    if obra:
        obra_txt = f"{obra.codigo or ''} {obra.nombre}".strip()
    else:
        obra_txt = f"obra #{solicitud.obra_id}"

    emp_txt = None
    if solicitud.empleado_id:
        emp = getattr(solicitud, 'empleado', None)
        if emp is None:
            emp = User.query.get(solicitud.empleado_id)
        if emp:
            emp_txt = f"{emp.name} {emp.lastname}".strip()

    requester = getattr(solicitud, 'requested_by', None)
    if requester is None and solicitud.requested_by_id:
        requester = User.query.get(solicitud.requested_by_id)
    if requester:
        req_txt = f"{requester.name} {requester.lastname}".strip()
    else:
        req_txt = f"user #{solicitud.requested_by_id}"

    fi = solicitud.fecha_inicio.strftime('%Y-%m-%d') if solicitud.fecha_inicio else '?'
    ff = solicitud.fecha_fin.strftime('%Y-%m-%d') if solicitud.fecha_fin else '?'

    parts = [f"Obra: {obra_txt}"]
    if emp_txt:
        parts.append(f"Empleado: {emp_txt}")
    parts.append(f"Fechas: {fi} → {ff}")
    parts.append(f"Solicitante: {req_txt}")

    register_log(
        user_id=solicitud.requested_by_id,
        category='solicitud',
        action=action,
        detail=' | '.join(parts),
        target_user_id=solicitud.empleado_id if tipo == 'CONCRETA' else None,
    )


def _solicitud_cierre_marker(solicitud):
    """Rastro de cierre: auto (cuadrante) o manual (desde la solicitud)."""
    config = _parse_solicitud_config(solicitud)
    if not isinstance(config, dict):
        return None, None
    if isinstance(config.get('auto_cierre'), dict):
        return 'auto_cierre', config['auto_cierre']
    if isinstance(config.get('cierre'), dict):
        return 'cierre', config['cierre']
    return None, None


def solicitud_cerrada_desde_solicitud(solicitud):
    """True si se cerró asignando desde la ficha de solicitud (no autocierre)."""
    if getattr(solicitud, 'auto_fulfilled', False):
        return False
    kind, _ = _solicitud_cierre_marker(solicitud)
    return kind == 'cierre'


def get_solicitud_auto_cierre_texto(solicitud):
    """Texto corto de trazabilidad del cierre (auto o desde solicitud)."""
    kind, ac = _solicitud_cierre_marker(solicitud)
    if not ac:
        if not getattr(solicitud, 'auto_fulfilled', False):
            return None
        return None
    if kind == 'auto_cierre' and not getattr(solicitud, 'auto_fulfilled', False):
        return None
    motivo_labels = {
        'asignaciones_cuadrante': 'cubierta en cuadrante',
        'asignacion_desde_solicitud': 'asignada desde la solicitud',
        'cubierto_accionable_resto_pasado': 'cubierto lo operable; resto en pasado',
        'cubierto_antes_de_vencer': 'cubierta antes de vencer',
        'vencida_sin_dias_accionables': 'vencida (sin días accionables)',
        'vencida_sin_atender': 'vencida sin atender',
        'vencida_cobertura_parcial': 'vencida con cobertura parcial',
        'desasignacion_completa': 'desasignación completa',
    }
    parts = []
    motivo = ac.get('motivo')
    if motivo:
        parts.append(motivo_labels.get(motivo, str(motivo)))
    at = ac.get('at')
    if at:
        parts.append(str(at).replace('T', ' ')[:19])
    nombre = (ac.get('actor_nombre') or '').strip()
    if nombre:
        parts.append(nombre)
    if not parts:
        return None
    return ' · '.join(parts)


def get_solicitud_notas(solicitud):
    if getattr(solicitud, 'notas', None):
        text = solicitud.notas.strip()
        if text:
            return text

    comentarios = solicitud.comentarios
    if not comentarios:
        return None

    if comentarios.strip().startswith('{'):
        try:
            data = json.loads(comentarios)
            legacy = (data.get('mensaje_original') or '').strip()
            return legacy or None
        except Exception:
            return None

    if any(marker in comentarios for marker in _AUTO_COMENTARIO_MARKERS):
        return None
    text = comentarios.strip()
    return text or None

def get_solicitud_valid_dates(solicitud):
    """Días que realmente pide la solicitud (original_dates / laborables, no el span calendario)."""
    start = solicitud.fecha_inicio
    end = solicitud.fecha_fin
    if not start or not end:
        return []

    explicit_dates = []
    if solicitud.comentarios:
        try:
            raw = solicitud.comentarios.strip()
            if raw.startswith('{'):
                data = json.loads(raw)
                fechas_base = data.get('original_dates') or data.get('dates', [])
                if fechas_base:
                    explicit_dates = [
                        datetime.strptime(d, '%Y-%m-%d').date() for d in fechas_base
                    ]
        except Exception:
            explicit_dates = []

    if explicit_dates:
        return sorted({d for d in explicit_dates if start <= d <= end})

    festivos = Festivo.query.filter(Festivo.fecha >= start, Festivo.fecha <= end).all()
    fechas_festivas = {f.fecha for f in festivos}
    valid_dates = []
    curr = start
    while curr <= end:
        if curr.weekday() < 5 and curr not in fechas_festivas:
            valid_dates.append(curr)
        curr += timedelta(days=1)

    if valid_dates:
        return valid_dates

    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def compute_generica_coverage(solicitud, counts_by_day=None):
    """
    Cobertura GENERICA unificada:
    - Con baseline (solicitudes nuevas): cuentan personas en obra ese día
      que no estaban al crear la petición, más las vinculadas a la solicitud.
    - Sin baseline (legacy): solo asignaciones con solicitud_id = esta solicitud.
    - progreso (cantidad_cubierta) = mínimo de personas efectivas por día válido
    - % = jornadas cubiertas (tope por día = solicitadas) / (solicitadas × días válidos)
    """
    valid_dates = get_solicitud_valid_dates(solicitud)
    requested = solicitud.cantidad_solicitada or 1
    config = _parse_solicitud_config(solicitud)
    baseline = config.get('baseline_users_by_day')
    has_baseline = isinstance(baseline, dict)

    if counts_by_day is None:
        counts_by_day = {d: 0 for d in valid_dates}
        if valid_dates and getattr(solicitud, 'id', None):
            asignaciones = Asignacion.query.filter(
                Asignacion.obra_id == solicitud.obra_id,
                Asignacion.fecha.in_(valid_dates),
            ).all()
            users_by_day = defaultdict(set)
            linked_by_day = defaultdict(set)
            for a in asignaciones:
                users_by_day[a.fecha].add(int(a.user_id))
                if a.solicitud_id == solicitud.id:
                    linked_by_day[a.fecha].add(int(a.user_id))

            for d in valid_dates:
                current = users_by_day.get(d, set())
                linked = linked_by_day.get(d, set())
                if has_baseline:
                    base = {
                        int(uid)
                        for uid in (baseline.get(d.strftime('%Y-%m-%d')) or [])
                    }
                    effective = (current - base) | linked
                    counts_by_day[d] = len(effective)
                else:
                    counts_by_day[d] = len(linked)

    min_coverage = min(counts_by_day.values()) if counts_by_day else 0
    jornadas_filled = sum(min(c, requested) for c in counts_by_day.values())
    jornadas_needed = requested * len(valid_dates) if valid_dates else 0
    if jornadas_needed > 0:
        pct = int((jornadas_filled / jornadas_needed) * 100)
    else:
        pct = 0

    return {
        'valid_dates': valid_dates,
        'counts_by_day': counts_by_day,
        'requested': requested,
        'min_coverage': min_coverage,
        'jornadas_filled': jornadas_filled,
        'jornadas_needed': jornadas_needed,
        'pct': min(pct, 100),
        'total_assignments': sum(counts_by_day.values()) if counts_by_day else 0,
        'has_baseline': has_baseline,
    }


def claim_user_to_open_genericas(obra_id, user_id, fecha):
    """
    Etiqueta la asignación (obra, user, fecha) a genéricas abiertas con cupo.
    No es requisito para contar (con baseline cuenta por presencia); da trazabilidad.
    """
    if not obra_id or not user_id or not fecha:
        return 0
    obra_id = int(obra_id)
    user_id = int(user_id)

    asig = Asignacion.query.filter_by(
        obra_id=obra_id, user_id=user_id, fecha=fecha,
    ).first()
    if not asig:
        return 0
    if asig.solicitud_id:
        return 0

    sols = (
        Solicitud.query.filter(
            Solicitud.obra_id == obra_id,
            Solicitud.tipo.in_(['GENERICA', 'generica']),
            Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO']),
            Solicitud.fecha_inicio <= fecha,
            Solicitud.fecha_fin >= fecha,
        )
        .order_by(Solicitud.created_at.asc(), Solicitud.id.asc())
        .all()
    )
    claimed = 0
    for sol in sols:
        valid = get_solicitud_valid_dates(sol)
        if fecha not in valid:
            continue
        requested = sol.cantidad_solicitada or 1
        linked_count = Asignacion.query.filter_by(
            obra_id=obra_id, solicitud_id=sol.id, fecha=fecha,
        ).count()
        if linked_count >= requested:
            continue
        config = _parse_solicitud_config(sol)
        baseline = config.get('baseline_users_by_day')
        if isinstance(baseline, dict):
            base = {
                int(uid) for uid in (baseline.get(fecha.strftime('%Y-%m-%d')) or [])
            }
            if user_id in base:
                continue
        asig.solicitud_id = sol.id
        db.session.add(asig)
        claimed += 1
        break
    if claimed:
        db.session.flush()
    return claimed


def reconcile_solicitudes_after_cuadrante_change(
    obra_id, user_id, fecha, resolved_by_id=None,
):
    """
    Punto único post-asignación/desasignación: acredita genéricas y recalcula.
    Seguro de llamar desde CoreAssignmentService (no debe tumbar el cuadrante).
    """
    try:
        if not obra_id or not fecha or not user_id:
            return
        claim_user_to_open_genericas(obra_id, user_id, fecha)
        update_solicitudes_for_assignment(
            obra_id, user_id, fecha, resolved_by_id=resolved_by_id,
        )
    except Exception:
        logger.exception(
            'reconcile solicitudes falló obra=%s user=%s fecha=%s',
            obra_id, user_id, fecha,
        )


def update_solicitudes_for_assignment(
    obra_id, worker_id, fecha, resolved_by_id=None, *, origen_cierre='cuadrante',
):
    worker_id = int(worker_id)
    if obra_id:
        obra_id = int(obra_id)

    worker = User.query.get(worker_id)
    if not worker:
        return

    qs = Solicitud.query.filter(
        Solicitud.obra_id == obra_id,
        Solicitud.estado.in_(["PENDIENTE", "EN_PROCESO"]),
        Solicitud.fecha_inicio <= fecha,
        Solicitud.fecha_fin >= fecha,
    ).all()

    for sol in qs:
        tipo = (sol.tipo or '').upper()
        if tipo == "CONCRETA":
            emp_id = sol.empleado_id
            try:
                emp_id = int(emp_id) if emp_id is not None else None
            except (TypeError, ValueError):
                emp_id = None
            if emp_id != worker_id:
                continue
            # Vincular la asignación a esta concreta (trazabilidad).
            _link_concreta_assignment(sol, worker_id, fecha)

        estado_previo = sol.estado
        _recalculate_solicitud_coverage(
            sol, resolved_by_id, origen_cierre=origen_cierre,
        )

        # Red de seguridad: si ya no queda ningún día pendiente, cerrar sí o sí.
        if sol.estado in ('PENDIENTE', 'EN_PROCESO'):
            pending = get_solicitud_pending_dates(sol)
            if not pending:
                automatico = origen_cierre != 'solicitud'
                _mark_auto_cumplida(
                    sol, resolved_by_id=resolved_by_id, automatico=automatico,
                )

        if estado_previo != 'CUMPLIDA' and sol.estado == 'CUMPLIDA':
            from app.services.email_service import notificar_resolucion_solicitud
            admin_user = User.query.get(resolved_by_id) if resolved_by_id else None
            admin_name = f"{admin_user.name} {admin_user.lastname}" if admin_user else "Sistema Automático"
            try:
                notificar_resolucion_solicitud(sol, admin_name, worker_id=worker_id)
            except Exception:
                pass


def _link_concreta_assignment(solicitud, worker_id, fecha):
    """Si la asignación del día no tiene solicitud_id, la enlaza a esta concreta."""
    if not getattr(solicitud, 'id', None):
        return
    asig = Asignacion.query.filter_by(
        obra_id=int(solicitud.obra_id),
        user_id=int(worker_id),
        fecha=fecha,
    ).first()
    if not asig:
        return
    if asig.solicitud_id is None:
        asig.solicitud_id = solicitud.id
        db.session.add(asig)
        db.session.flush()


def _mark_auto_cumplida(solicitud, resolved_by_id=None, *, automatico=True):
    """Cierre total por cobertura (cuadrante = auto, ficha solicitud = manual)."""
    motivo = (
        'asignaciones_cuadrante' if automatico else 'asignacion_desde_solicitud'
    )
    _mark_auto_cierre(
        solicitud,
        estado='CUMPLIDA',
        motivo=motivo,
        resolved_by_id=resolved_by_id,
        automatico=automatico,
    )


def _mark_auto_cierre(solicitud, *, estado, motivo, resolved_by_id=None, automatico=True):
    """Cierre por cobertura (CUMPLIDA o CERRADA_PARCIAL) con rastro."""
    solicitud.estado = estado
    solicitud.auto_fulfilled = bool(automatico)
    solicitud.resolved_at = utc_now()
    if resolved_by_id:
        solicitud.resolved_by_id = resolved_by_id
    if estado in ('CUMPLIDA', 'CERRADA_PARCIAL') and not solicitud.cantidad_cubierta:
        if (solicitud.tipo or '').upper() != 'GENERICA':
            solicitud.cantidad_cubierta = solicitud.cantidad_solicitada or 0

    config = _parse_solicitud_config(solicitud)
    actor_name = None
    if resolved_by_id:
        actor = User.query.get(resolved_by_id)
        if actor:
            actor_name = f'{(actor.name or "").strip()} {(actor.lastname or "").strip()}'.strip()
    payload = {
        'at': utc_now().isoformat(timespec='seconds'),
        'motivo': motivo,
        'estado': estado,
        'actor_id': resolved_by_id,
        'actor_nombre': actor_name,
    }
    if automatico:
        config.pop('cierre', None)
        config['auto_cierre'] = payload
    else:
        config.pop('auto_cierre', None)
        config['cierre'] = payload
    _write_solicitud_config(solicitud, config)


def _clear_auto_cierre_marker(solicitud):
    solicitud.auto_fulfilled = False
    config = _parse_solicitud_config(solicitud)
    changed = False
    if 'auto_cierre' in config:
        config.pop('auto_cierre', None)
        changed = True
    if 'cierre' in config:
        config.pop('cierre', None)
        changed = True
    if changed:
        _write_solicitud_config(solicitud, config)


def mark_solicitud_cierre_desde_ficha(solicitud, resolved_by_id=None):
    """
    Si la solicitud ya quedó CUMPLIDA/CERRADA_PARCIAL por asignar desde su ficha,
    anota cierre manual (no «Autocerrada»).
    """
    if solicitud.estado not in ('CUMPLIDA', 'CERRADA_PARCIAL'):
        return False
    kind, ac = _solicitud_cierre_marker(solicitud)
    motivo = 'asignacion_desde_solicitud'
    if (
        solicitud.estado == 'CERRADA_PARCIAL'
        and isinstance(ac, dict)
        and ac.get('motivo')
        and ac.get('motivo') not in ('asignaciones_cuadrante', 'asignacion_desde_solicitud')
    ):
        motivo = ac['motivo']
    _mark_auto_cierre(
        solicitud,
        estado=solicitud.estado,
        motivo=motivo,
        resolved_by_id=resolved_by_id or getattr(solicitud, 'resolved_by_id', None),
        automatico=False,
    )
    return True


def get_solicitud_actionable_dates(solicitud, hoy=None):
    """Días de la solicitud que aún se pueden tocar (hoy y futuro)."""
    hoy = hoy or today_local()
    return [d for d in get_solicitud_valid_dates(solicitud) if d >= hoy]


def get_solicitud_past_dates(solicitud, hoy=None):
    hoy = hoy or today_local()
    return [d for d in get_solicitud_valid_dates(solicitud) if d < hoy]


def get_solicitud_pending_dates(solicitud):
    """
    Días que aún faltan por cubrir de una solicitud abierta.
    Sirve para pintar en calendarios solo lo pendiente (no el rango original entero).
    """
    tipo = (getattr(solicitud, 'tipo', None) or '').upper()
    valid = get_solicitud_valid_dates(solicitud)
    if not valid:
        return []

    if tipo == 'GENERICA':
        cov = compute_generica_coverage(solicitud)
        requested = cov['requested'] or 1
        counts = cov.get('counts_by_day') or {}
        return [d for d in valid if counts.get(d, 0) < requested]

    accion = getattr(solicitud, 'accion', 'ASIGNAR') or 'ASIGNAR'
    empleado_id = getattr(solicitud, 'empleado_id', None)
    obra_id = getattr(solicitud, 'obra_id', None)
    if not empleado_id or not obra_id:
        return list(valid)

    asignados = {
        a.fecha
        for a in Asignacion.query.filter(
            Asignacion.obra_id == obra_id,
            Asignacion.user_id == empleado_id,
            Asignacion.fecha.in_(valid),
        ).all()
    }

    if accion == 'DESASIGNAR':
        # Pendiente = días en los que aún está asignado.
        return [d for d in valid if d in asignados]
    # ASIGNAR: pendiente = días en los que aún NO está.
    return [d for d in valid if d not in asignados]


def collapse_dates_to_ranges(dates):
    """Agrupa fechas sueltas en tramos contiguos (start, end_inclusive)."""
    ordered = sorted({d for d in (dates or []) if d})
    if not ordered:
        return []
    ranges = []
    start = prev = ordered[0]
    for d in ordered[1:]:
        if d == prev + timedelta(days=1):
            prev = d
            continue
        ranges.append((start, prev))
        start = prev = d
    ranges.append((start, prev))
    return ranges


def iter_solicitud_calendar_spans(solicitud):
    """Tramos (start, end_inclusive) pendientes para pintar la solicitud."""
    return collapse_dates_to_ranges(get_solicitud_pending_dates(solicitud))


def _recalculate_solicitud_coverage(solicitud, resolved_by_id=None, *, origen_cierre='cuadrante'):
    hoy = today_local()
    valid_dates = get_solicitud_valid_dates(solicitud)
    actionable = [d for d in valid_dates if d >= hoy]
    past_dates = [d for d in valid_dates if d < hoy]
    total_validos = len(valid_dates)
    prev_estado = solicitud.estado
    # Desde la ficha de solicitud = cierre manual; desde cuadrante = autocierre.
    automatico = origen_cierre != 'solicitud'
    tipo = (solicitud.tipo or '').upper()

    if tipo == "GENERICA":
        cov = compute_generica_coverage(solicitud)
        requested = cov['requested']
        counts_by_day = cov['counts_by_day']
        min_coverage = cov['min_coverage']
        total_assignments_count = cov['total_assignments']

        solicitud.cantidad_cubierta = min_coverage

        dias_incompletos = [
            d.strftime("%Y-%m-%d") for d, c in counts_by_day.items() if c < requested
        ]
        try:
            config = _parse_solicitud_config(solicitud)
            if not config:
                plain = (solicitud.comentarios or '').strip()
                config = {}
                if plain and not any(marker in plain for marker in _AUTO_COMENTARIO_MARKERS):
                    config['mensaje_original'] = plain

            if 'original_dates' not in config:
                config['original_dates'] = config.get('dates', [])
            if not config.get('original_dates') and valid_dates:
                config['original_dates'] = [d.strftime("%Y-%m-%d") for d in valid_dates]

            config['mode'] = 'selected'
            config['dates'] = dias_incompletos
            _write_solicitud_config(solicitud, config)
        except Exception:
            pass

        if not valid_dates or requested <= 0:
            pass
        elif not actionable:
            # Ya no queda nada que se pueda hacer en el cuadrante.
            if min_coverage >= requested:
                _mark_auto_cierre(
                    solicitud, estado='CUMPLIDA',
                    motivo='cubierto_antes_de_vencer',
                    resolved_by_id=resolved_by_id,
                    automatico=automatico,
                )
            elif total_assignments_count > 0:
                _mark_auto_cierre(
                    solicitud, estado='CERRADA_PARCIAL',
                    motivo='vencida_cobertura_parcial',
                    resolved_by_id=resolved_by_id,
                    automatico=automatico,
                )
            else:
                _mark_auto_cierre(
                    solicitud, estado='CERRADA_PARCIAL',
                    motivo='vencida_sin_atender',
                    resolved_by_id=resolved_by_id,
                    automatico=automatico,
                )
        else:
            actionable_counts = [counts_by_day.get(d, 0) for d in actionable]
            min_actionable = min(actionable_counts) if actionable_counts else 0
            past_incomplete = any(
                counts_by_day.get(d, 0) < requested for d in past_dates
            )
            if min_actionable >= requested:
                if past_dates and past_incomplete:
                    _mark_auto_cierre(
                        solicitud, estado='CERRADA_PARCIAL',
                        motivo='cubierto_accionable_resto_pasado',
                        resolved_by_id=resolved_by_id,
                        automatico=automatico,
                    )
                else:
                    _mark_auto_cumplida(
                        solicitud, resolved_by_id=resolved_by_id, automatico=automatico,
                    )
            elif sum(actionable_counts) > 0 or total_assignments_count > 0:
                solicitud.estado = "EN_PROCESO"
                solicitud.resolved_at = None
                if prev_estado in ('CUMPLIDA', 'CERRADA_PARCIAL'):
                    _clear_auto_cierre_marker(solicitud)
            else:
                solicitud.estado = "PENDIENTE"
                solicitud.resolved_at = None
                if prev_estado in ('CUMPLIDA', 'CERRADA_PARCIAL'):
                    _clear_auto_cierre_marker(solicitud)

    elif tipo == "CONCRETA":
        accion = getattr(solicitud, 'accion', 'ASIGNAR')

        if accion == 'DESASIGNAR' and prev_estado in ('CUMPLIDA', 'CERRADA_PARCIAL'):
            return

        asignaciones_reales = Asignacion.query.filter(
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.user_id == solicitud.empleado_id,
            Asignacion.fecha.in_(valid_dates),
        ).all() if valid_dates else []

        asignados = {a.fecha for a in asignaciones_reales}
        asignados_actionable = {d for d in asignados if d in actionable}
        asignados_past = {d for d in asignados if d in past_dates}

        if accion == 'DESASIGNAR':
            if not valid_dates:
                pass
            elif not actionable:
                # Solo pasado: ya no se puede operar.
                if not asignados:
                    _mark_auto_cierre(
                        solicitud, estado='CUMPLIDA',
                        motivo='desasignacion_completa',
                        resolved_by_id=resolved_by_id,
                        automatico=automatico,
                    )
                else:
                    _mark_auto_cierre(
                        solicitud, estado='CERRADA_PARCIAL',
                        motivo='vencida_sin_dias_accionables',
                        resolved_by_id=resolved_by_id,
                        automatico=automatico,
                    )
            elif not asignados_actionable:
                # Hoy/futuro ya limpios: la baja operativa está hecha.
                solicitud.cantidad_cubierta = solicitud.cantidad_solicitada
                if asignados_past:
                    _mark_auto_cierre(
                        solicitud, estado='CERRADA_PARCIAL',
                        motivo='cubierto_accionable_resto_pasado',
                        resolved_by_id=resolved_by_id,
                        automatico=automatico,
                    )
                else:
                    _mark_auto_cumplida(
                        solicitud, resolved_by_id=resolved_by_id, automatico=automatico,
                    )
            elif len(asignados_actionable) < len(actionable):
                solicitud.estado = "EN_PROCESO"
                if prev_estado in ('CUMPLIDA', 'CERRADA_PARCIAL'):
                    _clear_auto_cierre_marker(solicitud)
            else:
                solicitud.estado = "PENDIENTE"
                solicitud.cantidad_cubierta = 0
                solicitud.resolved_at = None
                if prev_estado in ('CUMPLIDA', 'CERRADA_PARCIAL'):
                    _clear_auto_cierre_marker(solicitud)
        else:
            # ASIGNAR concreta
            if not valid_dates:
                pass
            elif not actionable:
                if len(asignados) == total_validos and total_validos > 0:
                    _mark_auto_cumplida(
                        solicitud, resolved_by_id=resolved_by_id, automatico=automatico,
                    )
                elif asignados:
                    _mark_auto_cierre(
                        solicitud, estado='CERRADA_PARCIAL',
                        motivo='vencida_cobertura_parcial',
                        resolved_by_id=resolved_by_id,
                        automatico=automatico,
                    )
                else:
                    _mark_auto_cierre(
                        solicitud, estado='CERRADA_PARCIAL',
                        motivo='vencida_sin_atender',
                        resolved_by_id=resolved_by_id,
                        automatico=automatico,
                    )
            elif actionable and asignados_actionable.issuperset(set(actionable)):
                solicitud.cantidad_cubierta = solicitud.cantidad_solicitada
                past_incomplete = any(d not in asignados for d in past_dates)
                if past_dates and past_incomplete:
                    _mark_auto_cierre(
                        solicitud, estado='CERRADA_PARCIAL',
                        motivo='cubierto_accionable_resto_pasado',
                        resolved_by_id=resolved_by_id,
                        automatico=automatico,
                    )
                else:
                    _mark_auto_cumplida(
                        solicitud, resolved_by_id=resolved_by_id, automatico=automatico,
                    )
            elif asignados_actionable:
                solicitud.estado = "EN_PROCESO"
                if prev_estado in ('CUMPLIDA', 'CERRADA_PARCIAL'):
                    _clear_auto_cierre_marker(solicitud)
            else:
                solicitud.estado = "PENDIENTE"
                solicitud.cantidad_cubierta = 0
                solicitud.resolved_at = None
                if prev_estado in ('CUMPLIDA', 'CERRADA_PARCIAL'):
                    _clear_auto_cierre_marker(solicitud)

    db.session.add(solicitud)


def sweep_open_solicitudes_actionable(limit=300):
    """
    Recalcula abiertas: cierra las que ya no tienen días accionables
    o quedan cubiertas en lo operable. Pensado para listado / jobs.
    """
    sols = (
        Solicitud.query.filter(
            Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO']),
        )
        .order_by(Solicitud.fecha_fin.asc(), Solicitud.id.asc())
        .limit(limit)
        .all()
    )
    changed = 0
    for sol in sols:
        prev = sol.estado
        _recalculate_solicitud_coverage(sol, resolved_by_id=None)
        if sol.estado in ('PENDIENTE', 'EN_PROCESO') and not get_solicitud_pending_dates(sol):
            _mark_auto_cumplida(sol, resolved_by_id=None, automatico=True)
        if sol.estado != prev:
            changed += 1
    if changed:
        db.session.commit()
    return changed

class SolicitudService:
    @staticmethod
    def create_solicitud_generica(solicitante_id, obra_id, fecha_inicio, fecha_fin, cantidad, perfil, notas=None, fechas_explicitas=None, etiqueta_ids=None):
        solicitante = User.query.get(solicitante_id)
        fechas = fechas_explicitas or [fecha_inicio + timedelta(days=i) for i in range((fecha_fin - fecha_inicio).days + 1)]
        baseline = snapshot_generica_baseline(obra_id, fechas)
        nueva_solicitud = Solicitud(
            requested_by_id=solicitante_id,
            obra_id=obra_id,
            tipo="GENERICA",
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            cantidad_solicitada=cantidad,
            perfil_categoria=perfil,
            comentarios=build_comentarios_config(
                fechas, baseline_users_by_day=baseline,
            ),
            notas=(notas or '').strip() or None,
            estado="PENDIENTE"
        )
        db.session.add(nueva_solicitud)
        db.session.flush()
        if etiqueta_ids:
            from app.services.etiqueta_service import set_solicitud_etiquetas
            set_solicitud_etiquetas(nueva_solicitud, etiqueta_ids)
        db.session.commit()
        log_nueva_solicitud(nueva_solicitud)
        notificar_nueva_solicitud(nueva_solicitud, solicitante.name)
        return nueva_solicitud

    @staticmethod
    def create_or_merge_solicitud_baja(jefe_id, obra_id, empleado_id, date_objs, notas=None):
        if not date_objs:
            return None, "none"

        # Solo tiene sentido pedir baja de días en los que el operario está asignado.
        fechas_pedidas = []
        for d in date_objs:
            if isinstance(d, str):
                d = datetime.strptime(d, '%Y-%m-%d').date()
            fechas_pedidas.append(d)
        fechas_pedidas = sorted(set(fechas_pedidas))

        asignados = {
            a.fecha
            for a in Asignacion.query.filter(
                Asignacion.obra_id == obra_id,
                Asignacion.user_id == empleado_id,
                Asignacion.fecha.in_(fechas_pedidas),
            ).all()
        }
        date_objs = [d for d in fechas_pedidas if d in asignados]
        if not date_objs:
            return None, "none"

        start_date = min(date_objs)
        end_date = max(date_objs)
        dates_str = [d.strftime('%Y-%m-%d') for d in date_objs]

        open_bajas = Solicitud.query.filter_by(
            tipo='CONCRETA', accion='DESASIGNAR', obra_id=obra_id, empleado_id=empleado_id
        ).filter(Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])).all()

        for baja in open_bajas:
            if (baja.fecha_inicio - timedelta(days=1)) <= end_date and (baja.fecha_fin + timedelta(days=1)) >= start_date:
                baja.fecha_inicio = min(baja.fecha_inicio, start_date)
                baja.fecha_fin = max(baja.fecha_fin, end_date)
                baja.comentarios = merge_comentarios_dates(baja.comentarios, dates_str)
                baja.notas = merge_notas(baja.notas, notas)
                db.session.commit()
                return baja, "merged"

        sol_baja = Solicitud(
            tipo='CONCRETA', accion='DESASIGNAR', obra_id=obra_id,
            requested_by_id=jefe_id, empleado_id=empleado_id,
            fecha_inicio=start_date, fecha_fin=end_date,
            cantidad_solicitada=1, estado='PENDIENTE',
            comentarios=build_comentarios_config(dates_str),
            notas=(notas or '').strip() or None,
        )
        db.session.add(sol_baja)
        db.session.commit()
        log_nueva_solicitud(sol_baja)

        jefe = User.query.get(jefe_id)
        notificar_nueva_solicitud(sol_baja, jefe.name if jefe else 'Sistema')
        return sol_baja, "new"
    
def _parse_desasignacion_config(solicitud):
    mode = 'all_obra'
    dates_to_remove = []
    if solicitud.comentarios and '{' in solicitud.comentarios:
        try:
            config = json.loads(solicitud.comentarios)
            mode = config.get('mode', 'all_obra')
            dates_to_remove = config.get('dates', []) or []
        except Exception:
            pass
    return mode, dates_to_remove


def _collect_desasignacion_asignaciones(solicitud):
    """Asignaciones a eliminar según mode de la solicitud de baja."""
    mode, dates_to_remove = _parse_desasignacion_config(solicitud)
    asigs = []

    if mode == 'selected' and dates_to_remove:
        for d_str in dates_to_remove:
            try:
                d_obj = datetime.strptime(d_str, '%Y-%m-%d').date()
            except ValueError:
                continue
            a = Asignacion.query.filter_by(
                user_id=solicitud.empleado_id,
                obra_id=solicitud.obra_id,
                fecha=d_obj,
            ).first()
            if a:
                asigs.append(a)
    elif mode == 'auto_range':
        asigs = Asignacion.query.filter(
            Asignacion.user_id == solicitud.empleado_id,
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.fecha >= solicitud.fecha_inicio,
            Asignacion.fecha <= solicitud.fecha_fin,
        ).all()
    else:  # all_obra
        start_del = solicitud.fecha_inicio if solicitud.fecha_inicio else today_local()
        asigs = Asignacion.query.filter(
            Asignacion.user_id == solicitud.empleado_id,
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.fecha >= start_del,
        ).all()

    return asigs


def resolver_solicitud_admin(solicitud, accion, user_actor, target_obra_id=None):
    from app.services.assignment_service import process_assignment_action
    from app.services.email_service import notificar_resolucion_solicitud
    from app.services.core_assignment_service import CoreAssignmentService

    if accion in ('aceptar_concreta', 'aceptar_concreta_traslado'):
        if not solicitud.empleado_id:
            raise ValueError("Error: Solicitud concreta sin empleado asignado.")

        tipo_accion = getattr(solicitud, 'accion', 'ASIGNAR')

        if accion == 'aceptar_concreta_traslado':
            if tipo_accion != 'DESASIGNAR':
                raise ValueError("El traslado solo aplica a solicitudes de desasignación.")
            if not target_obra_id:
                raise ValueError("Debes indicar la obra de destino.")
            target_obra_id = int(target_obra_id)
            if int(target_obra_id) == int(solicitud.obra_id):
                raise ValueError("La obra de destino debe ser distinta a la de origen.")

            asigs = _collect_desasignacion_asignaciones(solicitud)
            if not asigs:
                raise ValueError("No hay asignaciones que trasladar en el periodo solicitado.")

            fechas = sorted({a.fecha for a in asigs})
            for a in asigs:
                CoreAssignmentService.desasignar(
                    a.user_id, a.obra_id, a.fecha, user_actor.id,
                    "Traslado desde solicitud de baja",
                    detalle_extra=f"Origen obra {solicitud.obra_id} → destino {target_obra_id}",
                    registrar_log=False,
                )
            if fechas:
                CoreAssignmentService.registrar_log_rango(
                    solicitud.empleado_id, solicitud.obra_id,
                    fechas[0], fechas[-1], len(fechas),
                    user_actor.id, "Traslado desde solicitud de baja", False,
                    detalle_extra=f"Origen obra {solicitud.obra_id} → destino {target_obra_id}",
                    fechas=fechas,
                )

            result = process_assignment_action(
                actor_user=user_actor,
                worker_id=solicitud.empleado_id,
                target_obra_id=target_obra_id,
                date_list=fechas,
                overwrite=True,
            )
            if not result.get('success'):
                raise ValueError(
                    f"Desasignado del origen, pero fallo al asignar destino: {result.get('message')}"
                )

            mensaje = (
                f"Traslado completado: {len(fechas)} día(s) de la obra origen "
                f"a la obra {target_obra_id}."
            )

        elif tipo_accion == 'DESASIGNAR':
            asigs = _collect_desasignacion_asignaciones(solicitud)
            count = 0
            fechas = []
            for a in asigs:
                borrado = CoreAssignmentService.desasignar(
                    a.user_id, a.obra_id, a.fecha, user_actor.id,
                    "Aprobación de Solicitud de Baja",
                    registrar_log=False,
                )
                if borrado:
                    count += 1
                    fechas.append(a.fecha)
            if count and fechas:
                fechas = sorted(set(fechas))
                CoreAssignmentService.registrar_log_rango(
                    solicitud.empleado_id, solicitud.obra_id,
                    fechas[0], fechas[-1], count,
                    user_actor.id, "Aprobación de Solicitud de Baja", False,
                    fechas=fechas,
                )
            mensaje = f"Devolución aprobada. Se han eliminado {count} asignaciones."

        else:
            from app.models import Festivo
            festivos = {
                f.fecha for f in Festivo.query.filter(
                    Festivo.fecha >= solicitud.fecha_inicio,
                    Festivo.fecha <= solicitud.fecha_fin,
                ).all()
            }
            dias = []
            curr = solicitud.fecha_inicio
            while curr <= solicitud.fecha_fin:
                if curr.weekday() < 5 and curr not in festivos:
                    dias.append(curr)
                curr += timedelta(days=1)
            if not dias:
                raise ValueError(
                    "El rango de la solicitud no contiene días laborables válidos."
                )

            result = process_assignment_action(
                actor_user=user_actor, worker_id=solicitud.empleado_id,
                target_obra_id=solicitud.obra_id, date_list=dias, overwrite=True
            )

            if not result.get('success'):
                raise ValueError(f"Error al asignar: {result.get('message')}")

            mensaje = "Solicitud aceptada y trabajador asignado."

        # El core puede haber autocerrado (y notificado) al asignar/desasignar.
        ya_notificado_auto = (
            solicitud.estado == 'CUMPLIDA' and bool(solicitud.auto_fulfilled)
        )
        _clear_auto_cierre_marker(solicitud)
        solicitud.estado = 'CUMPLIDA'
        solicitud.auto_fulfilled = False
        solicitud.cantidad_cubierta = solicitud.cantidad_solicitada
        solicitud.resolved_at = utc_now()
        solicitud.resolved_by_id = user_actor.id
        db.session.commit()
        if not ya_notificado_auto:
            try:
                notificar_resolucion_solicitud(solicitud, user_actor.name)
            except Exception:
                # La resolución ya está guardada; un fallo de correo no debe tumbar la API.
                pass
        return mensaje

    elif accion == 'denegar':
        _clear_auto_cierre_marker(solicitud)
        solicitud.estado = 'DENEGADA'
        solicitud.resolved_at = utc_now()
        solicitud.resolved_by_id = user_actor.id
        db.session.commit()
        try:
            notificar_resolucion_solicitud(solicitud, user_actor.name)
        except Exception:
            pass
        return "Solicitud denegada."

    elif accion == 'cancelar':
        return cancelar_solicitud_por_autor(solicitud, user_actor)

    elif accion == 'reabrir':
        _clear_auto_cierre_marker(solicitud)
        solicitud.estado = 'PENDIENTE'
        solicitud.resolved_at = None
        solicitud.resolved_by_id = None
        # Recalcula progreso/cobertura con lo que haya vinculado ahora mismo.
        _recalculate_solicitud_coverage(solicitud, resolved_by_id=None)
        db.session.commit()
        return "Solicitud reabierta."
    else:
        raise ValueError("Acción no reconocida.")


def cancelar_solicitud_por_autor(solicitud, user_actor):
    """El autor retira su propia solicitud abierta (no es un denegado de oficina)."""
    from app.services.i18n_service import translate

    if not user_actor or not getattr(user_actor, 'id', None):
        raise ValueError(translate('No autorizado.'))
    if solicitud.requested_by_id != user_actor.id:
        raise ValueError(translate('Solo quien abrió la solicitud puede cancelarla.'))
    if solicitud.estado not in ('PENDIENTE', 'EN_PROCESO'):
        raise ValueError(translate('Solo se pueden cancelar solicitudes abiertas.'))

    solicitud.estado = 'CANCELADA'
    solicitud.auto_fulfilled = False
    solicitud.resolved_at = utc_now()
    solicitud.resolved_by_id = user_actor.id
    config = _parse_solicitud_config(solicitud)
    if 'auto_cierre' in config:
        config.pop('auto_cierre', None)
        _write_solicitud_config(solicitud, config)
    db.session.commit()
    return "Solicitud cancelada."


def solicitud_calendar_title(solicitud, obra_label='?', *, view='worker'):
    """
    Título legible para eventos de solicitud en calendarios.

    view:
      - worker: calendario del propio operario (incluye obra, sin nombre)
      - obra: ficha de obra (nombre del operario, sin obra en el título)
      - empresa: ficha de empresa (nombre + obra)
    """
    from app.services.i18n_service import translate

    accion = getattr(solicitud, 'accion', 'ASIGNAR') or 'ASIGNAR'
    obra = obra_label or '?'

    if getattr(solicitud, 'tipo', None) == 'GENERICA':
        faltan = solicitud.cantidad_solicitada - solicitud.cantidad_cubierta
        if faltan <= 0:
            return None
        perfil = solicitud.perfil_categoria or translate('Cualquiera')
        if view == 'empresa':
            return translate(
                'Solicitud de personal: faltan {n} ({perfil}) · {obra}',
                n=faltan,
                perfil=perfil,
                obra=obra,
            )
        return translate(
            'Solicitud de personal: faltan {n} ({perfil})',
            n=faltan,
            perfil=perfil,
        )

    emp_name = '?'
    empleado = getattr(solicitud, 'empleado', None)
    if empleado:
        emp_name = empleado.name or '?'

    if view == 'worker':
        if accion == 'DESASIGNAR':
            return translate('Solicitud de baja · {obra}', obra=obra)
        return translate('Solicitud de asignación · {obra}', obra=obra)

    if accion == 'DESASIGNAR':
        if view == 'empresa':
            return translate(
                'Solicitud de baja: {nombre} ({obra})',
                nombre=emp_name,
                obra=obra,
            )
        return translate('Solicitud de baja: {nombre}', nombre=emp_name)

    if view == 'empresa':
        return translate(
            'Solicitud de asignación: {nombre} ({obra})',
            nombre=emp_name,
            obra=obra,
        )
    return translate('Solicitud de asignación: {nombre}', nombre=emp_name)
