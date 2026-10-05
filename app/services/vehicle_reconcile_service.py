# app/services/vehicle_reconcile_service.py
"""
Reasignación autónoma plan ↔ uso Odoo.

Si el operario tenía planificado A y reporta km en B:
  - A queda como no_usada (rastro)
  - B pasa a efectiva con nota del plan original

Si otra persona reporta km en un vehículo con plan fantasma / efectiva ajena:
  - se elimina el rastro del que no lo usó
  - se asigna efectiva a quien sí imputó km
"""
from __future__ import annotations

import logging
from datetime import datetime

from app import db
from app.models import AsignacionVehiculo, Vehiculo
from app.services.core_vehicle_assignment_service import (
    CoreVehicleAssignmentService as Core,
    EFECTIVA,
    NO_USADA,
)

logger = logging.getLogger(__name__)

CTX = 'Sync Odoo vehículos (auto-reasignación)'


def _label(vehiculo_id):
    v = Vehiculo.query.get(vehiculo_id)
    return Core.format_vehiculo_label(v) if v else f'#{vehiculo_id}'


def reconcile_vehicle_assignments_from_usage(
    covered_days,
    users_by_odoo,
    users_by_name,
    *,
    autor_id=None,
    match_driver_fn=None,
):
    """
    covered_days: {(vehiculo_id, 'YYYY-MM-DD'): cover_dict}
    Devuelve contadores {cross_swaps, claimed_free, ghosts_cleared}.
    """
    from app.services.vehicle_sync_service import _match_driver_user

    match = match_driver_fn or _match_driver_user
    stats = {'cross_swaps': 0, 'claimed_free': 0, 'ghosts_cleared': 0, 'upgraded': 0}

    # Orden estable por fecha
    items = []
    for (veh_id, date_str), cover in (covered_days or {}).items():
        if not cover:
            continue
        try:
            fecha = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            continue
        matched = match(
            cover.get('driver_partner_id'),
            cover.get('driver_name'),
            users_by_odoo,
            users_by_name,
        )
        if not matched:
            continue
        items.append((fecha, int(veh_id), matched))

    items.sort(key=lambda t: (t[0], t[1], t[2].id))

    for fecha, veh_b_id, user in items:
        try:
            _reconcile_one_day(fecha, veh_b_id, user, autor_id, stats)
        except Exception:
            logger.exception(
                'reconcile vehículo falló user=%s veh=%s fecha=%s',
                user.id, veh_b_id, fecha,
            )
            db.session.rollback()
            raise

    return stats


def _reconcile_one_day(fecha, veh_b_id, user, autor_id, stats):
    label_b = _label(veh_b_id)

    # 1) Fantasmas / efectiva ajena en B → fuera si no es este conductor
    for row in AsignacionVehiculo.query.filter_by(vehiculo_id=veh_b_id, fecha=fecha).all():
        if row.user_id == user.id:
            continue
        Core.desasignar(
            row.vehiculo_id, row.user_id, fecha,
            autor_id, CTX,
            detalle_extra=(
                f"Liberado: km reportados por otro conductor en {label_b}."
            ),
            registrar_log=True,
        )
        stats['ghosts_cleared'] += 1

    efectiva = Core.get_efectiva_user(user.id, fecha)

    # 2) Ya efectiva en B
    if efectiva and efectiva.vehiculo_id == veh_b_id:
        if not (efectiva.notas or '').strip():
            # Mantener notas existentes; no machacar.
            pass
        return

    # 3) Efectiva en otro vehículo A → A pasa a no_usada, B efectiva
    if efectiva and efectiva.vehiculo_id != veh_b_id:
        veh_a_id = efectiva.vehiculo_id
        label_a = _label(veh_a_id)
        Core.marcar_no_usada(
            veh_a_id, user.id, fecha, autor_id, CTX,
            notas=(
                f"Planificado aquí ({label_a}); kilómetros reportados en "
                f"{label_b}."
            ),
            registrar_log=True,
        )
        Core.asignar(
            veh_b_id, user.id, fecha, autor_id, CTX,
            detalle_extra=f"Auto: uso Odoo en {label_b} (plan era {label_a}).",
            overwrite=True,
            registrar_log=True,
            notas=(
                f"Kilómetros reportados aquí ({label_b}); "
                f"tenía planificado {label_a}."
            ),
            estado=EFECTIVA,
        )
        stats['cross_swaps'] += 1
        return

    # 4) Sin efectiva: quizá ya tiene no_usada en B → subir; o asignar nuevo
    same = AsignacionVehiculo.query.filter_by(
        vehiculo_id=veh_b_id, user_id=user.id, fecha=fecha,
    ).first()
    if same and same.estado == NO_USADA:
        same.estado = EFECTIVA
        same.notas = same.notas or (
            f"Kilómetros reportados aquí ({label_b}); reactivado desde plan no usado."
        )
        db.session.flush()
        stats['upgraded'] += 1
        return

    Core.asignar(
        veh_b_id, user.id, fecha, autor_id, CTX,
        detalle_extra=f"Auto: km Odoo sin plan previo → {label_b}.",
        overwrite=True,
        registrar_log=True,
        notas=f"Asignado automáticamente por kilómetros reportados en Odoo ({label_b}).",
        estado=EFECTIVA,
    )
    stats['claimed_free'] += 1
