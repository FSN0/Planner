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


# ---------------------------------------------------------------------------
# Acuses informativos ("Visto") — no alteran la detección
# ---------------------------------------------------------------------------

ANOMALIA_KINDS = frozenset({
    'salto', 'cross', 'leave', 'desvio', 'mismatch', 'sin_km', 'sin_plan',
})


def _fecha_iso(val):
    if val is None:
        return ''
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


def build_anomaly_clave(kind, item):
    """
    Clave estable para acuse (clave compuesta estable).
    Formato: {kind}:reg:{id} | leave:asig:{id} | leave:{user}:{fecha}:{veh} | …
    """
    kind = (kind or '').strip().lower()
    if isinstance(item, dict):
        if kind == 'leave':
            asig = item.get('asignacion_id')
            if asig:
                return f'leave:asig:{asig}'
            return (
                f"leave:{item.get('user_id')}:{_fecha_iso(item.get('fecha'))}"
                f":{item.get('vehiculo_id')}"
            )
        if kind == 'salto':
            return (
                f"salto:{item.get('vehiculo_id')}:{_fecha_iso(item.get('fecha_anterior'))}"
                f":{_fecha_iso(item.get('fecha_actual'))}"
            )
        if kind == 'cross':
            return (
                f"cross:{item.get('user_id')}:{_fecha_iso(item.get('fecha'))}"
                f":{item.get('vehiculo_planificado_id')}:{item.get('vehiculo_reportado_id')}"
            )
        if kind == 'desvio':
            viaje = item.get('viaje_odoo_id')
            if viaje:
                return f'desvio:viaje:{viaje}'
            return (
                f"desvio:{item.get('vehiculo_id')}:{_fecha_iso(item.get('fecha'))}"
                f":{item.get('viaje_code') or ''}"
            )
        # Fallback: si no hay un esquema estable específico para el kind,
        # usamos reg_id (legacy). Esto evita romper casos raros.
        reg_id = item.get('reg_id')
        if reg_id:
            return f'{kind}:reg:{reg_id}'
        return (
            f'{kind}:fallback:'
            f'{item.get("vehiculo_id") or item.get("user_id") or "x"}:'
            f'{_fecha_iso(item.get("fecha") or item.get("fecha_actual"))}'
        )

    # RegistroOdometro u objeto con .id
    oid = getattr(item, 'id', None)
    if oid is not None:
        if kind in {'mismatch', 'sin_km', 'sin_plan'}:
            vehiculo_id = getattr(item, 'vehiculo_id', None)
            fecha = getattr(item, 'fecha', None)
            if vehiculo_id is not None and fecha is not None:
                return f'{kind}:veh:{vehiculo_id}:{_fecha_iso(fecha)}'
        return f'{kind}:reg:{oid}'
    raise ValueError(f'No se puede construir clave para kind={kind!r}')


def annotate_anomaly_clave(kind, item):
    """Añade anomalia_kind / anomalia_clave al dict o al objeto ORM."""
    clave = build_anomaly_clave(kind, item)
    if isinstance(item, dict):
        out = dict(item)
        out['anomalia_kind'] = kind
        out['anomalia_clave'] = clave
        return out
    try:
        item.anomalia_kind = kind
        item.anomalia_clave = clave
    except Exception:
        pass
    return item


def get_vistos_claves(kinds=None):
    """Set de (kind, clave) vistas; si kinds, filtra por esos kinds."""
    from app.models import AnomaliaVehiculoVista

    q = AnomaliaVehiculoVista.query
    if kinds:
        q = q.filter(AnomaliaVehiculoVista.kind.in_(list(kinds)))
    return set(
        q.with_entities(
            AnomaliaVehiculoVista.kind, AnomaliaVehiculoVista.clave
        ).all()
    )


def get_vistas_map(kinds=None):
    """
    Mapa {(kind, clave)->AnomaliaVehiculoVista} para separar pendientes vs vistos,
    y para enriquecer el histórico con "quién lo ha visto".

    Compatibilidad legacy:
    - Si existen claves guardadas tipo `{kind}:reg:{id}`, intentamos reconstruir
      la clave estable compuesta equivalente en base al estado actual.
    """
    from app import db
    from app.models import AnomaliaVehiculoVista

    q = AnomaliaVehiculoVista.query
    if kinds:
        q = q.filter(AnomaliaVehiculoVista.kind.in_(list(kinds)))

    vistos_rows = q.options(db.joinedload(AnomaliaVehiculoVista.visto_por)).all()
    vistas_map = {(r.kind, r.clave): r for r in vistos_rows}
    if not vistos_rows:
        return vistas_map

    need_user_indexes = any(r.kind in {'cross', 'leave'} for r in vistos_rows)
    users_by_odoo = users_by_name = None
    if need_user_indexes:
        users_by_odoo, users_by_name = _build_user_indexes()

    for row in vistos_rows:
        parts = (row.clave or '').split(':reg:')
        if len(parts) != 2 or parts[0] != row.kind:
            continue
        try:
            reg_id = int(parts[1])
        except (TypeError, ValueError):
            continue

        reg = RegistroOdometro.query.get(reg_id)
        if not reg:
            continue

        fecha_iso = _fecha_iso(reg.fecha)
        stable = None

        if row.kind in {'mismatch', 'sin_km', 'sin_plan'}:
            if reg.vehiculo_id is not None and fecha_iso:
                stable = f'{row.kind}:veh:{reg.vehiculo_id}:{fecha_iso}'
        elif row.kind == 'desvio':
            if reg.viaje_odoo_id:
                stable = f'desvio:viaje:{reg.viaje_odoo_id}'
            elif reg.vehiculo_id is not None and fecha_iso:
                stable = (
                    f'desvio:{reg.vehiculo_id}:{fecha_iso}:{reg.viaje_code or ""}'
                )
        elif row.kind == 'salto':
            if reg.vehiculo_id is not None and reg.fecha:
                prev = RegistroOdometro.query.filter(
                    RegistroOdometro.vehiculo_id == reg.vehiculo_id,
                    RegistroOdometro.fecha < reg.fecha,
                    RegistroOdometro.valor.isnot(None),
                    RegistroOdometro.viaje_odoo_id.isnot(None),
                ).order_by(RegistroOdometro.fecha.desc(), RegistroOdometro.id.desc()).first()
                if prev and prev.fecha:
                    stable = (
                        f'salto:{reg.vehiculo_id}:{_fecha_iso(prev.fecha)}:{_fecha_iso(reg.fecha)}'
                    )
        elif row.kind == 'cross':
            matched = _match_driver_user(
                reg.odoo_driver_partner_id,
                reg.odoo_driver_name,
                users_by_odoo,
                users_by_name,
            )
            if matched:
                planned = AsignacionVehiculo.query.filter_by(
                    user_id=matched.id,
                    fecha=reg.fecha,
                ).first()
                if planned and planned.vehiculo_id is not None and reg.vehiculo_id is not None:
                    stable = (
                        f'cross:{matched.id}:{fecha_iso}:{planned.vehiculo_id}:{reg.vehiculo_id}'
                    )
        elif row.kind == 'leave':
            matched = _match_driver_user(
                reg.odoo_driver_partner_id,
                reg.odoo_driver_name,
                users_by_odoo,
                users_by_name,
            )
            if matched:
                asig = AsignacionVehiculo.query.filter_by(
                    user_id=matched.id,
                    fecha=reg.fecha,
                    vehiculo_id=reg.vehiculo_id,
                ).first()
                if asig:
                    stable = f'leave:asig:{asig.id}'
                elif reg.vehiculo_id is not None and fecha_iso:
                    stable = f'leave:{matched.id}:{fecha_iso}:{reg.vehiculo_id}'

        if stable:
            vistas_map[(row.kind, stable)] = row

    return vistas_map


def partition_anomalias(kind, items, vistas_map=None):
    """
    Anota claves y parte en (pendientes, vistos).
    vistas_map: dict[(kind, clave)] -> AnomaliaVehiculoVista precargado opcional.
    """
    if vistas_map is None:
        vistas_map = get_vistas_map(kinds=[kind])

    pendientes, vistos = [], []
    for raw in items:
        item = annotate_anomaly_clave(kind, raw)
        clave = item['anomalia_clave'] if isinstance(item, dict) else item.anomalia_clave

        vista_row = vistas_map.get((kind, clave))
        if vista_row:
            viewer = None
            try:
                if vista_row.visto_por:
                    viewer = f"{vista_row.visto_por.name} {vista_row.visto_por.lastname}".strip()
            except Exception:
                viewer = None

            if isinstance(item, dict):
                item['visto_por_name'] = viewer
                item['visto_en'] = vista_row.visto_en
            else:
                try:
                    item.visto_por_name = viewer
                    item.visto_en = vista_row.visto_en
                except Exception:
                    pass

            vistos.append(item)
        else:
            pendientes.append(item)
    return pendientes, vistos


def marcar_anomalia_vista(kind, clave, user_id, payload=None):
    """Upsert acuse informativo. Retorna la fila."""
    from app.models import AnomaliaVehiculoVista
    from app import db
    from app.utils.timezone_utils import utc_now

    kind = (kind or '').strip().lower()
    clave = (clave or '').strip()
    if kind not in ANOMALIA_KINDS:
        raise ValueError(f'kind no válido: {kind}')
    if not clave or len(clave) > 160:
        raise ValueError('clave inválida')

    row = AnomaliaVehiculoVista.query.filter_by(kind=kind, clave=clave).first()
    if row:
        row.visto_por_id = user_id
        row.visto_en = utc_now()
        if payload is not None:
            row.payload = payload
    else:
        row = AnomaliaVehiculoVista(
            kind=kind,
            clave=clave,
            visto_por_id=user_id,
            visto_en=utc_now(),
            payload=payload,
        )
        db.session.add(row)
    db.session.commit()
    return row
