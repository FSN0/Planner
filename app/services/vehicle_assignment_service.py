# app/services/vehicle_assignment_service.py

from datetime import datetime, date

from app import db
from app.models import (
    AsignacionVehiculo, Vehiculo, User, ROLE_ADMIN, ROLE_JEFE,
)
from app.services.core_vehicle_assignment_service import CoreVehicleAssignmentService
from app.services.vehicle_solicitud_service import VehicleSolicitudService


def _parse_dates(date_list):
    valid = []
    for d in date_list:
        if isinstance(d, str):
            try:
                valid.append(datetime.strptime(d, "%Y-%m-%d").date())
            except ValueError:
                continue
        elif isinstance(d, date):
            valid.append(d)
    return sorted(set(valid))


def process_vehicle_assignment_action(
    actor_user, worker_id, vehicle_id, date_list,
    *, notas=None, overwrite_mode='check', accion='ASIGNAR',
):
    """
    ADMIN: asigna/desasigna directamente vía CoreVehicleAssignmentService.
    JEFE: crea SolicitudVehiculo (siempre petición).

    overwrite_mode: 'check' | 'overwrite' | 'only_free'
      - mismo usuario+vehículo ese día → skip
      - conflicto con otro → check falla / overwrite fuerza / only_free omite
    """
    worker = User.query.get(worker_id)
    vehicle = Vehiculo.query.get(vehicle_id)

    if not worker or not vehicle:
        return {'success': False, 'error': 'Trabajador o vehículo no encontrados'}
    if not vehicle.active:
        return {'success': False, 'error': 'El vehículo no está activo'}

    valid_dates = _parse_dates(date_list)
    if not valid_dates:
        return {'success': False, 'error': 'No hay fechas válidas'}

    accion = (accion or 'ASIGNAR').upper()
    mode = overwrite_mode or 'check'

    # ==========================================
    # ADMIN
    # ==========================================
    if actor_user.role == ROLE_ADMIN:
        if accion == 'DESASIGNAR':
            count = 0
            done_dates = []
            for d in valid_dates:
                if CoreVehicleAssignmentService.desasignar(
                    vehicle.id, worker.id, d, actor_user.id, "Planificación Manual",
                    registrar_log=False,
                ):
                    count += 1
                    done_dates.append(d)
            if count and done_dates:
                CoreVehicleAssignmentService.registrar_log_rango(
                    worker.id, vehicle.id,
                    min(done_dates), max(done_dates), count,
                    actor_user.id, "Planificación Manual", False,
                )
            db.session.commit()
            return {
                'success': True,
                'action': 'unassigned',
                'message': f'Desasignación de vehículo ({count} días).',
            }

        conflict_details = {}
        free_dates = []
        skip_same = 0

        for d in valid_dates:
            same = AsignacionVehiculo.query.filter_by(
                vehiculo_id=vehicle.id, user_id=worker.id, fecha=d,
            ).first()
            if same:
                skip_same += 1
                continue

            conf_v = AsignacionVehiculo.query.filter_by(vehiculo_id=vehicle.id, fecha=d).first()
            conf_u = AsignacionVehiculo.query.filter_by(user_id=worker.id, fecha=d).first()

            if conf_v or conf_u:
                key_parts = []
                if conf_v:
                    other = User.query.get(conf_v.user_id)
                    oname = f"{other.name} {other.lastname}" if other else f"ID {conf_v.user_id}"
                    key_parts.append(f"Vehículo → {oname}")
                if conf_u and (not conf_v or conf_u.id != conf_v.id):
                    ov = Vehiculo.query.get(conf_u.vehiculo_id)
                    key_parts.append(f"Operario → {ov.label() if ov else '?'}")
                key = " / ".join(key_parts) or "Conflicto"
                conflict_details.setdefault(key, []).append(d.strftime('%d/%m'))
            else:
                free_dates.append(d)

        conflict_dates_count = sum(len(v) for v in conflict_details.values())

        if mode in ('check', 'pure_check') and conflict_dates_count > 0:
            return {
                'success': False,
                'conflict': True,
                'conflict_type': 'admin_hard',
                'message': (
                    f'Conflicto de vehículo en {conflict_dates_count} día(s). '
                    f'El vehículo u operario ya tienen otra asignación.'
                ),
                'conflict_details': conflict_details,
                'req_count': conflict_dates_count,
            }

        if mode == 'pure_check':
            return {'success': True, 'message': 'Sin conflictos de vehículo'}

        if mode == 'only_free':
            dates_to_assign = free_dates
        elif mode == 'overwrite':
            dates_to_assign = [d for d in valid_dates if not AsignacionVehiculo.query.filter_by(
                vehiculo_id=vehicle.id, user_id=worker.id, fecha=d,
            ).first()]
        else:
            # check sin conflictos → free_dates
            dates_to_assign = free_dates

        if not dates_to_assign:
            msg = 'Sin cambios (ya asignado o sin días libres).'
            if skip_same:
                msg = f'Ya estaba asignado ({skip_same} d). No se asignó nada nuevo.'
            return {'success': True, 'action': 'assigned', 'message': msg}

        count = 0
        for d in dates_to_assign:
            CoreVehicleAssignmentService.asignar(
                vehicle.id, worker.id, d, actor_user.id, "Planificación Manual",
                overwrite=(mode == 'overwrite'),
                registrar_log=False,
            )
            count += 1
        if count:
            CoreVehicleAssignmentService.registrar_log_rango(
                worker.id, vehicle.id,
                min(dates_to_assign), max(dates_to_assign), count,
                actor_user.id, "Planificación Manual", True,
            )
        db.session.commit()
        return {
            'success': True,
            'action': 'assigned',
            'message': f'Vehículo asignado ({count} días).',
        }

    # ==========================================
    # JEFE → siempre solicitud
    # ==========================================
    if actor_user.role == ROLE_JEFE:
        # Días ya cubiertos por el mismo par se omiten de la petición
        dates_for_request = []
        for d in valid_dates:
            same = AsignacionVehiculo.query.filter_by(
                vehiculo_id=vehicle.id, user_id=worker.id, fecha=d,
            ).first()
            if same and accion == 'ASIGNAR':
                continue
            dates_for_request.append(d)

        if not dates_for_request:
            return {
                'success': True,
                'action': 'assigned',
                'message': 'El vehículo ya estaba asignado esos días.',
            }

        sol, status = VehicleSolicitudService.create_solicitud(
            requested_by_id=actor_user.id,
            empleado_id=worker.id,
            vehiculo_id=vehicle.id,
            dates=dates_for_request,
            accion=accion,
            notas=notas,
        )
        if status == 'new':
            msg = f'Solicitud de vehículo enviada ({len(dates_for_request)}d).'
        elif status == 'merged':
            msg = 'Solicitud de vehículo existente ampliada.'
        else:
            msg = 'Ya existía una solicitud de vehículo equivalente.'

        return {'success': True, 'action': 'requested', 'message': msg, 'solicitud_id': sol.id}

    return {'success': False, 'error': 'Rol no autorizado para asignar vehículos'}
