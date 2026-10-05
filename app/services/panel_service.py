# app/services/panel_service.py
"""Datos agregados para el panel principal de administración."""

import json
from datetime import timedelta

from sqlalchemy import func, case, distinct, or_
from sqlalchemy.orm import joinedload

from app import db
from app.models import (
    User, Obra, Asignacion, Solicitud, Company, RegistroFichaje,
    SystemLog, SyncLog, AusenciaPlanificada, AusenciaConflicto,
    CONFLICT_PENDING, LEAVE_STATUS_PENDIENTE, LEAVE_STATUS_APROBADA,
    ROLE_OPERARIO, ROLE_JEFE, ROLE_RRHH, ROLE_ADMIN,
)
from app.services.fichaje_estado_service import (
    FICHAJE_INTERVENCION,
    FICHAJE_OK,
    label_estado_fichaje,
)
from app.utils.timezone_utils import today_local

# Un día se considera "cerrado" cuando el estado es OK (incluye resoluciones de
# auditoría: Resuelto_*, Cerrado_Multiobra, Exento_Ausencia) o intervención
# humana (Sobreescrito_RRHH). Sin esta unión, un `Resuelto_Movido` desaparece
# del KPI de OK y el admin siente que no avanza tras resolver.
_FICHAJE_ESTADOS_CERRADOS = FICHAJE_OK | FICHAJE_INTERVENCION


def _fichajes_fisicos_q(fecha, obra_ids=None):
    """
    Entradas reales del día: tienen check_in.

    Excluye ausencias sintéticas (Exento_Ausencia, Ausencia sin entrada),
    semillas Sin_Registro y cierres multiobra sin fichaje físico.
    """
    q = RegistroFichaje.query.filter(
        RegistroFichaje.fecha == fecha,
        RegistroFichaje.check_in.isnot(None),
    )
    if obra_ids is not None:
        if not obra_ids:
            return q.filter(RegistroFichaje.id < 0)
        q = q.filter(_filtro_auditoria_obras(obra_ids))
    return q


def _parse_kpi_fecha(fecha):
    if fecha is None or fecha == '':
        return None
    if hasattr(fecha, 'year'):
        return fecha
    from datetime import date as date_cls
    if isinstance(fecha, str):
        return date_cls.fromisoformat(fecha[:10])
    raise ValueError('fecha inválida')


def _fmt_hora(dt):
    if not dt:
        return None
    from app.utils.timezone_utils import format_time
    return format_time(dt)


def _nombre_user(user):
    if not user:
        return '—'
    return f'{(user.name or "").strip()} {(user.lastname or "").strip()}'.strip() or '—'


def _obra_nombre(obra):
    return (obra.nombre if obra else None) or '—'


def get_panel_kpi_detail(kind, fecha=None, *, obra_ids=None, limit=500):
    """
    Filas que componen un KPI del panel (fichajes / asignaciones / auditoría).

    obra_ids=None → admin (sin filtro de obra).
    obra_ids=[] → jefe sin obras (vacío).
    obra_ids=[...] → restringe a esas obras.
    """
    today = today_local()
    kind = (kind or '').strip().lower()
    if kind not in ('fichajes', 'asignaciones', 'auditoria'):
        raise ValueError('kind inválido')

    fecha_obj = _parse_kpi_fecha(fecha)
    if kind in ('fichajes', 'asignaciones') and fecha_obj is None:
        fecha_obj = today

    scoped = obra_ids is not None
    if scoped and not obra_ids:
        return {
            'kind': kind,
            'fecha': fecha_obj.isoformat() if fecha_obj else None,
            'today': today.isoformat(),
            'total': 0,
            'truncated': False,
            'columns': [],
            'rows': [],
        }

    if kind == 'fichajes':
        # Solo fichajes físicos (hay entrada). El KPI del panel usa el mismo criterio.
        q = (
            _fichajes_fisicos_q(fecha_obj, obra_ids if scoped else None)
            .options(
                joinedload(RegistroFichaje.user),
                joinedload(RegistroFichaje.obra_planificada),
                joinedload(RegistroFichaje.obra_real),
            )
        )
        regs = q.order_by(RegistroFichaje.check_in.asc().nullslast(), RegistroFichaje.id).limit(limit + 1).all()
        truncated = len(regs) > limit
        regs = regs[:limit]
        rows = []
        for r in regs:
            rows.append({
                'id': r.id,
                'user_id': r.user_id,
                'fecha': r.fecha.isoformat() if r.fecha else None,
                'nombre': _nombre_user(r.user),
                'dni': (r.user.dni if r.user else None) or '—',
                'obra_plan': _obra_nombre(r.obra_planificada),
                'obra_real': _obra_nombre(r.obra_real),
                'entrada': _fmt_hora(r.check_in),
                'salida': _fmt_hora(r.check_out),
                'estado': label_estado_fichaje(r.estado),
                'estado_raw': r.estado or '',
            })
        return {
            'kind': kind,
            'fecha': fecha_obj.isoformat(),
            'today': today.isoformat(),
            'total': len(rows),
            'truncated': truncated,
            'columns': ['fecha', 'nombre', 'obra_plan', 'obra_real', 'entrada', 'salida', 'estado'],
            'rows': rows,
        }

    if kind == 'asignaciones':
        q = (
            Asignacion.query.options(
                joinedload(Asignacion.user).joinedload(User.company_rel),
                joinedload(Asignacion.obra),
            )
            .filter(Asignacion.fecha == fecha_obj)
        )
        if scoped:
            q = q.filter(Asignacion.obra_id.in_(obra_ids))
        asigs = q.order_by(Asignacion.obra_id, Asignacion.user_id).limit(limit + 1).all()
        truncated = len(asigs) > limit
        asigs = asigs[:limit]
        rows = []
        for a in asigs:
            u = a.user
            if u and u.is_deleted:
                continue
            empresa = '—'
            if u and u.company_rel:
                empresa = u.company_rel.nombre or '—'
            rows.append({
                'id': a.id,
                'user_id': a.user_id,
                'fecha': a.fecha.isoformat() if a.fecha else None,
                'nombre': _nombre_user(u),
                'dni': (u.dni if u else None) or '—',
                'obra': _obra_nombre(a.obra),
                'empresa': empresa,
            })
        return {
            'kind': kind,
            'fecha': fecha_obj.isoformat(),
            'today': today.isoformat(),
            'total': len(rows),
            'truncated': truncated,
            'columns': ['nombre', 'dni', 'obra', 'empresa'],
            'rows': rows,
        }

    # auditoría pendiente (conflictos abiertos)
    q = (
        RegistroFichaje.query.options(
            joinedload(RegistroFichaje.user),
            joinedload(RegistroFichaje.obra_planificada),
            joinedload(RegistroFichaje.obra_real),
        )
        .filter(RegistroFichaje.estado.in_(['Conflicto', 'Paracaidista', 'Ausencia']))
    )
    if fecha_obj is not None:
        q = q.filter(RegistroFichaje.fecha == fecha_obj)
    if scoped:
        q = q.filter(_filtro_auditoria_obras(obra_ids))
    regs = q.order_by(RegistroFichaje.fecha.desc(), RegistroFichaje.id.desc()).limit(limit + 1).all()
    truncated = len(regs) > limit
    regs = regs[:limit]
    rows = []
    for r in regs:
        rows.append({
            'id': r.id,
            'user_id': r.user_id,
            'fecha': r.fecha.isoformat() if r.fecha else None,
            'nombre': _nombre_user(r.user),
            'dni': (r.user.dni if r.user else None) or '—',
            'obra_plan': _obra_nombre(r.obra_planificada),
            'obra_real': _obra_nombre(r.obra_real),
            'entrada': _fmt_hora(r.check_in),
            'salida': _fmt_hora(r.check_out),
            'estado': label_estado_fichaje(r.estado),
            'estado_raw': r.estado or '',
        })
    return {
        'kind': kind,
        'fecha': fecha_obj.isoformat() if fecha_obj else None,
        'today': today.isoformat(),
        'total': len(rows),
        'truncated': truncated,
        'columns': ['fecha', 'nombre', 'obra_plan', 'obra_real', 'entrada', 'salida', 'estado'],
        'rows': rows,
    }


def resumen_hoy_plan_vs_ficha(fecha=None, limite=40):
    """
    Quién está planificado hoy y si ha fichado (y dónde).

    Es la vista que el dueño mira a media mañana: planificado vs realidad.
    """
    fecha = fecha or today_local()
    asignaciones = (
        Asignacion.query.options(
            joinedload(Asignacion.user),
            joinedload(Asignacion.obra),
        )
        .filter(Asignacion.fecha == fecha)
        .order_by(Asignacion.obra_id, Asignacion.user_id)
        .all()
    )
    fichajes = {
        f.user_id: f
        for f in RegistroFichaje.query.options(
            joinedload(RegistroFichaje.obra_real),
        ).filter_by(fecha=fecha).all()
    }

    filas = []
    for a in asignaciones[:limite]:
        user = a.user
        if not user or user.is_deleted:
            continue
        fichaje = fichajes.get(user.id)
        obra_plan = a.obra
        obra_real = fichaje.obra_real if fichaje else None
        if not fichaje or not fichaje.check_in:
            estado = 'sin_fichar'
        elif obra_real and obra_plan and obra_real.id != obra_plan.id:
            estado = 'otra_obra'
        else:
            estado = 'ok'
        filas.append({
            'user': user,
            'obra_planificada': obra_plan,
            'obra_real': obra_real,
            'check_in': fichaje.check_in if fichaje else None,
            'check_out': fichaje.check_out if fichaje else None,
            'estado': estado,
        })

    return {
        'filas': filas,
        'planificados': len(filas),
        'fichados': sum(1 for f in filas if f['estado'] in ('ok', 'otra_obra')),
        'sin_fichar': sum(1 for f in filas if f['estado'] == 'sin_fichar'),
        'otra_obra': sum(1 for f in filas if f['estado'] == 'otra_obra'),
    }


def _obra_ids_del_jefe(user_id):
    return [
        o.id for o in Obra.query.filter(
            Obra.jefe_obra_id == user_id,
            Obra.is_deleted.is_(False),
        ).all()
    ]


def _filtro_auditoria_obras(obra_ids):
    return or_(
        RegistroFichaje.obra_planificada_id.in_(obra_ids),
        RegistroFichaje.obra_real_id.in_(obra_ids),
    )


def _parse_sync_errores_detail(sync_log):
    """Líneas legibles para tooltip de errores de la última sincronización."""
    if not sync_log or not sync_log.errores:
        return []

    det = (sync_log.detalles or '').strip()
    if det:
        if det.startswith('['):
            try:
                items = json.loads(det)
                if isinstance(items, list) and items:
                    return [str(x) for x in items[:25]]
            except (json.JSONDecodeError, TypeError):
                pass
        if '\n' in det:
            lines = [ln.strip() for ln in det.split('\n') if ln.strip()]
            if len(lines) > 1 or 'error' in det.lower():
                return lines[:25]

    tipo = sync_log.tipo or 'Sync'
    modo = sync_log.modo or '—'
    lines = [f'{sync_log.errores} registro(s) con advertencias en {tipo} ({modo})']
    if 'Obras' in tipo:
        lines.append('Suele deberse a jefe o encargado no encontrado en la plataforma.')
    elif 'Empleados' in tipo:
        lines.append('Suele deberse a conflictos de email, DNI o rol duplicado.')
    elif 'Ausencias' in tipo:
        lines.append(
            'Las omitidas suelen ser bajas de Odoo cuyo empleado no está vinculado en SignaPlan.'
        )
    else:
        lines.append('Registros omitidos por conflictos o datos incompletos.')
    if det and det not in lines:
        lines.append(det)
    if 'Ausencias' not in tipo:
        lines.append('Revisa el preview en Sincronizar Odoo para ver cada registro.')
    return lines


def get_admin_panel_context():
    today = today_local()
    chart_start = today - timedelta(days=13)

    # —— Personal ——
    total_operarios = User.query.filter_by(role=ROLE_OPERARIO, is_deleted=False).count()
    operarios_activos = User.query.filter_by(
        role=ROLE_OPERARIO, is_deleted=False, active=True
    ).count()
    operarios_inactivos = total_operarios - operarios_activos

    total_internos = (
        User.query.join(Company)
        .filter(User.role == ROLE_OPERARIO, User.is_deleted == False, Company.is_internal == True)
        .count()
    )
    total_externos = (
        User.query.join(Company)
        .filter(User.role == ROLE_OPERARIO, User.is_deleted == False, Company.is_internal == False)
        .count()
    )

    from app.services.inercia_service import ids_ocupados_en_fecha
    planificados_hoy = len(ids_ocupados_en_fecha(today))
    asignaciones_hoy = Asignacion.query.filter_by(fecha=today).count()
    libres_hoy = max(0, operarios_activos - planificados_hoy)
    ocupacion_pct = round((planificados_hoy / operarios_activos * 100), 1) if operarios_activos else 0

    # —— Obras ——
    obras_en_curso = Obra.query.filter(
        Obra.is_deleted.is_(False), Obra.estado.in_(['En Curso', 'En Garantía'])
    ).count()
    total_obras = Obra.query.filter(Obra.is_deleted.is_(False)).count()
    obras_sin_jefe = Obra.query.filter(
        Obra.is_deleted.is_(False),
        Obra.estado.in_(['En Curso', 'En Garantía']),
        Obra.jefe_obra_id.is_(None),
    ).count()

    total_jefes = User.query.filter(
        User.role == ROLE_JEFE, User.is_deleted == False, User.active == True
    ).count()
    total_rrhh = User.query.filter_by(role=ROLE_RRHH, is_deleted=False).count()
    total_companies = Company.query.count()

    # —— Solicitudes ——
    solicitudes_por_estado = dict(
        db.session.query(Solicitud.estado, func.count(Solicitud.id))
        .group_by(Solicitud.estado)
        .all()
    )
    solicitudes_abiertas = (
        solicitudes_por_estado.get('PENDIENTE', 0)
        + solicitudes_por_estado.get('EN_PROCESO', 0)
    )

    recent_solicitudes = (
        Solicitud.query.options(
            joinedload(Solicitud.obra),
            joinedload(Solicitud.empleado),
            joinedload(Solicitud.requested_by),
        )
        .order_by(
            case(
                (Solicitud.estado == 'PENDIENTE', 0),
                (Solicitud.estado == 'EN_PROCESO', 1),
                else_=2,
            ),
            Solicitud.id.desc(),
        )
        .limit(10)
        .all()
    )

    # —— Auditoría fichajes ——
    audit_conflictos = RegistroFichaje.query.filter_by(estado='Conflicto').count()
    audit_paracaidistas = RegistroFichaje.query.filter_by(estado='Paracaidista').count()
    audit_ausencias = RegistroFichaje.query.filter_by(estado='Ausencia').count()
    audit_pendientes_total = audit_conflictos + audit_paracaidistas + audit_ausencias

    auditoria_alertas = (
        RegistroFichaje.query.options(
            joinedload(RegistroFichaje.user),
            joinedload(RegistroFichaje.obra_planificada),
            joinedload(RegistroFichaje.obra_real),
        )
        .filter(RegistroFichaje.estado.in_(['Conflicto', 'Paracaidista', 'Ausencia']))
        .order_by(RegistroFichaje.fecha.desc())
        .limit(8)
        .all()
    )

    fichajes_hoy = _fichajes_fisicos_q(today).all()
    fichajes_ok_hoy = sum(
        1 for f in fichajes_hoy if f.estado in _FICHAJE_ESTADOS_CERRADOS
    )
    fichajes_incidente_hoy = sum(
        1 for f in fichajes_hoy
        if f.estado in ('Conflicto', 'Paracaidista', 'Ausencia', 'Disputa', 'Retraso')
    )

    # —— Gráfico planificación 14 días ——
    asig_rows = (
        db.session.query(Asignacion.fecha, func.count(Asignacion.id))
        .filter(Asignacion.fecha >= chart_start, Asignacion.fecha <= today)
        .group_by(Asignacion.fecha)
        .all()
    )
    asig_map = {f: c for f, c in asig_rows}
    chart_plan_labels = []
    chart_plan_values = []
    for i in range(14):
        d = chart_start + timedelta(days=i)
        chart_plan_labels.append(d.strftime('%d/%m'))
        chart_plan_values.append(asig_map.get(d, 0))

    chart_plan_dates = [
        (chart_start + timedelta(days=i)).isoformat() for i in range(14)
    ]

    # —— Obras con más personal hoy ——
    obras_hoy_rows = (
        db.session.query(Obra, func.count(Asignacion.id))
        .join(Asignacion, Asignacion.obra_id == Obra.id)
        .filter(Asignacion.fecha == today, Obra.is_deleted.is_(False))
        .group_by(Obra.id)
        .order_by(func.count(Asignacion.id).desc())
        .limit(8)
        .all()
    )

    recent_obras = (
        Obra.query.filter(Obra.is_deleted.is_(False))
        .options(joinedload(Obra.jefe_obra))
        .order_by(Obra.id.desc())
        .limit(5)
        .all()
    )

    # —— Actividad ——
    recent_logs = (
        SystemLog.query.options(joinedload(SystemLog.user))
        .order_by(SystemLog.timestamp.desc())
        .limit(8)
        .all()
    )
    last_sync = (
        SyncLog.query.filter(db.or_(SyncLog.visto.is_(False), SyncLog.visto.is_(None)))
        .order_by(SyncLog.fecha.desc())
        .first()
    )
    sync_error_lines = _parse_sync_errores_detail(last_sync) if last_sync else []
    hoy_en_obra = resumen_hoy_plan_vs_ficha(today)

    return {
        'today': today,
        'hoy_en_obra': hoy_en_obra,
        'total_operarios': total_operarios,
        'operarios_activos': operarios_activos,
        'operarios_inactivos': operarios_inactivos,
        'total_internos': total_internos,
        'total_externos': total_externos,
        'planificados_hoy': planificados_hoy,
        'libres_hoy': libres_hoy,
        'asignaciones_hoy': asignaciones_hoy,
        'ocupacion_pct': ocupacion_pct,
        'obras_en_curso': obras_en_curso,
        'total_obras': total_obras,
        'obras_sin_jefe': obras_sin_jefe,
        'total_jefes': total_jefes,
        'total_rrhh': total_rrhh,
        'total_companies': total_companies,
        'solicitudes_por_estado': solicitudes_por_estado,
        'solicitudes_abiertas': solicitudes_abiertas,
        'recent_solicitudes': recent_solicitudes,
        'audit_conflictos': audit_conflictos,
        'audit_paracaidistas': audit_paracaidistas,
        'audit_ausencias': audit_ausencias,
        'audit_pendientes_total': audit_pendientes_total,
        'auditoria_alertas': auditoria_alertas,
        'fichajes_ok_hoy': fichajes_ok_hoy,
        'fichajes_incidente_hoy': fichajes_incidente_hoy,
        'fichajes_total_hoy': len(fichajes_hoy),
        'chart_plan_labels': chart_plan_labels,
        'chart_plan_values': chart_plan_values,
        'chart_plan_dates': chart_plan_dates,
        'obras_hoy_rows': obras_hoy_rows,
        'recent_obras': recent_obras,
        'recent_logs': recent_logs,
        'last_sync': last_sync,
        'sync_error_lines': sync_error_lines,
        'chart_solicitud_labels': list(solicitudes_por_estado.keys()),
        'chart_solicitud_values': list(solicitudes_por_estado.values()),
    }


def get_laboral_panel_context(user, *, puede_ver_auditoria=True, horizon_days=14):
    """
    Panel de inicio para ROLE_LABORAL / ROLE_RRHH (y admin si entra).
    KPIs de ausencias, conflictos y auditoría de fichajes.
    """
    today = today_local()
    horizon = today + timedelta(days=horizon_days)

    ausencias_pendientes = (
        AusenciaPlanificada.query.filter_by(estado=LEAVE_STATUS_PENDIENTE).count()
    )
    conflictos_pendientes = (
        AusenciaConflicto.query.filter_by(estado=CONFLICT_PENDING).count()
    )

    audit_conflictos = audit_paracaidistas = audit_ausencias = 0
    audit_pendientes_total = 0
    if puede_ver_auditoria:
        audit_conflictos = RegistroFichaje.query.filter_by(estado='Conflicto').count()
        audit_paracaidistas = RegistroFichaje.query.filter_by(estado='Paracaidista').count()
        audit_ausencias = RegistroFichaje.query.filter_by(estado='Ausencia').count()
        audit_pendientes_total = audit_conflictos + audit_paracaidistas + audit_ausencias

    proximas_ausencias = (
        AusenciaPlanificada.query.options(joinedload(AusenciaPlanificada.user))
        .filter(
            AusenciaPlanificada.estado == LEAVE_STATUS_APROBADA,
            AusenciaPlanificada.fecha_fin >= today,
            AusenciaPlanificada.fecha_inicio <= horizon,
        )
        .order_by(AusenciaPlanificada.fecha_inicio.asc(), AusenciaPlanificada.id.asc())
        .limit(12)
        .all()
    )

    return {
        'today': today,
        'horizon_days': horizon_days,
        'ausencias_pendientes': ausencias_pendientes,
        'conflictos_pendientes': conflictos_pendientes,
        'audit_conflictos': audit_conflictos,
        'audit_paracaidistas': audit_paracaidistas,
        'audit_ausencias': audit_ausencias,
        'audit_pendientes_total': audit_pendientes_total,
        'puede_ver_auditoria': puede_ver_auditoria,
        'proximas_ausencias': proximas_ausencias,
    }


def get_jefe_panel_context(user):
    """Panel de control filtrado al alcance de planificación del usuario."""
    today = today_local()
    chart_start = today - timedelta(days=13)
    from app.services.panel_scope_service import (
        PANEL_TABLERO,
        apply_obra_scope_filter,
        user_panel_mode,
    )

    mode = user_panel_mode(user, PANEL_TABLERO)
    if mode == 'office':
        mis_obras = (
            Obra.query.filter(Obra.is_deleted.is_(False))
            .options(joinedload(Obra.jefe_obra))
            .all()
        )
        obra_ids = [o.id for o in mis_obras]
    elif mode == 'none':
        obra_ids = []
        mis_obras = []
    else:
        mis_obras = (
            apply_obra_scope_filter(
                Obra.query.filter(Obra.is_deleted.is_(False)).options(
                    joinedload(Obra.jefe_obra)
                ),
                user,
                PANEL_TABLERO,
            ).all()
        )
        obra_ids = [o.id for o in mis_obras]
        if not obra_ids:
            obra_ids = _obra_ids_del_jefe(user.id)
            mis_obras = (
                Obra.query.filter(
                    Obra.jefe_obra_id == user.id,
                    Obra.is_deleted.is_(False),
                )
                .options(joinedload(Obra.jefe_obra))
                .all()
            ) if obra_ids else []

    obras_en_curso = sum(
        1 for o in mis_obras if o.estado in ('En Curso', 'En Garantía')
    )
    total_obras = len(mis_obras)

    if obra_ids:
        from app.services.inercia_service import presencias_en_fecha
        presencias = [
            p for p in presencias_en_fecha(today)
            if p['obra_id'] in set(obra_ids)
        ]
        asignaciones_hoy = len(presencias)
        planificados_hoy = len({p['user_id'] for p in presencias})
        obras_hoy_rows = (
            db.session.query(Obra, func.count(Asignacion.id))
            .join(Asignacion, Asignacion.obra_id == Obra.id)
            .filter(Asignacion.fecha == today, Obra.id.in_(obra_ids))
            .group_by(Obra.id)
            .order_by(func.count(Asignacion.id).desc())
            .limit(8)
            .all()
        )
        asig_rows = (
            db.session.query(Asignacion.fecha, func.count(Asignacion.id))
            .filter(
                Asignacion.obra_id.in_(obra_ids),
                Asignacion.fecha >= chart_start,
                Asignacion.fecha <= today,
            )
            .group_by(Asignacion.fecha)
            .all()
        )
        audit_base = RegistroFichaje.query.filter(_filtro_auditoria_obras(obra_ids))
        audit_conflictos = audit_base.filter_by(estado='Conflicto').count()
        audit_paracaidistas = audit_base.filter_by(estado='Paracaidista').count()
        audit_ausencias = audit_base.filter_by(estado='Ausencia').count()
        auditoria_alertas = (
            RegistroFichaje.query.options(
                joinedload(RegistroFichaje.user),
                joinedload(RegistroFichaje.obra_planificada),
                joinedload(RegistroFichaje.obra_real),
            )
            .filter(
                RegistroFichaje.estado.in_(['Conflicto', 'Paracaidista', 'Ausencia']),
                _filtro_auditoria_obras(obra_ids),
            )
            .order_by(RegistroFichaje.fecha.desc())
            .limit(8)
            .all()
        )
        fichajes_hoy = _fichajes_fisicos_q(today, obra_ids).all()
        solicitudes_q = Solicitud.query.filter(Solicitud.obra_id.in_(obra_ids))
    else:
        asignaciones_hoy = planificados_hoy = 0
        obras_hoy_rows = []
        asig_rows = []
        audit_conflictos = audit_paracaidistas = audit_ausencias = 0
        auditoria_alertas = []
        fichajes_hoy = []
        solicitudes_q = Solicitud.query.filter(Solicitud.id < 0)

    audit_pendientes_total = audit_conflictos + audit_paracaidistas + audit_ausencias
    libres_hoy = 0
    ocupacion_pct = 0
    fichajes_ok_hoy = sum(
        1 for f in fichajes_hoy if f.estado in _FICHAJE_ESTADOS_CERRADOS
    )
    fichajes_incidente_hoy = sum(
        1 for f in fichajes_hoy
        if f.estado in ('Conflicto', 'Paracaidista', 'Ausencia', 'Disputa', 'Retraso')
    )

    solicitudes_por_estado = dict(
        db.session.query(Solicitud.estado, func.count(Solicitud.id))
        .filter(Solicitud.obra_id.in_(obra_ids) if obra_ids else Solicitud.id < 0)
        .group_by(Solicitud.estado)
        .all()
    ) if obra_ids else {}
    solicitudes_abiertas = (
        solicitudes_por_estado.get('PENDIENTE', 0)
        + solicitudes_por_estado.get('EN_PROCESO', 0)
    )

    recent_solicitudes = (
        solicitudes_q.options(
            joinedload(Solicitud.obra),
            joinedload(Solicitud.empleado),
            joinedload(Solicitud.requested_by),
        )
        .order_by(
            case(
                (Solicitud.estado == 'PENDIENTE', 0),
                (Solicitud.estado == 'EN_PROCESO', 1),
                else_=2,
            ),
            Solicitud.id.desc(),
        )
        .limit(10)
        .all()
    ) if obra_ids else []

    asig_map = {f: c for f, c in asig_rows}
    chart_plan_labels = []
    chart_plan_values = []
    for i in range(14):
        d = chart_start + timedelta(days=i)
        chart_plan_labels.append(d.strftime('%d/%m'))
        chart_plan_values.append(asig_map.get(d, 0))

    chart_plan_dates = [
        (chart_start + timedelta(days=i)).isoformat() for i in range(14)
    ]

    recent_obras = [o for o in mis_obras if o.estado in ('En Curso', 'En Garantía')][:5]

    recent_logs = (
        SystemLog.query.options(joinedload(SystemLog.user))
        .filter(
            or_(
                SystemLog.user_id == user.id,
                SystemLog.category.in_(['fichajes', 'planificacion', 'solicitudes']),
            )
        )
        .order_by(SystemLog.timestamp.desc())
        .limit(8)
        .all()
    )

    return {
        'today': today,
        'panel_mode': 'jefe',
        'mis_obras': mis_obras,
        'planificados_hoy': planificados_hoy,
        'libres_hoy': libres_hoy,
        'asignaciones_hoy': asignaciones_hoy,
        'ocupacion_pct': ocupacion_pct,
        'obras_en_curso': obras_en_curso,
        'total_obras': total_obras,
        'solicitudes_por_estado': solicitudes_por_estado,
        'solicitudes_abiertas': solicitudes_abiertas,
        'recent_solicitudes': recent_solicitudes,
        'audit_conflictos': audit_conflictos,
        'audit_paracaidistas': audit_paracaidistas,
        'audit_ausencias': audit_ausencias,
        'audit_pendientes_total': audit_pendientes_total,
        'auditoria_alertas': auditoria_alertas,
        'fichajes_ok_hoy': fichajes_ok_hoy,
        'fichajes_incidente_hoy': fichajes_incidente_hoy,
        'fichajes_total_hoy': len(fichajes_hoy),
        'chart_plan_labels': chart_plan_labels,
        'chart_plan_values': chart_plan_values,
        'chart_plan_dates': chart_plan_dates,
        'obras_hoy_rows': obras_hoy_rows,
        'recent_obras': recent_obras,
        'recent_logs': recent_logs,
        'chart_solicitud_labels': list(solicitudes_por_estado.keys()),
        'chart_solicitud_values': list(solicitudes_por_estado.values()),
    }
