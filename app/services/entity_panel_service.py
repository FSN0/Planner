# app/services/entity_panel_service.py
"""Estadísticas e indicadores para fichas de Obra, Empleado, Empresa y Vehículo."""

from datetime import timedelta

from flask import url_for
from sqlalchemy import func, distinct, or_

from app import db
from app.models import (
    User, Asignacion, Solicitud, RegistroFichaje, Rating,
    ROLE_OPERARIO,
)
from app.services.i18n_service import translate as _
from app.utils.timezone_utils import today_local

OPEN_SOLICITUD = ('PENDIENTE', 'EN_PROCESO')
FICHAJE_INCIDENTES = ('Conflicto', 'Paracaidista', 'Ausencia')
FICHAJE_OK = (
    'Correcto', 'Correcto_Automatico',
    'Resuelto_Movido', 'Resuelto_Asignado', 'Resuelto_Dividido',
    'Resuelto_Ignorado', 'Resuelto_Falta', 'Resuelto_Ausencia',
    'Exento_Ausencia', 'Cerrado_Multiobra',
)


def _tf(msgid, **kwargs):
    """Traduce msgid y aplica .format(**kwargs) sobre el resultado."""
    return _(msgid).format(**kwargs)


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


def _odometer_regs_for_worker(worker, start_date, end_date, end_exclusive=True):
    """RegistroOdometro del rango cuyo conductor Odoo (o planned_user) es este operario."""
    from sqlalchemy import or_
    from app.models import RegistroOdometro
    from app.services.vehicle_sync_service import _build_user_indexes, _match_driver_user, _norm_name

    q = RegistroOdometro.query.filter(RegistroOdometro.fecha >= start_date)
    if end_exclusive:
        q = q.filter(RegistroOdometro.fecha < end_date)
    else:
        q = q.filter(RegistroOdometro.fecha <= end_date)

    partner_ids = []
    ext = getattr(worker, 'external_ids', None) or {}
    for key in ('odoo', 'odoo_partner', 'partner'):
        val = ext.get(key)
        if val is None or str(val).strip() == '':
            continue
        try:
            partner_ids.append(int(val))
        except (TypeError, ValueError):
            continue

    full_name = _norm_name(f"{getattr(worker, 'name', '') or ''} {getattr(worker, 'lastname', '') or ''}")

    # Candidatos SQL (planned_user / partner_id) + filas con nombre para match por texto
    clauses = [RegistroOdometro.planned_user_id == worker.id]
    if partner_ids:
        clauses.append(RegistroOdometro.odoo_driver_partner_id.in_(partner_ids))
    if full_name:
        clauses.append(RegistroOdometro.odoo_driver_name.isnot(None))

    candidates = q.filter(or_(*clauses)).all() if clauses else []

    users_by_odoo, users_by_name = _build_user_indexes()
    matched = []
    seen = set()
    for reg in candidates:
        if reg.id in seen:
            continue
        if reg.planned_user_id == worker.id:
            matched.append(reg)
            seen.add(reg.id)
            continue
        # Solo uso real respaldado por viaje tms.shipment (NO odómetro contaminado)
        if not getattr(reg, 'viaje_odoo_id', None):
            continue
        has_usage = bool(
            reg.valor is not None
            or reg.qty_km is not None
            or (reg.odoo_driver_name or '').strip()
            or reg.odoo_driver_partner_id
        )
        if not has_usage:
            continue
        u = _match_driver_user(
            reg.odoo_driver_partner_id,
            reg.odoo_driver_name,
            users_by_odoo,
            users_by_name,
        )
        if u and u.id == worker.id:
            matched.append(reg)
            seen.add(reg.id)
    return matched


def get_worker_vehicle_day_map(worker, start_date, end_date, end_exclusive=True):
    """
    Días con vehículo para un operario: planificación local ∪ uso Odoo.
    Devuelve {fecha: {label, vehiculo_id, km, source, plan_status, ...}}.

    plan_status (misma regla que el calendario del coche):
      - plan: asignado, sin dato Odoo aún (hoy/futuro)
      - cumplido: asignado + km Odoo (misma persona)
      - conflicto: km sin plan | plan pasado sin km | otro conductor
      - ausencia: asignado en vacaciones/baja
    """
    from app.models import AsignacionVehiculo, LEAVE_STATUS_APROBADA, RegistroOdometro, Vehiculo
    from app.services.leave_service import build_leaves_by_user, leave_covering
    from app.services.vehicle_sync_service import _build_user_indexes, _match_driver_user

    day_map = {}
    hoy = today_local()

    planned = AsignacionVehiculo.query.filter(
        AsignacionVehiculo.user_id == worker.id,
        AsignacionVehiculo.fecha >= start_date,
    )
    if end_exclusive:
        planned = planned.filter(AsignacionVehiculo.fecha < end_date)
    else:
        planned = planned.filter(AsignacionVehiculo.fecha <= end_date)
    planned = planned.all()

    veh_ids = {a.vehiculo_id for a in planned}
    odo_regs = []
    try:
        odo_regs = _odometer_regs_for_worker(worker, start_date, end_date, end_exclusive=end_exclusive)
        veh_ids |= {r.vehiculo_id for r in odo_regs}
    except Exception:
        odo_regs = []

    planned_veh_dates = {(a.vehiculo_id, a.fecha) for a in planned}
    odo_on_planned = {}
    if planned_veh_dates:
        p_veh_ids = {vid for vid, _ in planned_veh_dates}
        p_fechas = {f for _, f in planned_veh_dates}
        try:
            for r in RegistroOdometro.query.filter(
                RegistroOdometro.vehiculo_id.in_(p_veh_ids),
                RegistroOdometro.fecha.in_(p_fechas),
            ).all():
                if (r.vehiculo_id, r.fecha) in planned_veh_dates:
                    odo_on_planned[(r.vehiculo_id, r.fecha)] = r
                    veh_ids.add(r.vehiculo_id)
        except Exception:
            odo_on_planned = {}

    vehiculos = {
        v.id: v for v in Vehiculo.query.filter(Vehiculo.id.in_(veh_ids)).all()
    } if veh_ids else {}

    range_end = (end_date - timedelta(days=1)) if end_exclusive and end_date > start_date else end_date
    leaves_idx = build_leaves_by_user([worker.id], start_date, range_end)
    user_leaves = leaves_idx.get(worker.id, [])

    users_by_odoo, users_by_name = _build_user_indexes()

    def _odo_has_usage(odo):
        return bool(
            odo and (
                odo.valor is not None
                or odo.qty_km is not None
                or (odo.odoo_driver_name or '').strip()
                or odo.odoo_driver_partner_id
            )
        )

    for a in planned:
        v = vehiculos.get(a.vehiculo_id)
        label = v.label() if v else f"Vehículo #{a.vehiculo_id}"
        odo = odo_on_planned.get((a.vehiculo_id, a.fecha))
        km = None
        if odo:
            if odo.qty_km is not None:
                km = odo.qty_km
            elif odo.valor is not None:
                km = odo.valor

        leave = leave_covering(user_leaves, a.fecha)
        on_leave = bool(leave and leave.estado == LEAVE_STATUS_APROBADA)

        effective_other = None
        mismatch = False
        if _odo_has_usage(odo):
            matched = _match_driver_user(
                odo.odoo_driver_partner_id,
                odo.odoo_driver_name,
                users_by_odoo,
                users_by_name,
            )
            if matched and matched.id != worker.id:
                mismatch = True
                effective_other = f"{matched.name} {matched.lastname}".strip()
            elif not matched and (odo.odoo_driver_name or '').strip():
                mismatch = True
                effective_other = (odo.odoo_driver_name or '').strip()

        if on_leave:
            plan_status = 'ausencia'
            source = 'planificado'
        elif mismatch:
            plan_status = 'conflicto'
            source = 'planificado'
        elif _odo_has_usage(odo):
            plan_status = 'cumplido'
            source = 'ambos'
        elif a.fecha < hoy:
            # Sin ERP no hay km: el pasado planificado no es un conflicto.
            from flask import g
            tenant = getattr(g, 'current_tenant', None)
            mods = getattr(tenant, 'modulos_activos', None) or {} if tenant else {}
            if mods.get('odoo'):
                plan_status = 'conflicto'
                source = 'planificado'
            else:
                plan_status = 'plan'
                source = 'planificado'
        else:
            plan_status = 'plan'
            source = 'planificado'

        day_map[a.fecha] = {
            'label': label,
            'vehiculo_id': a.vehiculo_id,
            'km': km,
            'source': source,
            'plan_status': plan_status,
            'en_ausencia': on_leave,
            'ausencia_tipo': leave.tipo if on_leave else None,
            'mismatch': mismatch,
            'effective_other': effective_other,
            'conductor': (odo.odoo_driver_name if odo else None) or (v.odoo_driver_name if v else None),
        }

    for r in odo_regs:
        if r.fecha in day_map and day_map[r.fecha]['vehiculo_id'] == r.vehiculo_id:
            continue
        if r.fecha in day_map:
            continue
        v = vehiculos.get(r.vehiculo_id)
        label = v.label() if v else f"Vehículo #{r.vehiculo_id}"
        km = r.qty_km if r.qty_km is not None else (r.valor if r.valor is not None else None)
        day_map[r.fecha] = {
            'label': label,
            'vehiculo_id': r.vehiculo_id,
            'km': km,
            'source': 'odoo',
            'plan_status': 'conflicto',  # km sin plan propio
            'en_ausencia': False,
            'ausencia_tipo': None,
            'mismatch': False,
            'effective_other': None,
            'conductor': r.odoo_driver_name or (v.odoo_driver_name if v else None),
        }

    return day_map


def get_worker_vehicle_rows(worker, days=30):
    """Últimos N días: AsignacionVehiculo ∪ uso Odoo (misma lógica que el calendario del vehículo)."""
    today = today_local()
    start = today - timedelta(days=days - 1)
    day_map = get_worker_vehicle_day_map(worker, start, today, end_exclusive=False)
    rows = []
    for fecha in sorted(day_map.keys(), reverse=True):
        info = day_map[fecha]
        rows.append({
            'fecha': fecha,
            'vehiculo_id': info['vehiculo_id'],
            'vehiculo_label': info['label'],
            'km': info.get('km'),
            'conductor': info.get('conductor'),
            'source': info.get('source'),
        })
    return rows


def get_obra_vehicle_rows(obra, days=30):
    """Days when operario assigned to obra ALSO has AsignacionVehiculo that day."""
    from app.models import Asignacion, AsignacionVehiculo, RegistroOdometro, Vehiculo, User
    today = today_local()
    start = today - timedelta(days=days - 1)
    obra_asigs = Asignacion.query.filter(
        Asignacion.obra_id == obra.id,
        Asignacion.fecha >= start,
        Asignacion.fecha <= today,
        Asignacion.user_id.isnot(None),
    ).all()
    if not obra_asigs:
        return []
    pairs = {(a.user_id, a.fecha) for a in obra_asigs}
    user_ids = {u for u, _ in pairs}
    fechas = {f for _, f in pairs}
    veh_asigs = AsignacionVehiculo.query.filter(
        AsignacionVehiculo.user_id.in_(user_ids),
        AsignacionVehiculo.fecha.in_(fechas),
    ).all()
    veh_asigs = [a for a in veh_asigs if (a.user_id, a.fecha) in pairs]
    if not veh_asigs:
        return []
    veh_ids = {a.vehiculo_id for a in veh_asigs}
    vehiculos = {v.id: v for v in Vehiculo.query.filter(Vehiculo.id.in_(veh_ids)).all()}
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()}
    odo_map = {}
    try:
        for r in RegistroOdometro.query.filter(
            RegistroOdometro.vehiculo_id.in_(veh_ids),
            RegistroOdometro.fecha.in_(fechas),
        ).all():
            odo_map[(r.vehiculo_id, r.fecha)] = r
    except Exception:
        odo_map = {}
    rows = []
    for a in sorted(veh_asigs, key=lambda x: (x.fecha, x.id), reverse=True):
        v = vehiculos.get(a.vehiculo_id)
        u = users.get(a.user_id)
        odo = odo_map.get((a.vehiculo_id, a.fecha))
        km = odo.valor if odo and odo.valor is not None else None
        if km is None and v and v.odoo_odometer_date == a.fecha:
            km = v.odoo_odometer_value
        rows.append({
            'fecha': a.fecha,
            'vehiculo_id': a.vehiculo_id,
            'vehiculo_label': v.label() if v else f'#{a.vehiculo_id}',
            'operario': f'{u.name} {u.lastname}' if u else f'#{a.user_id}',
            'km': km,
        })
    return rows


def get_vehicle_panel_stats(vehiculo):
    """KPIs for vehicle ficha: planificación local + uso Odoo (odómetros)."""
    from app.models import AsignacionVehiculo, RegistroOdometro, SolicitudVehiculo
    from app.services.vehicle_sync_service import _build_user_indexes, _match_driver_user
    from sqlalchemy import or_

    today = today_local()
    range_30 = today - timedelta(days=29)
    veh_id = vehiculo.id

    def _odo_usage_filter():
        return or_(
            RegistroOdometro.valor.isnot(None),
            RegistroOdometro.odoo_driver_name.isnot(None),
            RegistroOdometro.odoo_driver_partner_id.isnot(None),
        )

    planned_hoy = AsignacionVehiculo.query.filter_by(
        vehiculo_id=veh_id, fecha=today
    ).first()
    odo_hoy = (
        RegistroOdometro.query
        .filter(
            RegistroOdometro.vehiculo_id == veh_id,
            RegistroOdometro.fecha == today,
            _odo_usage_filter(),
        )
        .first()
    )

    users_by_odoo, users_by_name = _build_user_indexes()
    conductor_hoy = None
    usado_hoy = False
    if planned_hoy and planned_hoy.user:
        conductor_hoy = f'{planned_hoy.user.name} {planned_hoy.user.lastname}'
        usado_hoy = True
    elif odo_hoy:
        usado_hoy = True
        matched = _match_driver_user(
            odo_hoy.odoo_driver_partner_id,
            odo_hoy.odoo_driver_name,
            users_by_odoo,
            users_by_name,
        )
        if matched:
            conductor_hoy = f'{matched.name} {matched.lastname}'
        elif (odo_hoy.odoo_driver_name or '').strip():
            conductor_hoy = f'{odo_hoy.odoo_driver_name.strip()} (no está en el programa)'
        else:
            conductor_hoy = 'Uso Odoo (sin conductor)'

    planned_fechas = {
        f for (f,) in db.session.query(AsignacionVehiculo.fecha).filter(
            AsignacionVehiculo.vehiculo_id == veh_id,
            AsignacionVehiculo.fecha >= range_30,
            AsignacionVehiculo.fecha <= today,
        ).all()
    }
    odo_fechas = {
        f for (f,) in db.session.query(RegistroOdometro.fecha).filter(
            RegistroOdometro.vehiculo_id == veh_id,
            RegistroOdometro.fecha >= range_30,
            RegistroOdometro.fecha <= today,
            _odo_usage_filter(),
        ).all()
    }
    dias_30 = len(planned_fechas | odo_fechas)

    # Conductores distintos: users de planificación + matches Odoo + nombres externos
    conductor_keys = set()
    for a in AsignacionVehiculo.query.filter(
        AsignacionVehiculo.vehiculo_id == veh_id,
        AsignacionVehiculo.fecha >= range_30,
        AsignacionVehiculo.fecha <= today,
    ).all():
        if a.user_id:
            conductor_keys.add(f'u:{a.user_id}')

    for r in RegistroOdometro.query.filter(
        RegistroOdometro.vehiculo_id == veh_id,
        RegistroOdometro.fecha >= range_30,
        RegistroOdometro.fecha <= today,
        _odo_usage_filter(),
    ).all():
        matched = _match_driver_user(
            r.odoo_driver_partner_id, r.odoo_driver_name, users_by_odoo, users_by_name
        )
        if matched:
            conductor_keys.add(f'u:{matched.id}')
        elif (r.odoo_driver_name or '').strip():
            conductor_keys.add(f'n:{(r.odoo_driver_name or "").strip().lower()}')
        elif r.odoo_driver_partner_id is not None:
            conductor_keys.add(f'p:{r.odoo_driver_partner_id}')
    conductores_unicos = len(conductor_keys)

    solicitudes_abiertas = SolicitudVehiculo.query.filter(
        SolicitudVehiculo.vehiculo_id == veh_id,
        SolicitudVehiculo.estado.in_(OPEN_SOLICITUD),
    ).count()

    chart_start = today - timedelta(days=13)
    usage_dates = set()
    for (f,) in db.session.query(AsignacionVehiculo.fecha).filter(
        AsignacionVehiculo.vehiculo_id == veh_id,
        AsignacionVehiculo.fecha >= chart_start,
        AsignacionVehiculo.fecha <= today,
    ).all():
        usage_dates.add(f)
    for (f,) in db.session.query(RegistroOdometro.fecha).filter(
        RegistroOdometro.vehiculo_id == veh_id,
        RegistroOdometro.fecha >= chart_start,
        RegistroOdometro.fecha <= today,
        _odo_usage_filter(),
    ).all():
        usage_dates.add(f)
    chart_14d = [
        1 if (chart_start + timedelta(days=i)) in usage_dates else 0
        for i in range(14)
    ]

    km_txt = '—'
    if vehiculo.odoo_odometer_value is not None:
        km_txt = f'{int(vehiculo.odoo_odometer_value):,}'.replace(',', '.')
        if vehiculo.odoo_odometer_date:
            km_txt = f'{km_txt} ({vehiculo.odoo_odometer_date.strftime("%d/%m")})'

    stats = [
        {
            'key': 'hoy',
            'label': 'En uso hoy',
            'value': 1 if usado_hoy else 0,
            'sub': conductor_hoy or 'Libre hoy',
            'icon': 'fa-calendar-day',
            'tone': 'green' if usado_hoy else 'slate',
        },
        {
            'key': 'dias_30',
            'label': 'Días en uso (30d)',
            'value': dias_30,
            'sub': 'Planificado + Odoo',
            'icon': 'fa-calendar-check',
            'tone': 'slate',
        },
        {
            'key': 'conductores',
            'label': 'Conductores (30d)',
            'value': conductores_unicos,
            'sub': 'Personas distintas',
            'icon': 'fa-users',
            'tone': 'blue',
        },
        {
            'key': 'odometro',
            'label': 'Odómetro Odoo',
            'value': km_txt,
            'sub': vehiculo.odoo_driver_name or 'Sin conductor Odoo',
            'icon': 'fa-tachometer-alt',
            'tone': 'slate',
        },
        {
            'key': 'solicitudes',
            'label': 'Solicitudes abiertas',
            'value': solicitudes_abiertas,
            'sub': 'Pendientes / en proceso',
            'icon': 'fa-clipboard-list',
            'tone': 'amber' if solicitudes_abiertas else 'slate',
            'href': url_for('admin.solicitudes_list', seccion='vehiculos') if solicitudes_abiertas else None,
        },
    ]

    return {
        'stats': stats,
        'chart_14d': chart_14d,
        'chart_14d_max': max(chart_14d) if chart_14d else 1,
    }


def get_vehicle_history_rows(vehiculo, days=30):
    """Últimos N días: planificación local + uso Odoo (odómetro), unidos por fecha."""
    from app.models import AsignacionVehiculo, Asignacion, RegistroOdometro, User, Obra
    from app.services.vehicle_sync_service import _build_user_indexes, _match_driver_user

    try:
        days = int(days or 30)
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(730, days))

    today = today_local()
    start = today - timedelta(days=days - 1)
    veh_id = vehiculo.id

    asignaciones = (
        AsignacionVehiculo.query
        .filter(
            AsignacionVehiculo.vehiculo_id == veh_id,
            AsignacionVehiculo.fecha >= start,
            AsignacionVehiculo.fecha <= today,
        )
        .all()
    )
    planned_by_date = {a.fecha: a for a in asignaciones}

    odo_regs = RegistroOdometro.query.filter(
        RegistroOdometro.vehiculo_id == veh_id,
        RegistroOdometro.fecha >= start,
        RegistroOdometro.fecha <= today,
    ).all()
    odo_by_date = {
        r.fecha: r for r in odo_regs
        if r.valor is not None or (r.odoo_driver_name or '').strip() or r.odoo_driver_partner_id
    }

    if not planned_by_date and not odo_by_date:
        return []

    users_by_odoo, users_by_name = _build_user_indexes()
    user_ids = {a.user_id for a in asignaciones if a.user_id}
    for r in odo_regs:
        matched = _match_driver_user(
            r.odoo_driver_partner_id, r.odoo_driver_name, users_by_odoo, users_by_name
        )
        if matched:
            user_ids.add(matched.id)
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}

    fechas = set(planned_by_date.keys()) | set(odo_by_date.keys())
    obra_map = {}
    if user_ids and fechas:
        for a in Asignacion.query.filter(
            Asignacion.user_id.in_(user_ids),
            Asignacion.fecha.in_(fechas),
        ).all():
            key = (a.user_id, a.fecha)
            if key not in obra_map:
                obra_map[key] = a

    obra_ids = {a.obra_id for a in obra_map.values() if a.obra_id}
    obras = {o.id: o for o in Obra.query.filter(Obra.id.in_(obra_ids)).all()} if obra_ids else {}

    rows = []
    for fecha in sorted(fechas, reverse=True):
        a = planned_by_date.get(fecha)
        odo = odo_by_date.get(fecha)

        planned_user = users.get(a.user_id) if a else None
        matched = None
        if odo:
            matched = _match_driver_user(
                odo.odoo_driver_partner_id, odo.odoo_driver_name, users_by_odoo, users_by_name
            )

        display_user = planned_user or matched
        user_id = display_user.id if display_user else (a.user_id if a else None)

        if planned_user:
            operario = f'{planned_user.name} {planned_user.lastname}'
            origen = 'planificado'
        elif matched:
            operario = f'{matched.name} {matched.lastname}'
            origen = 'odoo'
        elif odo and (odo.odoo_driver_name or '').strip():
            operario = f'{odo.odoo_driver_name.strip()} (no está en el programa)'
            origen = 'odoo_externo'
        elif odo:
            operario = 'Uso Odoo (sin conductor)'
            origen = 'odoo'
        else:
            operario = f'#{a.user_id}' if a else '—'
            origen = 'planificado'

        obra_asig = obra_map.get((user_id, fecha)) if user_id else None
        obra = obras.get(obra_asig.obra_id) if obra_asig and obra_asig.obra_id else None
        km = odo.valor if odo and odo.valor is not None else None
        if km is None and vehiculo.odoo_odometer_date == fecha:
            km = vehiculo.odoo_odometer_value
        driver = (odo.odoo_driver_name if odo else None) or None
        if not driver and vehiculo.odoo_odometer_date == fecha:
            driver = vehiculo.odoo_driver_name

        rows.append({
            'fecha': fecha,
            'user_id': user_id,
            'operario': operario,
            'origen': origen,
            'obra_id': obra.id if obra else None,
            'obra_label': (
                f'{obra.codigo} - {obra.nombre}' if obra and obra.codigo
                else (obra.nombre if obra else None)
            ),
            'km': km,
            'conductor': driver,
        })
    return rows


def get_obra_panel_stats(obra):
    today = today_local()
    month_start, month_end = _month_bounds(today)
    chart_start = today - timedelta(days=13)
    range_30 = today - timedelta(days=29)
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
            'sub': _tf('Cupo {n}', n=limite) if limite else 'Sin límite definido',
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
            'sub': _tf('{n} plazas pendientes', n=plazas_pendientes) if plazas_pendientes else 'Sin plazas genéricas',
            'icon': 'fa-clipboard-list',
            'tone': 'amber' if solicitudes_abiertas else 'slate',
            'href': url_for('admin.solicitudes_list', obra_id=obra_id) if solicitudes_abiertas else None,
        },
        {
            'key': 'dias_mes',
            'label': 'Días-persona mes',
            'value': dias_mes,
            'sub': _tf('{n} operarios distintos', n=operarios_unicos_mes),
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
            'sub': (
                _tf('{n} incidencias', n=fichajes_alertas) if fichajes_alertas
                else ('Sin registros' if not fichajes_hoy else 'Sin incidencias')
            ),
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
            'sub': _tf('{n} activos', n=workers_active),
            'icon': 'fa-users',
            'tone': 'green',
            'href': personal_url,
        },
        {
            'key': 'hoy',
            'label': 'En obra hoy',
            'value': planificados_hoy,
            'sub': _tf('{pct}% de activos', pct=ocupacion_pct) if ocupacion_pct is not None else 'Sin activos',
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
            'sub': _tf('{n} días-persona este mes', n=dias_mes),
            'icon': 'fa-calendar-check',
            'tone': 'slate',
        },
        {
            'key': 'valoracion',
            'label': 'Valoración media',
            'value': avg_rating if avg_rating is not None else '—',
            'sub': _tf('{n} valoraciones', n=ratings_count) if ratings_count else 'Sin valoraciones',
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
