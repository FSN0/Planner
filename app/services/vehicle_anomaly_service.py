# app/services/vehicle_anomaly_service.py
"""Detección de anomalías de vehículos (saltos de odómetro, plan vs reporte, uso en ausencia)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_

from app.models import AsignacionVehiculo, ConfiguracionGlobal, RegistroOdometro, Vehiculo
from app.services.vehicle_sync_service import _build_user_indexes, _match_driver_user


DEFAULT_THRESHOLDS = {
    'vehiculo_salto_km_dia': 400,
}


def _cfg_int(clave, default):
    row = ConfiguracionGlobal.query.filter_by(clave=clave).first()
    if not row or row.valor in (None, ''):
        return int(default)
    try:
        return int(float(str(row.valor).strip().replace(',', '.')))
    except (TypeError, ValueError):
        return int(default)


def get_odometer_jump_thresholds():
    """Umbral único: km/día medios entre dos lecturas consecutivas."""
    return {
        'km_dia': max(1, _cfg_int(
            'vehiculo_salto_km_dia', DEFAULT_THRESHOLDS['vehiculo_salto_km_dia']
        )),
    }


def _classify_jump(delta_km, delta_dias, km_dia, thresholds):
    """
    Alerta si:
    - el odómetro baja, o
    - km_totales / días >= umbral km/día
      (1000 km en 1 día o en 2 con umbral 400 → alerta; en 3 → no).
    """
    motivos = []
    severidad = None

    if delta_km < 0:
        motivos.append('odometro_atras')
        severidad = 'alta'

    if delta_dias <= 0:
        delta_dias = 1

    if delta_km > 0 and km_dia >= thresholds['km_dia']:
        motivos.append('km_dia')
        severidad = 'alta'

    return severidad, motivos


def detect_odometer_jumps(fecha_desde, fecha_hasta, thresholds=None):
    """
    Compara lecturas consecutivas por vehículo.
    Incluye como 'prev' lecturas anteriores al rango para no perder el primer salto.
    Solo emite alertas cuya lectura actual cae dentro de [fecha_desde, fecha_hasta].
    """
    thresholds = thresholds or get_odometer_jump_thresholds()
    lookback = fecha_desde - timedelta(days=90)

    regs = (
        RegistroOdometro.query
        .filter(
            RegistroOdometro.fecha >= lookback,
            RegistroOdometro.fecha <= fecha_hasta,
            RegistroOdometro.valor.isnot(None),
            RegistroOdometro.viaje_odoo_id.isnot(None),
        )
        .order_by(RegistroOdometro.vehiculo_id.asc(), RegistroOdometro.fecha.asc(), RegistroOdometro.id.asc())
        .all()
    )

    by_vehicle = {}
    for r in regs:
        by_vehicle.setdefault(r.vehiculo_id, []).append(r)

    veh_ids = list(by_vehicle.keys())
    vehiculos = {
        v.id: v for v in Vehiculo.query.filter(Vehiculo.id.in_(veh_ids)).all()
    } if veh_ids else {}

    jumps = []
    for veh_id, series in by_vehicle.items():
        prev = None
        for cur in series:
            if prev is None:
                prev = cur
                continue
            if cur.fecha < fecha_desde:
                prev = cur
                continue
            # cur dentro del rango visible
            try:
                delta_km = float(cur.valor) - float(prev.valor)
            except (TypeError, ValueError):
                prev = cur
                continue
            delta_dias = (cur.fecha - prev.fecha).days
            if delta_dias < 0:
                prev = cur
                continue
            km_dia = delta_km / float(max(delta_dias, 1))
            severidad, motivos = _classify_jump(delta_km, delta_dias, km_dia, thresholds)
            if severidad:
                veh = vehiculos.get(veh_id) or cur.vehiculo
                jumps.append({
                    'vehiculo_id': veh_id,
                    'vehiculo': veh,
                    'fecha_anterior': prev.fecha,
                    'fecha_actual': cur.fecha,
                    'km_anterior': float(prev.valor),
                    'km_actual': float(cur.valor),
                    'delta_km': delta_km,
                    'delta_dias': max(delta_dias, 1),
                    'km_dia': km_dia,
                    'conductor_odoo': cur.odoo_driver_name,
                    'planned_user': cur.planned_user,
                    'severidad': severidad,
                    'motivos': motivos,
                    'reg_id': cur.id,
                })
            prev = cur

    jumps.sort(key=lambda j: (j['fecha_actual'], abs(j['delta_km'])), reverse=True)
    return jumps


def detect_cross_vehicle_reports(fecha_desde, fecha_hasta):
    """
    Operario planificado en vehículo A ese día, pero el viaje tms.shipment
    de ese día (matched a ese operario) está en vehículo B.
    """
    users_by_odoo, users_by_name = _build_user_indexes()

    asignaciones = AsignacionVehiculo.query.filter(
        AsignacionVehiculo.fecha >= fecha_desde,
        AsignacionVehiculo.fecha <= fecha_hasta,
    ).all()
    if not asignaciones:
        return []

    planned_by_user_date = {}
    for a in asignaciones:
        planned_by_user_date[(a.user_id, a.fecha)] = a

    odo_regs = RegistroOdometro.query.filter(
        RegistroOdometro.fecha >= fecha_desde,
        RegistroOdometro.fecha <= fecha_hasta,
        RegistroOdometro.viaje_odoo_id.isnot(None),
        or_(
            RegistroOdometro.valor.isnot(None),
            RegistroOdometro.qty_km.isnot(None),
            RegistroOdometro.odoo_driver_name.isnot(None),
            RegistroOdometro.odoo_driver_partner_id.isnot(None),
        ),
    ).all()

    alerts = []
    seen = set()
    for reg in odo_regs:
        matched = _match_driver_user(
            reg.odoo_driver_partner_id,
            reg.odoo_driver_name,
            users_by_odoo,
            users_by_name,
        )
        if not matched:
            continue
        planned = planned_by_user_date.get((matched.id, reg.fecha))
        if not planned:
            continue
        if planned.vehiculo_id == reg.vehiculo_id:
            continue
        key = (matched.id, reg.fecha, planned.vehiculo_id, reg.vehiculo_id)
        if key in seen:
            continue
        seen.add(key)
        alerts.append({
            'fecha': reg.fecha,
            'user': matched,
            'user_id': matched.id,
            'vehiculo_planificado': planned.vehiculo,
            'vehiculo_planificado_id': planned.vehiculo_id,
            'vehiculo_reportado': reg.vehiculo,
            'vehiculo_reportado_id': reg.vehiculo_id,
            'km': reg.valor,
            'conductor_odoo': reg.odoo_driver_name,
            'reg_id': reg.id,
        })

    alerts.sort(key=lambda a: a['fecha'], reverse=True)
    return alerts


def detect_vehicle_on_leave(fecha_desde, fecha_hasta):
    """
    Operario con vehículo planificado y/o reportado en Odoo un día
    en el que tiene ausencia aprobada (vacaciones, baja, permiso…).
    """
    from app.models import LEAVE_STATUS_APROBADA, User
    from app.services.leave_service import build_leaves_by_user, leave_covering

    users_by_odoo, users_by_name = _build_user_indexes()
    candidates = {}

    asignaciones = AsignacionVehiculo.query.filter(
        AsignacionVehiculo.fecha >= fecha_desde,
        AsignacionVehiculo.fecha <= fecha_hasta,
    ).all()
    for a in asignaciones:
        key = (a.user_id, a.fecha, a.vehiculo_id)
        entry = candidates.setdefault(key, {
            'user_id': a.user_id,
            'fecha': a.fecha,
            'vehiculo_id': a.vehiculo_id,
            'fuente_plan': False,
            'fuente_odoo': False,
            'km': None,
            'conductor_odoo': None,
            'reg_id': None,
            'asignacion_id': None,
        })
        entry['fuente_plan'] = True
        entry['asignacion_id'] = a.id

    odo_regs = RegistroOdometro.query.filter(
        RegistroOdometro.fecha >= fecha_desde,
        RegistroOdometro.fecha <= fecha_hasta,
        RegistroOdometro.viaje_odoo_id.isnot(None),
        or_(
            RegistroOdometro.valor.isnot(None),
            RegistroOdometro.qty_km.isnot(None),
            RegistroOdometro.odoo_driver_name.isnot(None),
            RegistroOdometro.odoo_driver_partner_id.isnot(None),
        ),
    ).all()
    for reg in odo_regs:
        matched = _match_driver_user(
            reg.odoo_driver_partner_id,
            reg.odoo_driver_name,
            users_by_odoo,
            users_by_name,
        )
        if not matched:
            continue
        key = (matched.id, reg.fecha, reg.vehiculo_id)
        entry = candidates.setdefault(key, {
            'user_id': matched.id,
            'fecha': reg.fecha,
            'vehiculo_id': reg.vehiculo_id,
            'fuente_plan': False,
            'fuente_odoo': False,
            'km': None,
            'conductor_odoo': None,
            'reg_id': None,
            'asignacion_id': None,
        })
        entry['fuente_odoo'] = True
        entry['km'] = reg.qty_km if reg.qty_km is not None else reg.valor
        entry['conductor_odoo'] = reg.odoo_driver_name
        entry['reg_id'] = reg.id

    if not candidates:
        return []

    user_ids = {c['user_id'] for c in candidates.values()}
    leaves_idx = build_leaves_by_user(list(user_ids), fecha_desde, fecha_hasta)
    users = {
        u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()
    } if user_ids else {}
    veh_ids = {c['vehiculo_id'] for c in candidates.values()}
    vehiculos = {
        v.id: v for v in Vehiculo.query.filter(Vehiculo.id.in_(veh_ids)).all()
    } if veh_ids else {}

    alerts = []
    for entry in candidates.values():
        leave = leave_covering(leaves_idx.get(entry['user_id'], []), entry['fecha'])
        if not leave or leave.estado != LEAVE_STATUS_APROBADA:
            continue
        user = users.get(entry['user_id'])
        if not user:
            continue
        if entry['fuente_plan'] and entry['fuente_odoo']:
            fuente = 'ambos'
        elif entry['fuente_plan']:
            fuente = 'planificado'
        else:
            fuente = 'reportado'
        alerts.append({
            'fecha': entry['fecha'],
            'user': user,
            'user_id': entry['user_id'],
            'vehiculo': vehiculos.get(entry['vehiculo_id']),
            'vehiculo_id': entry['vehiculo_id'],
            'fuente': fuente,
            'km': entry['km'],
            'conductor_odoo': entry['conductor_odoo'],
            'ausencia': leave,
            'ausencia_tipo': (leave.tipo or 'Ausencia').strip() or 'Ausencia',
            'ausencia_inicio': leave.fecha_inicio,
            'ausencia_fin': leave.fecha_fin,
            'reg_id': entry['reg_id'],
            'asignacion_id': entry['asignacion_id'],
        })

    alerts.sort(key=lambda a: (a['fecha'], a['user_id']), reverse=True)
    return alerts


DEFAULT_DESVIO_PCT = 25  # legado (simétrico)
DEFAULT_DESVIO_MAX_PCT = 40  # alerta si desvío ≥ +este %
DEFAULT_DESVIO_MIN_PCT = 30  # alerta si desvío ≤ -este %


def get_desvio_thresholds():
    """
    Umbrales asimétricos de desvío vs km previsto.
    - max_pct: dispara si desvio >= +max_pct
    - min_pct: dispara si desvio <= -min_pct
    Si solo existe la clave legada vehiculo_desvio_pct, se usa en ambos lados.
    """
    legado = ConfiguracionGlobal.query.filter_by(clave='vehiculo_desvio_pct').first()
    legado_val = None
    if legado and legado.valor not in (None, ''):
        try:
            legado_val = max(1, int(float(str(legado.valor).strip().replace(',', '.'))))
        except (TypeError, ValueError):
            legado_val = None

    default_max = legado_val if legado_val is not None else DEFAULT_DESVIO_MAX_PCT
    default_min = legado_val if legado_val is not None else DEFAULT_DESVIO_MIN_PCT

    return {
        'max_pct': max(1, _cfg_int('vehiculo_desvio_max_pct', default_max)),
        'min_pct': max(1, _cfg_int('vehiculo_desvio_min_pct', default_min)),
    }


def get_desvio_threshold():
    """Compat: umbral simétrico (el mayor de max/min)."""
    t = get_desvio_thresholds()
    return max(t['max_pct'], t['min_pct'])


def detect_viaje_desvios(fecha_desde, fecha_hasta, thresholds=None):
    """
    Viajes con desvío fuera de banda: desvio >= +max_pct o desvio <= -min_pct.
    Requiere km_previsto > 0.
    """
    thresholds = thresholds or get_desvio_thresholds()
    max_pct = thresholds['max_pct']
    min_pct = thresholds['min_pct']

    regs = (
        RegistroOdometro.query
        .filter(
            RegistroOdometro.fecha >= fecha_desde,
            RegistroOdometro.fecha <= fecha_hasta,
            RegistroOdometro.desvio.isnot(None),
            RegistroOdometro.km_previsto.isnot(None),
            RegistroOdometro.km_previsto > 0,
        )
        .all()
    )

    alerts = []
    for reg in regs:
        try:
            desvio = float(reg.desvio)
        except (TypeError, ValueError):
            continue

        por_encima = desvio >= max_pct
        por_debajo = desvio <= -min_pct
        if not por_encima and not por_debajo:
            continue

        if por_encima and por_debajo:
            lado = 'ambos'
        elif por_encima:
            lado = 'por_encima'
        else:
            lado = 'por_debajo'

        alerts.append({
            'fecha': reg.fecha,
            'vehiculo': reg.vehiculo,
            'vehiculo_id': reg.vehiculo_id,
            'planned_user': reg.planned_user,
            'conductor_odoo': reg.odoo_driver_name,
            'qty_km': reg.qty_km,
            'km_previsto': reg.km_previsto,
            'desvio': desvio,
            'lado': lado,
            'viaje_code': reg.viaje_code,
            'viaje_odoo_id': reg.viaje_odoo_id,
            'reg_id': reg.id,
            'severidad': 'alta' if abs(desvio) >= max(max_pct, min_pct) * 2 else 'media',
        })

    alerts.sort(key=lambda a: (abs(a['desvio']), a['fecha']), reverse=True)
    return alerts
