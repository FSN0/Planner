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


def _compute_estado(planned_user_id, has_usage, matched_driver_user_id, has_driver_info):
    planned = planned_user_id is not None
    if planned and not has_usage:
        return 'sin_km'
    if has_usage and not planned:
        return 'sin_planificar'
    if planned and has_usage:
        if has_driver_info and matched_driver_user_id is not None:
            if matched_driver_user_id != planned_user_id:
                return 'mismatch_driver'
            return 'ok'
        # Sin info de conductor pero hay uso + plan → ok (no podemos contrastar)
        return 'ok'
    return 'ok'


def purge_registros_uso(fecha_desde=None, fecha_hasta=None):
    """
    Borra snapshots de uso diario (antes odómetro; ahora viajes).
    Sin fechas → borra TODO (para resync limpio desde tms.shipment).
    """
    q = RegistroOdometro.query
    if fecha_desde is not None:
        if isinstance(fecha_desde, str):
            fecha_desde = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
        q = q.filter(RegistroOdometro.fecha >= fecha_desde)
    if fecha_hasta is not None:
        if isinstance(fecha_hasta, str):
            fecha_hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
        q = q.filter(RegistroOdometro.fecha <= fecha_hasta)
    borrados = q.delete(synchronize_session=False)
    db.session.commit()
    return borrados


def _build_vehicle_indexes():
    """Índices locales para resolver equipo Odoo → Vehiculo."""
    by_odoo_id = {}
    by_nombre = {}
    for v in Vehiculo.query.all():
        ext = v.external_ids or {}
        oid = ext.get('odoo')
        if oid is not None and str(oid).strip() != '':
            by_odoo_id[str(oid)] = v
        if v.nombre:
            by_nombre[_norm_name(v.nombre)] = v
        if v.matricula:
            by_nombre[_norm_name(v.matricula)] = v
    return by_odoo_id, by_nombre


def _ensure_vehiculo_for_viaje(viaje, by_odoo_id, by_nombre):
    """
    Resuelve o crea Vehiculo para el equipo del viaje.
    No descartamos viajes: si no hay vínculo local, lo creamos.
    """
    oid = viaje.get('odoo_vehicle_id')
    if oid is None:
        return None, 'sin_equipo'

    key = str(int(oid))
    veh = by_odoo_id.get(key)
    if veh:
        return veh, 'ok'

    name = (viaje.get('odoo_vehicle_name') or '').strip()
    if name:
        veh = by_nombre.get(_norm_name(name))
        if veh:
            ext = dict(veh.external_ids or {})
            ext['odoo'] = key
            veh.external_ids = ext
            db.session.add(veh)
            by_odoo_id[key] = veh
            return veh, 'vinculado_nombre'

    veh = Vehiculo(
        external_ids={'odoo': key},
        nombre=name or f'Vehículo Odoo {key}',
        active=True,
    )
    db.session.add(veh)
    db.session.flush()
    by_odoo_id[key] = veh
    if name:
        by_nombre[_norm_name(name)] = veh
    return veh, 'auto_creado'


def sync_odometros(fecha_desde=None, fecha_hasta=None, modo='Automático', limpiar_rango=True):
    """
    Fuente ÚNICA de uso/conductor: viajes Odoo tms.shipment.
    Nunca usa fleet.vehicle.odometer (el conductor del odómetro se reescribe
    al último que reportó km y contamina el histórico).

    Si limpiar_rango=True, borra los registros del rango (y catch-up) y
    los reconstruye solo desde viajes + planificación local.
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
    viajes = []
    try:
        viajes = adapter.get_viajes_diarios(
            fecha=fecha_desde.isoformat(),
            fecha_hasta=fecha_hasta.isoformat(),
        ) or []
    except Exception as e:
        logger.exception('Error leyendo viajes tms.shipment: %s', e)
        viajes = []

    by_odoo_id, by_nombre = _build_vehicle_indexes()

    # 1) Resolver/crear vehículos ANTES de generar días (no tirar viajes)
    skipped_sin_equipo = 0
    auto_creados = 0
    vinculados_nombre = 0
    for viaje in viajes:
        veh, status = _ensure_vehiculo_for_viaje(viaje, by_odoo_id, by_nombre)
        if status == 'sin_equipo':
            skipped_sin_equipo += 1
        elif status == 'auto_creado':
            auto_creados += 1
        elif status == 'vinculado_nombre':
            vinculados_nombre += 1

    latest_by_vehicle = {}
    day_readings = {}
    covered_days = {}
    desvio_alerts = 0
    viajes_aplicados = 0
    parse_fail = 0
    dates_seen = set()

    for viaje in viajes:
        veh, _status = _ensure_vehiculo_for_viaje(viaje, by_odoo_id, by_nombre)
        if not veh:
            continue
        try:
            d0 = datetime.strptime(str(viaje['date_start'])[:10], '%Y-%m-%d').date()
            d1 = datetime.strptime(str(viaje['date_end'])[:10], '%Y-%m-%d').date()
        except (KeyError, TypeError, ValueError):
            parse_fail += 1
            continue
        if d1 < d0:
            d0, d1 = d1, d0

        # Seguridad: no expandir un viaje a más de 60 días (dato raro)
        if (d1 - d0).days > 60:
            d1 = d0

        km_start = viaje.get('km_start')
        km_end = viaje.get('km_end')
        desvio = viaje.get('desvio')
        km_previsto = viaje.get('km_previsto')
        if desvio is not None and km_previsto is not None and float(km_previsto) > 0:
            try:
                from app.services.vehicle_anomaly_service import get_desvio_thresholds
                _dt = get_desvio_thresholds()
                dval = float(desvio)
                if dval >= _dt['max_pct'] or dval <= -_dt['min_pct']:
                    desvio_alerts += 1
            except Exception:
                if abs(float(desvio)) >= 25:
                    desvio_alerts += 1

        # IMPORTANTE: escribir SIEMPRE los días del viaje que devolvió Odoo.
        # El adapter ya filtró por rango; NO volver a filtrar aquí (era el bug
        # que dejaba 57 registros con 7904 viajes).
        wrote_any = False
        cur = d0
        while cur <= d1:
            wrote_any = True
            dates_seen.add(cur.isoformat())
            key = (veh.id, cur.isoformat())
            meta = {
                'driver_partner_id': viaje.get('driver_partner_id'),
                'driver_name': viaje.get('driver_name'),
                'value': km_end if cur == d1 else None,
                'km_start': km_start,
                'km_end': km_end,
                'qty_km': viaje.get('qty_km'),
                'km_previsto': viaje.get('km_previsto'),
                'desvio': desvio,
                'from_viaje': True,
                'viaje_id': viaje.get('odoo_viaje_id'),
                'viaje_code': viaje.get('code'),
                'viaje_start': d0.isoformat(),
                'viaje_end': d1.isoformat(),
                'obra_origen': viaje.get('obra_origen'),
                'obra_destino': viaje.get('obra_destino'),
            }
            prev_c = covered_days.get(key)
            # Si hay varios viajes el mismo día/vehículo, quedarnos con el de mayor id
            prev_vid = (prev_c or {}).get('viaje_id') or 0
            cur_vid = viaje.get('odoo_viaje_id') or 0
            if prev_c is None or cur_vid >= prev_vid:
                covered_days[key] = meta

            if cur == d1 and km_end is not None:
                prev = day_readings.get(key)
                if prev is None or km_end >= (prev.get('value') or 0):
                    day_readings[key] = {
                        'date': cur.isoformat(),
                        'value': km_end,
                        'driver_partner_id': viaje.get('driver_partner_id'),
                        'driver_name': viaje.get('driver_name'),
                        'from_viaje': True,
                        'desvio': desvio,
                        'km_previsto': viaje.get('km_previsto'),
                        'qty_km': viaje.get('qty_km'),
                    }
            cur += timedelta(days=1)

        if wrote_any:
            viajes_aplicados += 1

        d_reg = str(viaje.get('date_registro') or viaje.get('date_end') or '')[:10]
        if d_reg and km_end is not None:
            prev_latest = latest_by_vehicle.get(veh.id)
            if prev_latest is None or d_reg >= prev_latest['date']:
                latest_by_vehicle[veh.id] = {
                    'date': d_reg,
                    'value': km_end,
                    'driver_partner_id': viaje.get('driver_partner_id'),
                    'driver_name': viaje.get('driver_name'),
                    '_veh': veh,
                }

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

    # Rango real a persistir = unión del filtro pedido + días de los viajes
    look_asign_desde = fecha_desde
    look_asign_hasta = fecha_hasta
    for _vid, date_str in covered_days.keys():
        try:
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            continue
        if d < look_asign_desde:
            look_asign_desde = d
        if d > look_asign_hasta:
            look_asign_hasta = d

    borrados = 0
    if limpiar_rango:
        borrados = (
            RegistroOdometro.query
            .filter(
                RegistroOdometro.fecha >= look_asign_desde,
                RegistroOdometro.fecha <= look_asign_hasta,
            )
            .delete(synchronize_session=False)
        )

    asignaciones = AsignacionVehiculo.query.filter(
        AsignacionVehiculo.fecha >= look_asign_desde,
        AsignacionVehiculo.fecha <= look_asign_hasta,
    ).all()
    asig_map = {(a.vehiculo_id, a.fecha.isoformat()): a for a in asignaciones}

    keys = set(covered_days.keys()) | set(day_readings.keys())
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
        cover = covered_days.get((veh_id, date_str))
        asig = asig_map.get((veh_id, date_str))
        planned_user_id = asig.user_id if asig else None

        valor = reading.get('value') if reading else None
        if valor is None and cover and cover.get('value') is not None:
            valor = cover.get('value')

        driver_partner_id = None
        driver_name = None
        if cover:
            driver_partner_id = cover.get('driver_partner_id')
            driver_name = cover.get('driver_name')
        elif reading:
            driver_partner_id = reading.get('driver_partner_id')
            driver_name = reading.get('driver_name')

        has_usage = cover is not None
        has_driver_info = bool(driver_partner_id or driver_name)

        matched = _match_driver_user(
            driver_partner_id, driver_name, users_by_odoo, users_by_name
        )
        matched_id = matched.id if matched else None

        estado = _compute_estado(
            planned_user_id, has_usage, matched_id, has_driver_info
        )
        estados_count[estado] = estados_count.get(estado, 0) + 1

        reg = RegistroOdometro(vehiculo_id=veh_id, fecha=fecha)
        db.session.add(reg)
        reg.valor = valor
        reg.odoo_driver_partner_id = driver_partner_id
        reg.odoo_driver_name = driver_name
        reg.planned_user_id = planned_user_id
        reg.estado = estado
        if cover:
            reg.km_start = cover.get('km_start')
            reg.qty_km = cover.get('qty_km')
            reg.km_previsto = cover.get('km_previsto')
            reg.desvio = cover.get('desvio')
            reg.viaje_code = cover.get('viaje_code')
            reg.viaje_odoo_id = cover.get('viaje_id')
        upserts += 1

    sorted_dates = sorted(dates_seen)
    detalle = (
        f"Viajes tms.shipment sync={fecha_desde}→{fecha_hasta}: "
        f"viajes_odoo={len(viajes)} aplicados={viajes_aplicados} parse_fail={parse_fail} "
        f"dias_unicos={len(dates_seen)} "
        f"min_dia={sorted_dates[0] if sorted_dates else None} "
        f"max_dia={sorted_dates[-1] if sorted_dates else None} "
        f"registros={upserts} borrados={borrados} "
        f"veh_auto={auto_creados} veh_vinc_nombre={vinculados_nombre} "
        f"sin_equipo={skipped_sin_equipo} "
        f"ok={estados_count.get('ok', 0)} mismatch={estados_count.get('mismatch_driver', 0)} "
        f"sin_km={estados_count.get('sin_km', 0)} sin_plan={estados_count.get('sin_planificar', 0)} "
        f"desvio_alto={desvio_alerts}"
    )
    logger.info('[sync_odometros] %s', detalle)
    db.session.add(SyncLog(
        fecha=utc_now(), tipo='Vehículos (Viajes)', modo=modo,
        nuevos=auto_creados, actualizados=upserts, finalizados=borrados, errores=0,
        detalles=detalle, estado='ok',
        duracion_ms=int((time.time() - t0) * 1000),
    ))
    db.session.commit()
    return {
        'upserts': upserts,
        'borrados': borrados,
        'estados': estados_count,
        'viajes': len(viajes),
        'viajes_aplicados': viajes_aplicados,
        'parse_fail': parse_fail,
        'dias_unicos': len(dates_seen),
        'min_dia': sorted_dates[0] if sorted_dates else None,
        'max_dia': sorted_dates[-1] if sorted_dates else None,
        'vehiculos_auto_creados': auto_creados,
        'vehiculos_vinculados_nombre': vinculados_nombre,
        'sin_equipo': skipped_sin_equipo,
        'dias_cubiertos': len(covered_days),
        'desvio_alto': desvio_alerts,
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
