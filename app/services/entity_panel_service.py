# app/services/entity_panel_service.py
"""Estadísticas e indicadores para fichas de Obra, Empleado y Empresa."""

from datetime import timedelta

from flask import url_for
from sqlalchemy import func, distinct, or_

from app import db
from app.models import (
    User, Asignacion, Solicitud, RegistroFichaje, Rating,
    ROLE_OPERARIO,
)
from app.utils.timezone_utils import today_local

OPEN_SOLICITUD = ('PENDIENTE', 'EN_PROCESO')
FICHAJE_INCIDENTES = ('Conflicto', 'Paracaidista', 'Ausencia')
FICHAJE_OK = ('Correcto', 'Correcto_Automatico')


def _month_bounds(ref):
    start = ref.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
    return start, end


def _asignaciones_empresa_q(company_id):
    """Asignaciones atribuibles a una empresa (snapshot o empresa actual del operario)."""
    return (
        Asignacion.query
        .outerjoin(User, Asignacion.user_id == User.id)
        .filter(or_(Asignacion.company_id == company_id, User.company_id == company_id))
    )


def get_obra_panel_stats(obra):
    today = today_local()
    month_start, month_end = _month_bounds(today)
    chart_start = today - timedelta(days=13)
    obra_id = obra.id

    q_hoy = Asignacion.query.filter(Asignacion.obra_id == obra_id, Asignacion.fecha == today)
    operarios_hoy = q_hoy.with_entities(func.count(distinct(Asignacion.user_id))).scalar() or 0
    empresas_hoy = (
        q_hoy.filter(Asignacion.company_id.isnot(None))
        .with_entities(func.count(distinct(Asignacion.company_id)))
        .scalar() or 0
    )

    limite = obra.limite_trabajadores or 0
    ocupacion_pct = round(operarios_hoy / limite * 100) if limite > 0 else None

    dias_mes = (
        Asignacion.query.filter(
            Asignacion.obra_id == obra_id,
            Asignacion.fecha >= month_start,
            Asignacion.fecha <= month_end,
        ).count()
    )

    operarios_unicos_mes = (
        db.session.query(func.count(distinct(Asignacion.user_id)))
        .filter(
            Asignacion.obra_id == obra_id,
            Asignacion.fecha >= month_start,
            Asignacion.fecha <= month_end,
        )
        .scalar() or 0
    )

    proximos_7 = (
        Asignacion.query.filter(
            Asignacion.obra_id == obra_id,
            Asignacion.fecha > today,
            Asignacion.fecha <= today + timedelta(days=7),
        ).count()
    )

    solicitudes_abiertas = Solicitud.query.filter(
        Solicitud.obra_id == obra_id,
        Solicitud.estado.in_(OPEN_SOLICITUD),
    ).all()
    plazas_pendientes = sum(
        max(0, (s.cantidad_solicitada or 0) - (s.cantidad_cubierta or 0))
        for s in solicitudes_abiertas
        if s.tipo == 'generica'
    )

    fichajes_hoy = RegistroFichaje.query.filter(
        RegistroFichaje.fecha == today,
        or_(
            RegistroFichaje.obra_planificada_id == obra_id,
            RegistroFichaje.obra_real_id == obra_id,
        ),
    ).all()
    fichajes_ok = sum(1 for f in fichajes_hoy if f.estado in FICHAJE_OK)
    fichajes_alertas = sum(1 for f in fichajes_hoy if f.estado in FICHAJE_INCIDENTES)

    asig_rows = (
        db.session.query(Asignacion.fecha, func.count(Asignacion.id))
        .filter(
            Asignacion.obra_id == obra_id,
            Asignacion.fecha >= chart_start,
            Asignacion.fecha <= today,
        )
        .group_by(Asignacion.fecha)
        .all()
    )
    asig_map = {f: c for f, c in asig_rows}
    chart_14d = [asig_map.get(chart_start + timedelta(days=i), 0) for i in range(14)]

    dias_restantes = None
    if obra.fecha_fin and obra.fecha_fin >= today:
        dias_restantes = (obra.fecha_fin - today).days
    elif obra.fecha_fin and obra.fecha_fin < today:
        dias_restantes = -(today - obra.fecha_fin).days

    stats = [
        {
            'key': 'operarios_hoy',
            'label': 'Operarios hoy',
            'value': operarios_hoy,
            'sub': f'Cupo {limite}' if limite else 'Sin límite definido',
            'icon': 'fa-users',
            'tone': 'green' if limite and operarios_hoy >= limite else ('amber' if limite and operarios_hoy >= limite * 0.85 else 'green'),
            'progress': min(100, ocupacion_pct) if ocupacion_pct is not None else None,
        },
        {
            'key': 'empresas_hoy',
            'label': 'Empresas hoy',
            'value': empresas_hoy,
            'sub': 'Subcontratas activas',
            'icon': 'fa-briefcase',
            'tone': 'blue',
        },
        {
            'key': 'solicitudes',
            'label': 'Solicitudes abiertas',
            'value': len(solicitudes_abiertas),
            'sub': f'{plazas_pendientes} plazas pendientes' if plazas_pendientes else 'Sin plazas genéricas',
            'icon': 'fa-clipboard-list',
            'tone': 'amber' if solicitudes_abiertas else 'slate',
            'href': url_for('admin.solicitudes_list', obra_id=obra_id) if solicitudes_abiertas else None,
        },
        {
            'key': 'dias_mes',
            'label': 'Días-persona mes',
            'value': dias_mes,
            'sub': f'{operarios_unicos_mes} operarios distintos',
            'icon': 'fa-calendar-check',
            'tone': 'slate',
        },
        {
            'key': 'proximos_7',
            'label': 'Próx. 7 días',
            'value': proximos_7,
            'sub': 'Asignaciones planificadas',
            'icon': 'fa-forward',
            'tone': 'slate',
        },
        {
            'key': 'fichajes',
            'label': 'Fichajes hoy',
            'value': f'{fichajes_ok}/{len(fichajes_hoy)}' if fichajes_hoy else '—',
            'sub': f'{fichajes_alertas} incidencias' if fichajes_alertas else ('Sin registros' if not fichajes_hoy else 'Sin incidencias'),
            'icon': 'fa-fingerprint',
            'tone': 'red' if fichajes_alertas else ('green' if fichajes_hoy else 'slate'),
        },
    ]

    if dias_restantes is not None:
        stats.append({
            'key': 'plazo',
            'label': 'Plazo obra',
            'value': abs(dias_restantes),
            'sub': 'días restantes' if dias_restantes >= 0 else 'días desde cierre',
            'icon': 'fa-hourglass-half',
            'tone': 'amber' if 0 <= dias_restantes <= 14 else ('red' if dias_restantes < 0 else 'slate'),
        })

    return {
        'stats': stats,
        'chart_14d': chart_14d,
        'chart_14d_max': max(chart_14d) if chart_14d else 1,
        'operarios_hoy': operarios_hoy,
        'ocupacion_pct': ocupacion_pct,
    }


def get_worker_panel_stats(worker):
    today = today_local()
    month_start, month_end = _month_bounds(today)
    range_30 = today - timedelta(days=29)
    user_id = worker.id

    dias_mes = Asignacion.query.filter(
        Asignacion.user_id == user_id,
        Asignacion.fecha >= month_start,
        Asignacion.fecha <= month_end,
    ).count()

    obras_distintas_30 = (
        db.session.query(func.count(distinct(Asignacion.obra_id)))
        .filter(
            Asignacion.user_id == user_id,
            Asignacion.fecha >= range_30,
            Asignacion.fecha <= today,
        )
        .scalar() or 0
    )

    multi_obra_rows = len(
        db.session.query(Asignacion.fecha)
        .filter(
            Asignacion.user_id == user_id,
            Asignacion.fecha >= range_30,
            Asignacion.fecha <= today,
        )
        .group_by(Asignacion.fecha)
        .having(func.count(distinct(Asignacion.obra_id)) > 1)
        .all()
    )

    proxima = (
        Asignacion.query.filter(Asignacion.user_id == user_id, Asignacion.fecha > today)
        .order_by(Asignacion.fecha.asc())
        .first()
    )

    asignado_hoy = Asignacion.query.filter(
        Asignacion.user_id == user_id, Asignacion.fecha == today
    ).count()

    solicitudes_abiertas = Solicitud.query.filter(
        Solicitud.empleado_id == user_id,
        Solicitud.estado.in_(OPEN_SOLICITUD),
    ).count()

    ratings_count = Rating.query.filter_by(user_id=user_id, is_active=True).count()

    fichajes_30 = RegistroFichaje.query.filter(
        RegistroFichaje.user_id == user_id,
        RegistroFichaje.fecha >= range_30,
        RegistroFichaje.fecha <= today,
    ).all()
    fichajes_ok = sum(1 for f in fichajes_30 if f.estado in FICHAJE_OK)
    fichajes_alertas = sum(1 for f in fichajes_30 if f.estado in FICHAJE_INCIDENTES)
    fichaje_total = len(fichajes_30)
    fichaje_pct = round(fichajes_ok / fichaje_total * 100) if fichaje_total else None

    chart_start = today - timedelta(days=13)
    asig_rows = (
        db.session.query(Asignacion.fecha, func.count(Asignacion.obra_id))
        .filter(
            Asignacion.user_id == user_id,
            Asignacion.fecha >= chart_start,
            Asignacion.fecha <= today + timedelta(days=13),
        )
        .group_by(Asignacion.fecha)
        .all()
    )
    asig_map = {f: c for f, c in asig_rows}
    chart_14d = [asig_map.get(chart_start + timedelta(days=i), 0) for i in range(14)]

    stats = [
        {
            'key': 'hoy',
            'label': 'Asignado hoy',
            'value': asignado_hoy,
            'sub': f'{asignado_hoy} obra(s)' if asignado_hoy else 'Libre hoy',
            'icon': 'fa-calendar-day',
            'tone': 'green' if asignado_hoy else 'slate',
        },
        {
            'key': 'dias_mes',
            'label': 'Días asignados mes',
            'value': dias_mes,
            'sub': 'En calendario actual',
            'icon': 'fa-calendar-alt',
            'tone': 'slate',
        },
        {
            'key': 'obras_30',
            'label': 'Obras (30 días)',
            'value': obras_distintas_30,
            'sub': f'{multi_obra_rows} días multi-obra' if multi_obra_rows else 'Sin pluriempleo',
            'icon': 'fa-building',
            'tone': 'amber' if multi_obra_rows else 'blue',
        },
        {
            'key': 'fichajes',
            'label': 'Fichajes 30 días',
            'value': f'{fichaje_pct}%' if fichaje_pct is not None else '—',
            'sub': f'{fichajes_alertas} incidencias' if fichajes_alertas else ('Sin datos' if not fichaje_total else 'Correctos'),
            'icon': 'fa-fingerprint',
            'tone': 'red' if fichajes_alertas else ('green' if fichaje_pct and fichaje_pct >= 90 else 'slate'),
            'progress': fichaje_pct,
        },
        {
            'key': 'reputacion',
            'label': 'Reputación',
            'value': worker.reputation_score,
            'sub': f'{ratings_count} valoraciones activas',
            'icon': 'fa-star',
            'tone': 'green' if worker.reputation_score > 0 else ('red' if worker.reputation_score < 0 else 'slate'),
        },
        {
            'key': 'solicitudes',
            'label': 'Solicitudes',
            'value': solicitudes_abiertas,
            'sub': 'Abiertas vinculadas',
            'icon': 'fa-clipboard-list',
            'tone': 'amber' if solicitudes_abiertas else 'slate',
        },
    ]

    if proxima:
        stats.append({
            'key': 'proxima',
            'label': 'Próxima asignación',
            'value': proxima.fecha.strftime('%d/%m'),
            'sub': proxima.obra.nombre if proxima.obra else 'Obra',
            'icon': 'fa-arrow-right',
            'tone': 'blue',
        })

    return {
        'stats': stats,
        'chart_14d': chart_14d,
        'chart_14d_max': max(chart_14d) if chart_14d else 1,
    }


def get_company_panel_stats(company):
    today = today_local()
    month_start, month_end = _month_bounds(today)
    range_30 = today - timedelta(days=29)
    company_id = company.id

    workers_total = User.query.filter_by(
        company_id=company_id, role=ROLE_OPERARIO, is_deleted=False
    ).count()
    workers_active = User.query.filter_by(
        company_id=company_id, role=ROLE_OPERARIO, is_deleted=False, active=True
    ).count()

    q_emp = _asignaciones_empresa_q(company_id)

    planificados_hoy = (
        q_emp.filter(Asignacion.fecha == today)
        .with_entities(func.count(distinct(Asignacion.user_id)))
        .scalar() or 0
    )

    intervenciones_30 = q_emp.filter(
        Asignacion.fecha >= range_30,
        Asignacion.fecha <= today,
    ).count()

    obras_30 = (
        q_emp.filter(Asignacion.fecha >= range_30, Asignacion.fecha <= today)
        .with_entities(func.count(distinct(Asignacion.obra_id)))
        .scalar() or 0
    )

    dias_mes = q_emp.filter(
        Asignacion.fecha >= month_start,
        Asignacion.fecha <= month_end,
    ).count()

    worker_ids = [
        uid for (uid,) in User.query.filter_by(
            company_id=company_id, role=ROLE_OPERARIO, is_deleted=False
        ).with_entities(User.id).all()
    ]

    avg_rating = None
    ratings_count = 0
    if worker_ids:
        row = (
            db.session.query(func.avg(Rating.score), func.count(Rating.id))
            .filter(Rating.user_id.in_(worker_ids), Rating.is_active.is_(True))
            .first()
        )
        if row and row[1]:
            avg_rating = round(float(row[0]), 1)
            ratings_count = row[1]

    solicitudes_abiertas = (
        Solicitud.query
        .outerjoin(User, Solicitud.empleado_id == User.id)
        .filter(
            Solicitud.estado.in_(OPEN_SOLICITUD),
            or_(
                Solicitud.perfil_empresa_id == company_id,
                User.company_id == company_id,
            ),
        )
        .count()
    )

    fichajes_alertas = 0
    if worker_ids:
        fichajes_alertas = RegistroFichaje.query.filter(
            RegistroFichaje.user_id.in_(worker_ids),
            RegistroFichaje.fecha >= range_30,
            RegistroFichaje.fecha <= today,
            RegistroFichaje.estado.in_(FICHAJE_INCIDENTES),
        ).count()

    ocupacion_pct = round(planificados_hoy / workers_active * 100) if workers_active else None

    chart_start = today - timedelta(days=13)
    asig_rows = (
        q_emp.filter(Asignacion.fecha >= chart_start, Asignacion.fecha <= today)
        .with_entities(Asignacion.fecha, func.count(Asignacion.id))
        .group_by(Asignacion.fecha)
        .all()
    )
    asig_map = {f: c for f, c in asig_rows}
    chart_14d = [asig_map.get(chart_start + timedelta(days=i), 0) for i in range(14)]

    personal_url = url_for('admin.personal', company_id=company_id) + ('#internos' if company.is_internal else '#operarios')

    stats = [
        {
            'key': 'plantilla',
            'label': 'Plantilla',
            'value': workers_total,
            'sub': f'{workers_active} activos',
            'icon': 'fa-users',
            'tone': 'green',
            'href': personal_url,
        },
        {
            'key': 'hoy',
            'label': 'En obra hoy',
            'value': planificados_hoy,
            'sub': f'{ocupacion_pct}% de activos' if ocupacion_pct is not None else 'Sin activos',
            'icon': 'fa-hard-hat',
            'tone': 'green',
            'progress': ocupacion_pct,
        },
        {
            'key': 'obras',
            'label': 'Obras (30 días)',
            'value': obras_30,
            'sub': 'Con personal asignado',
            'icon': 'fa-building',
            'tone': 'blue',
        },
        {
            'key': 'intervenciones',
            'label': 'Intervenciones 30d',
            'value': intervenciones_30,
            'sub': f'{dias_mes} días-persona este mes',
            'icon': 'fa-calendar-check',
            'tone': 'slate',
        },
        {
            'key': 'valoracion',
            'label': 'Valoración media',
            'value': avg_rating if avg_rating is not None else '—',
            'sub': f'{ratings_count} valoraciones' if ratings_count else 'Sin valoraciones',
            'icon': 'fa-star',
            'tone': 'amber' if avg_rating else 'slate',
            'href': personal_url if ratings_count else None,
        },
        {
            'key': 'solicitudes',
            'label': 'Solicitudes',
            'value': solicitudes_abiertas,
            'sub': 'Abiertas de la empresa',
            'icon': 'fa-clipboard-list',
            'tone': 'amber' if solicitudes_abiertas else 'slate',
        },
        {
            'key': 'fichajes',
            'label': 'Incidencias fichaje',
            'value': fichajes_alertas,
            'sub': 'Últimos 30 días',
            'icon': 'fa-exclamation-triangle',
            'tone': 'red' if fichajes_alertas else 'green',
        },
    ]

    return {
        'stats': stats,
        'chart_14d': chart_14d,
        'chart_14d_max': max(chart_14d) if chart_14d else 1,
        'avg_rating': avg_rating,
        'ratings_count': ratings_count,
    }
