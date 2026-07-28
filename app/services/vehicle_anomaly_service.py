# app/services/vehicle_anomaly_service.py
"""Detección de anomalías de vehículos (saltos de odómetro y plan vs reporte)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_

from app.models import AsignacionVehiculo, ConfiguracionGlobal, RegistroOdometro, Vehiculo
from app.services.vehicle_sync_service import _build_user_indexes, _match_driver_user


DEFAULT_THRESHOLDS = {
    'vehiculo_salto_km_dia': 400,
    'vehiculo_salto_delta_km': 1000,
    'vehiculo_salto_ventana_dias': 7,
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
    """Umbrales configurables (configuración global)."""
    return {
        'km_dia': max(1, _cfg_int(
            'vehiculo_salto_km_dia', DEFAULT_THRESHOLDS['vehiculo_salto_km_dia']
        )),
        'delta_km': max(1, _cfg_int(
            'vehiculo_salto_delta_km', DEFAULT_THRESHOLDS['vehiculo_salto_delta_km']
        )),
        'ventana_dias': max(1, _cfg_int(
            'vehiculo_salto_ventana_dias', DEFAULT_THRESHOLDS['vehiculo_salto_ventana_dias']
        )),
    }


def _classify_jump(delta_km, delta_dias, km_dia, thresholds):
    """Devuelve (severidad, motivos[]) o (None, [])."""
    motivos = []
    severidad = None

    if delta_km < 0:
        motivos.append('odometro_atras')
        severidad = 'alta'

    if delta_dias <= 0:
        delta_dias = 1

    if km_dia >= thresholds['km_dia']:
        motivos.append('km_dia')
        severidad = 'alta'

    if delta_km >= thresholds['delta_km'] and delta_dias <= thresholds['ventana_dias']:
        motivos.append('delta_ventana')
        if severidad != 'alta':
            severidad = 'alta'

    return severidad, motivos


def detect_odometer_jumps(fecha_desde, fecha_hasta, thresholds=None):
    """
    Compara lecturas consecutivas por vehículo.
    Incluye como 'prev' lecturas anteriores al rango para no perder el primer salto.
    Solo emite alertas cuya lectura actual cae dentro de [fecha_desde, fecha_hasta].
    """
    thresholds = thresholds or get_odometer_jump_thresholds()
    lookback = fecha_desde - timedelta(days=max(90, thresholds['ventana_dias'] * 3))

    regs = (
        RegistroOdometro.query
        .filter(
            RegistroOdometro.fecha >= lookback,
            RegistroOdometro.fecha <= fecha_hasta,
            RegistroOdometro.valor.isnot(None),
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
    Operario planificado en vehículo A ese día, pero el odómetro de ese día
    (matched a ese operario) está en vehículo B.
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
        or_(
            RegistroOdometro.valor.isnot(None),
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
