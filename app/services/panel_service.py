# app/services/panel_service.py
"""Datos agregados para el panel principal de administración."""

import json
from datetime import timedelta

from sqlalchemy import func, case, distinct, or_
from sqlalchemy.orm import joinedload

from app import db
from app.models import (
    User, Obra, Asignacion, Solicitud, Company, RegistroFichaje,
    SystemLog, SyncLog,
    ROLE_OPERARIO, ROLE_JEFE, ROLE_RRHH, ROLE_ADMIN,
)
from app.utils.timezone_utils import today_local


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
    else:
        lines.append('Registros omitidos por conflictos o datos incompletos.')
    if det and det not in lines:
        lines.append(det)
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

    planificados_hoy = (
        db.session.query(func.count(distinct(Asignacion.user_id)))
        .filter(Asignacion.fecha == today)
        .scalar() or 0
    )
    asignaciones_hoy = Asignacion.query.filter_by(fecha=today).count()
    libres_hoy = max(0, operarios_activos - planificados_hoy)
    ocupacion_pct = round((planificados_hoy / operarios_activos * 100), 1) if operarios_activos else 0

    # —— Obras ——
    obras_en_curso = Obra.query.filter(
        Obra.is_deleted.is_(False), Obra.estado == 'En Curso'
    ).count()
    total_obras = Obra.query.filter(Obra.is_deleted.is_(False)).count()
    obras_sin_jefe = Obra.query.filter(
        Obra.is_deleted.is_(False),
        Obra.estado == 'En Curso',
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

    fichajes_hoy = RegistroFichaje.query.filter_by(fecha=today).all()
    fichajes_ok_hoy = sum(1 for f in fichajes_hoy if f.estado == 'Correcto')
    fichajes_incidente_hoy = sum(
        1 for f in fichajes_hoy
        if f.estado in ('Conflicto', 'Paracaidista', 'Ausencia')
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
    last_sync = SyncLog.query.order_by(SyncLog.fecha.desc()).first()
    sync_error_lines = _parse_sync_errores_detail(last_sync)

    return {
        'today': today,
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
        'obras_hoy_rows': obras_hoy_rows,
        'recent_obras': recent_obras,
        'recent_logs': recent_logs,
        'last_sync': last_sync,
        'sync_error_lines': sync_error_lines,
        'chart_solicitud_labels': list(solicitudes_por_estado.keys()),
        'chart_solicitud_values': list(solicitudes_por_estado.values()),
    }


def get_jefe_panel_context(user):
    """Panel de control filtrado a las obras del jefe de obra."""
    today = today_local()
    chart_start = today - timedelta(days=13)
    obra_ids = _obra_ids_del_jefe(user.id)

    mis_obras = (
        Obra.query.filter(
            Obra.jefe_obra_id == user.id,
            Obra.is_deleted.is_(False),
        )
        .options(joinedload(Obra.jefe_obra))
        .all()
    ) if obra_ids else []

    obras_en_curso = sum(1 for o in mis_obras if o.estado == 'En Curso')
    total_obras = len(mis_obras)

    if obra_ids:
        asignaciones_hoy = Asignacion.query.filter(
            Asignacion.fecha == today,
            Asignacion.obra_id.in_(obra_ids),
        ).count()
        planificados_hoy = (
            db.session.query(func.count(distinct(Asignacion.user_id)))
            .filter(Asignacion.fecha == today, Asignacion.obra_id.in_(obra_ids))
            .scalar() or 0
        )
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
        fichajes_hoy = RegistroFichaje.query.filter(
            RegistroFichaje.fecha == today,
            _filtro_auditoria_obras(obra_ids),
        ).all()
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
    fichajes_ok_hoy = sum(1 for f in fichajes_hoy if f.estado == 'Correcto')
    fichajes_incidente_hoy = sum(
        1 for f in fichajes_hoy
        if f.estado in ('Conflicto', 'Paracaidista', 'Ausencia')
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

    recent_obras = [o for o in mis_obras if o.estado == 'En Curso'][:5]

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
        'obras_hoy_rows': obras_hoy_rows,
        'recent_obras': recent_obras,
        'recent_logs': recent_logs,
        'chart_solicitud_labels': list(solicitudes_por_estado.keys()),
        'chart_solicitud_values': list(solicitudes_por_estado.values()),
    }
