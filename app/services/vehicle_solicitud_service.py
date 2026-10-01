# app/services/vehicle_solicitud_service.py

from datetime import datetime, date, timedelta

from app import db
from app.utils.timezone_utils import utc_now
from app.models import SolicitudVehiculo, Vehiculo, User
from app.services.core_vehicle_assignment_service import CoreVehicleAssignmentService
from app.services.email_service import (
    notificar_nueva_solicitud_vehiculo,
    notificar_resolucion_solicitud_vehiculo,
)
from app.services.permission_service import can_resolve_solicitudes_flota
from app.services.solicitud_service import merge_notas


def log_nueva_solicitud_vehiculo(solicitud):
    """Registra SystemLog category=solicitud al crear SolicitudVehiculo."""
    from app.utils import register_log

    accion = (getattr(solicitud, 'accion', None) or 'ASIGNAR').upper()
    action = f"Nueva solicitud VEHICULO"
    if accion == 'DESASIGNAR':
        action = "Nueva solicitud VEHICULO DESASIGNAR"

    emp = getattr(solicitud, 'empleado', None) or User.query.get(solicitud.empleado_id)
    emp_txt = f"{emp.name} {emp.lastname}".strip() if emp else f"user #{solicitud.empleado_id}"

    veh = getattr(solicitud, 'vehiculo', None)
    if veh is None and solicitud.vehiculo_id:
        veh = Vehiculo.query.get(solicitud.vehiculo_id)
    veh_txt = veh.label() if veh else (f"vehículo #{solicitud.vehiculo_id}" if solicitud.vehiculo_id else "cualquier")

    requester = getattr(solicitud, 'requested_by', None) or User.query.get(solicitud.requested_by_id)
    req_txt = f"{requester.name} {requester.lastname}".strip() if requester else f"user #{solicitud.requested_by_id}"

    fi = solicitud.fecha_inicio.strftime('%Y-%m-%d') if solicitud.fecha_inicio else '?'
    ff = solicitud.fecha_fin.strftime('%Y-%m-%d') if solicitud.fecha_fin else '?'

    detail = (
        f"Vehículo: {veh_txt} | Empleado: {emp_txt} | "
        f"Fechas: {fi} → {ff} | Solicitante: {req_txt}"
    )

    register_log(
        user_id=solicitud.requested_by_id,
        category='solicitud',
        action=action,
        detail=detail,
        target_user_id=solicitud.empleado_id,
    )


class VehicleSolicitudService:

    @staticmethod
    def create_solicitud(requested_by_id, empleado_id, vehiculo_id, dates, *,
                         accion='ASIGNAR', notas=None, merge_overlapping=True):
        """
        Crea SolicitudVehiculo (o amplía una abierta solapada).
        dates: list[date|str]. Commit incluido.
        Retorna (solicitud, status) con status in new|merged|duplicate.
        """
        valid = []
        for d in dates:
            if isinstance(d, str):
                try:
                    valid.append(datetime.strptime(d, "%Y-%m-%d").date())
                except ValueError:
                    continue
            elif isinstance(d, date):
                valid.append(d)
        valid = sorted(set(valid))
        if not valid:
            raise ValueError("No hay fechas válidas")
        if not empleado_id:
            raise ValueError("empleado_id es obligatorio")
        if not vehiculo_id:
            raise ValueError("vehiculo_id es obligatorio para solicitud concreta")

        start_date = min(valid)
        end_date = max(valid)
        accion = (accion or 'ASIGNAR').upper()

        if merge_overlapping:
            open_qs = SolicitudVehiculo.query.filter_by(
                empleado_id=empleado_id,
                vehiculo_id=vehiculo_id,
                accion=accion,
            ).filter(
                SolicitudVehiculo.estado.in_(['PENDIENTE', 'EN_PROCESO'])
            ).all()

            for existing in open_qs:
                if (existing.fecha_inicio - timedelta(days=1)) <= end_date and \
                   (existing.fecha_fin + timedelta(days=1)) >= start_date:
                    if existing.fecha_inicio <= start_date and existing.fecha_fin >= end_date:
                        if notas:
                            existing.notas = merge_notas(existing.notas, notas)
                            db.session.commit()
                        return existing, "duplicate"
                    existing.fecha_inicio = min(existing.fecha_inicio, start_date)
                    existing.fecha_fin = max(existing.fecha_fin, end_date)
                    existing.notas = merge_notas(existing.notas, notas)
                    db.session.commit()
                    return existing, "merged"

        sol = SolicitudVehiculo(
            accion=accion,
            requested_by_id=requested_by_id,
            empleado_id=empleado_id,
            vehiculo_id=vehiculo_id,
            fecha_inicio=start_date,
            fecha_fin=end_date,
            estado='PENDIENTE',
            notas=(notas or '').strip() or None,
        )
        db.session.add(sol)
        db.session.commit()
        log_nueva_solicitud_vehiculo(sol)
        requester = User.query.get(requested_by_id)
        notificar_nueva_solicitud_vehiculo(
            sol, requester.name if requester else 'Sistema'
        )
        return sol, "new"

    @staticmethod
    def list_open(*, empleado_id=None, vehiculo_id=None):
        q = SolicitudVehiculo.query.filter(
            SolicitudVehiculo.estado.in_(['PENDIENTE', 'EN_PROCESO'])
        )
        if empleado_id:
            q = q.filter_by(empleado_id=empleado_id)
        if vehiculo_id:
            q = q.filter_by(vehiculo_id=vehiculo_id)
        return q.order_by(SolicitudVehiculo.created_at.desc()).all()

    @staticmethod
    def resolve(solicitud, decision, actor, *, overwrite=True):
        """
        decision: 'aceptar' | 'denegar'
        Aceptar ASIGNAR → crea AsignacionVehiculo por cada día del rango.
        Aceptar DESASIGNAR → desasigna esos días.
        """
        if not can_resolve_solicitudes_flota(actor):
            raise PermissionError("No tienes permiso para resolver solicitudes de vehículo.")

        decision = (decision or '').lower()
        if decision in ('denegar', 'deny', 'rechazar'):
            solicitud.estado = 'DENEGADA'
            solicitud.resolved_at = utc_now()
            solicitud.resolved_by_id = actor.id
            db.session.commit()
            notificar_resolucion_solicitud_vehiculo(
                solicitud, f"{actor.name} {actor.lastname}".strip() or actor.name
            )
            return "Solicitud de vehículo denegada."

        if decision not in ('aceptar', 'approve', 'aprobar'):
            raise ValueError("Decisión no reconocida.")

        if not solicitud.empleado_id:
            raise ValueError("Solicitud sin empleado.")
        if not solicitud.vehiculo_id and (solicitud.accion or 'ASIGNAR') == 'ASIGNAR':
            raise ValueError("Solicitud de asignación sin vehículo.")

        days = []
        curr = solicitud.fecha_inicio
        while curr <= solicitud.fecha_fin:
            days.append(curr)
            curr += timedelta(days=1)

        accion = (solicitud.accion or 'ASIGNAR').upper()
        count = 0
        omitidos_ausencia = 0

        if accion == 'DESASIGNAR':
            for d in days:
                if CoreVehicleAssignmentService.desasignar(
                    solicitud.vehiculo_id, solicitud.empleado_id, d,
                    actor.id, "Resolución de Solicitud Vehículo",
                    registrar_log=False,
                ):
                    count += 1
        else:
            from app.services.leave_service import user_has_approved_leave
            for d in days:
                if user_has_approved_leave(solicitud.empleado_id, d):
                    omitidos_ausencia += 1
                    continue
                CoreVehicleAssignmentService.asignar(
                    solicitud.vehiculo_id, solicitud.empleado_id, d,
                    actor.id, "Resolución de Solicitud Vehículo",
                    solicitud_id=solicitud.id, overwrite=overwrite,
                    registrar_log=False,
                )
                count += 1

        if count and days:
            CoreVehicleAssignmentService.registrar_log_rango(
                solicitud.empleado_id, solicitud.vehiculo_id,
                days[0], days[-1], count,
                actor.id, "Resolución de Solicitud Vehículo",
                es_alta=(accion != 'DESASIGNAR'),
            )

        solicitud.estado = 'CUMPLIDA'
        solicitud.resolved_at = utc_now()
        solicitud.resolved_by_id = actor.id
        db.session.commit()
        notificar_resolucion_solicitud_vehiculo(
            solicitud, f"{actor.name} {actor.lastname}".strip() or actor.name
        )
        msg = f"Solicitud de vehículo aceptada ({count} día(s))."
        if omitidos_ausencia:
            msg += f" Omitidos {omitidos_ausencia} d. con ausencia aprobada."
        return msg
