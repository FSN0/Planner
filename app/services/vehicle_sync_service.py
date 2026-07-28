"""Sync de flota Odoo (Vehiculo) + odómetros diarios / auditoría informativa."""
from __future__ import annotations

import logging
import time
import unicodedata
from datetime import datetime, timedelta

from app import db
from app.models import (
    AsignacionVehiculo, RegistroOdometro, SyncLog, User, Vehiculo,
)
from app.sync.dispatcher import get_sync_adapter
from app.utils.timezone_utils import today_local, utc_now

logger = logging.getLogger(__name__)


def _set_odoo_external_id(entity, odoo_id):
    ext_ids = dict(entity.external_ids or {})
    ext_ids['odoo'] = str(odoo_id)
    entity.external_ids = ext_ids
    db.session.add(entity)


def _norm_name(text):
    if not text:
        return ''
    text = unicodedata.normalize('NFKD', str(text))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return ' '.join(text.lower().split())


def preview_diff():
    adapter = get_sync_adapter()
    diff = adapter.get_diff_vehiculos()
    listos = []
    for v in diff.get('nuevos', []):
        listos.append({**v, 'accion': 'nuevo'})
    for v in diff.get('actualizados', []):
        listos.append({**v, 'accion': 'actualizar'})
    sin_cambios = [{**v, 'accion': 'sin_cambios'} for v in diff.get('sin_cambios', [])]
    return {
        'diff': diff,
        'listos': listos,
        'sin_cambios': sin_cambios,
        'error': diff.get('error'),
        'stats': {
            'nuevos': len(diff.get('nuevos', [])),
            'actualizados': len(diff.get('actualizados', [])),
            'sin_cambios': len(sin_cambios),
            'listos': len(listos),
        },
        'modulo': 'vehiculos',
        'modulo_label': 'Vehículos / Flota',
        'icon': 'fa-car',
    }


def apply_diff(diff=None, modo='Automático'):
    """Crea/actualiza Vehiculo desde el diff de Odoo."""
    t0 = time.time()
    ahora = utc_now()
    if diff is None:
        adapter = get_sync_adapter()
        diff = adapter.get_diff_vehiculos()

    if diff.get('error'):
        db.session.add(SyncLog(
            fecha=ahora, tipo='Vehículos', modo=modo,
            nuevos=0, actualizados=0, finalizados=0, errores=1,
            detalles=diff['error'], estado='error',
            mensaje_error=diff['error'],
            duracion_ms=int((time.time() - t0) * 1000),
        ))
        db.session.commit()
        return {'nuevos': 0, 'actualizados': 0, 'error': diff['error']}

    nuevos = diff.get('nuevos', [])
    actualizados = diff.get('actualizados', [])
    mat_en_tx = set()

    for obj in nuevos:
        mat = obj.get('matricula')
        if mat and (Vehiculo.query.filter_by(matricula=mat).first() or mat in mat_en_tx):
            mat = f"{mat}-Odoo{obj['odoo_id']}"
        if mat:
            mat_en_tx.add(mat)
        db.session.add(Vehiculo(
            external_ids={'odoo': str(obj['odoo_id'])},
            nombre=obj['nombre'],
            matricula=mat,
            marca=obj.get('marca'),
            modelo=obj.get('modelo'),
            active=bool(obj.get('active', True)),
            odoo_driver_partner_id=obj.get('driver_partner_id'),
            odoo_driver_name=obj.get('driver_name'),
        ))

    for obj in actualizados:
        veh = Vehiculo.query.get(obj['local_id'])
        if not veh:
            continue
        _set_odoo_external_id(veh, obj['odoo_id'])
        veh.nombre = obj['nombre']
        nueva_matricula = obj.get('matricula')
        if nueva_matricula:
            choque = Vehiculo.query.filter(
                Vehiculo.matricula == nueva_matricula, Vehiculo.id != veh.id
            ).first()
            if not choque:
                veh.matricula = nueva_matricula
        else:
            veh.matricula = None
        veh.marca = obj.get('marca')
        veh.modelo = obj.get('modelo')
        veh.active = bool(obj.get('active', True))
        veh.odoo_driver_partner_id = obj.get('driver_partner_id')
        veh.odoo_driver_name = obj.get('driver_name')

    db.session.add(SyncLog(
        fecha=ahora, tipo='Vehículos', modo=modo,
        nuevos=len(nuevos), actualizados=len(actualizados),
        finalizados=0, errores=0,
        detalles='Sincronización de flota (fleet.vehicle) completada.',
        estado='ok',
        duracion_ms=int((time.time() - t0) * 1000),
    ))
    db.session.commit()
    return {'nuevos': len(nuevos), 'actualizados': len(actualizados), 'error': None}


def _match_driver_user(partner_id, driver_name, users_by_odoo, users_by_name):
    """Best-effort: external_ids.odoo (partner o employee) o nombre normalizado."""
    if partner_id is not None:
        u = users_by_odoo.get(str(partner_id))
        if u:
            return u
    if driver_name:
        return users_by_name.get(_norm_name(driver_name))
    return None


def _build_user_indexes():
    users = User.query.filter(User.active.is_(True)).all()
    by_odoo = {}
    by_name = {}
    for u in users:
        ext = u.external_ids or {}
        for key in ('odoo', 'odoo_partner', 'partner'):
            val = ext.get(key)
            if val is not None:
                by_odoo[str(val)] = u
        full = _norm_name(f"{u.name or ''} {u.lastname or ''}")
        if full:
            by_name[full] = u
    return by_odoo, by_name


def _compute_estado(planned_user_id, has_odometer, matched_driver_user_id, has_driver_info):
    planned = planned_user_id is not None
    if planned and not has_odometer:
        return 'sin_km'
    if has_odometer and not planned:
        return 'sin_planificar'
    if planned and has_odometer:
        if has_driver_info and matched_driver_user_id is not None:
            if matched_driver_user_id != planned_user_id:
                return 'mismatch_driver'
            return 'ok'
        # Sin info de conductor pero hay km + plan → ok (no podemos contrastar)
        return 'ok'
    return 'ok'


def sync_odometros(fecha_desde=None, fecha_hasta=None, modo='Automático'):
    """
    Importa odómetros del rango, actualiza snapshot en Vehiculo y upserta RegistroOdometro.
    """
    t0 = time.time()
    hoy = today_local()
    if isinstance(fecha_desde, str):
        fecha_desde = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
    if isinstance(fecha_hasta, str):
        fecha_hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
    if not fecha_desde:
        fecha_desde = hoy
    if not fecha_hasta:
        fecha_hasta = fecha_desde
    if fecha_hasta < fecha_desde:
        fecha_desde, fecha_hasta = fecha_hasta, fecha_desde

    adapter = get_sync_adapter()
    rows = adapter.get_odometros_diarios(
        fecha=fecha_desde.isoformat(),
        fecha_hasta=fecha_hasta.isoformat(),
    )

    # Map odoo vehicle id → local Vehiculo
    vehiculos = Vehiculo.query.filter(Vehiculo.external_ids.has_key('odoo')).all()
    by_odoo_id = {}
    for v in vehiculos:
        oid = (v.external_ids or {}).get('odoo')
        if oid is not None:
            by_odoo_id[str(oid)] = v

    # Latest odometer per vehicle for snapshot
    latest_by_vehicle = {}
    # Group readings: (vehiculo_local_id, date) → best reading (max value / last)
    day_readings = {}
    skipped_unmapped = 0
    for row in rows:
        veh = by_odoo_id.get(str(row['odoo_vehicle_id']))
        if not veh:
            skipped_unmapped += 1
            continue
        d = row['date']
        key = (veh.id, d)
        prev = day_readings.get(key)
        if prev is None or (row.get('value') or 0) >= (prev.get('value') or 0):
            day_readings[key] = row

        prev_latest = latest_by_vehicle.get(veh.id)
        if prev_latest is None or d >= prev_latest['date']:
            if prev_latest is None or d > prev_latest['date'] or (
                d == prev_latest['date'] and (row.get('value') or 0) >= (prev_latest.get('value') or 0)
            ):
                latest_by_vehicle[veh.id] = {**row, '_veh': veh}

    for veh_id, info in latest_by_vehicle.items():
        veh = info['_veh']
        try:
            veh.odoo_odometer_date = datetime.strptime(info['date'], '%Y-%m-%d').date()
        except ValueError:
            pass
        veh.odoo_odometer_value = info.get('value')
        if info.get('driver_partner_id') is not None:
            veh.odoo_driver_partner_id = info['driver_partner_id']
        if info.get('driver_name'):
            veh.odoo_driver_name = info['driver_name']

    users_by_odoo, users_by_name = _build_user_indexes()

    # Assignments in range
    asignaciones = AsignacionVehiculo.query.filter(
        AsignacionVehiculo.fecha >= fecha_desde,
        AsignacionVehiculo.fecha <= fecha_hasta,
    ).all()
    asig_map = {(a.vehiculo_id, a.fecha.isoformat()): a for a in asignaciones}

    # Union of (vehiculo_id, fecha) from readings + assignments
    keys = set(day_readings.keys())
    for a in asignaciones:
        keys.add((a.vehiculo_id, a.fecha.isoformat()))

    upserts = 0
    estados_count = {'ok': 0, 'mismatch_driver': 0, 'sin_km': 0, 'sin_planificar': 0}

    for veh_id, date_str in keys:
        try:
            fecha = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            continue

        reading = day_readings.get((veh_id, date_str))
        asig = asig_map.get((veh_id, date_str))
        planned_user_id = asig.user_id if asig else None

        valor = reading.get('value') if reading else None
        driver_partner_id = reading.get('driver_partner_id') if reading else None
        driver_name = reading.get('driver_name') if reading else None
        has_odometer = reading is not None and valor is not None
        has_driver_info = bool(driver_partner_id or driver_name)

        matched = _match_driver_user(
            driver_partner_id, driver_name, users_by_odoo, users_by_name
        )
        matched_id = matched.id if matched else None

        estado = _compute_estado(
            planned_user_id, has_odometer, matched_id, has_driver_info
        )
        estados_count[estado] = estados_count.get(estado, 0) + 1

        reg = RegistroOdometro.query.filter_by(vehiculo_id=veh_id, fecha=fecha).first()
        if not reg:
            reg = RegistroOdometro(vehiculo_id=veh_id, fecha=fecha)
            db.session.add(reg)
        reg.valor = valor
        reg.odoo_driver_partner_id = driver_partner_id
        reg.odoo_driver_name = driver_name
        reg.planned_user_id = planned_user_id
        reg.estado = estado
        upserts += 1

    detalle = (
        f"Odómetros {fecha_desde}→{fecha_hasta}: {upserts} registros. "
        f"ok={estados_count.get('ok', 0)} mismatch={estados_count.get('mismatch_driver', 0)} "
        f"sin_km={estados_count.get('sin_km', 0)} sin_plan={estados_count.get('sin_planificar', 0)} "
        f"omitidos_sin_vinculo={skipped_unmapped}"
    )
    db.session.add(SyncLog(
        fecha=utc_now(), tipo='Vehículos (Odómetros)', modo=modo,
        nuevos=0, actualizados=upserts, finalizados=0, errores=0,
        detalles=detalle, estado='ok',
        duracion_ms=int((time.time() - t0) * 1000),
    ))
    db.session.commit()
    return {
        'upserts': upserts,
        'estados': estados_count,
        'readings': len(rows),
        'omitidos_sin_vinculo': skipped_unmapped,
        'desde': fecha_desde.isoformat(),
        'hasta': fecha_hasta.isoformat(),
    }


def run_vehiculos_en_vivo(modo='Automático'):
    """Master data de flota + odómetros de hoy."""
    result_fleet = apply_diff(modo=modo)
    result_odo = sync_odometros(
        fecha_desde=today_local(),
        fecha_hasta=today_local(),
        modo=modo,
    )
    return {'fleet': result_fleet, 'odometros': result_odo}


def run_vehiculos_retro(days=None, modo='Automático'):
    from app.services.sync_config_service import SyncConfigService

    cfg = SyncConfigService.get_config()
    dias = int(days if days is not None else cfg.get('vehiculos_retro_days', 30))
    dias = max(1, min(365, dias))
    apply_diff(modo=modo)
    hasta = today_local()
    desde = hasta - timedelta(days=dias)
    return sync_odometros(fecha_desde=desde, fecha_hasta=hasta, modo=modo)
