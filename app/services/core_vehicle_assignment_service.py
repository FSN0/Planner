# app/services/core_vehicle_assignment_service.py
#
# ÚNICA FUENTE DE LA VERDAD para mutaciones de AsignacionVehiculo.
# Usar exclusivamente asignar() / desasignar().

from app import db
from app.utils.timezone_utils import utc_now
from app.models import AsignacionVehiculo, SystemLog, Vehiculo, User


class CoreVehicleAssignmentService:

    @staticmethod
    def format_vehiculo_label(vehiculo):
        if not vehiculo:
            return "Vehículo desconocido"
        return vehiculo.label()

    @staticmethod
    def _is_system_action(contexto_origen):
        return (
            contexto_origen in (
                "Auto-asignación por Fichaje Físico",
                "Actualización de Cuadrante (Auto)",
            )
            or "(Auto)" in (contexto_origen or "")
        )

    @staticmethod
    def asignar(vehiculo_id, user_id, fecha, autor_id, contexto_origen,
                detalle_extra=None, *, solicitud_id=None, overwrite=False):
        """
        Crea AsignacionVehiculo y SystemLog (category=planificacion).
        Hace flush(); commit queda al flujo superior.

        Si overwrite=True y hay conflicto (vehículo u operario ocupado ese día
        por otra pareja), desasigna primero las filas conflictivas.
        Si overwrite=False y hay conflicto, lanza ValueError.
        Si ya existe la misma pareja (vehiculo, user, fecha), retorna esa fila.
        """
        existing_same = AsignacionVehiculo.query.filter_by(
            vehiculo_id=vehiculo_id, user_id=user_id, fecha=fecha,
        ).first()
        if existing_same:
            return existing_same

        conflict_vehicle = AsignacionVehiculo.query.filter_by(
            vehiculo_id=vehiculo_id, fecha=fecha,
        ).first()
        conflict_user = AsignacionVehiculo.query.filter_by(
            user_id=user_id, fecha=fecha,
        ).first()

        if conflict_vehicle or conflict_user:
            if not overwrite:
                parts = []
                if conflict_vehicle and conflict_vehicle.user_id != user_id:
                    other = User.query.get(conflict_vehicle.user_id)
                    other_name = f"{other.name} {other.lastname}" if other else f"ID {conflict_vehicle.user_id}"
                    parts.append(f"vehículo ya asignado a {other_name}")
                if conflict_user and conflict_user.vehiculo_id != vehiculo_id:
                    v = Vehiculo.query.get(conflict_user.vehiculo_id)
                    parts.append(f"operario ya tiene {CoreVehicleAssignmentService.format_vehiculo_label(v)}")
                raise ValueError(
                    f"Conflicto el {fecha.strftime('%d/%m/%Y')}: " + ("; ".join(parts) or "ocupación")
                )

            if conflict_vehicle and conflict_vehicle.user_id != user_id:
                CoreVehicleAssignmentService.desasignar(
                    conflict_vehicle.vehiculo_id, conflict_vehicle.user_id, fecha,
                    autor_id, contexto_origen,
                    detalle_extra="Sobreescritura: liberar vehículo.",
                )
            if conflict_user and conflict_user.vehiculo_id != vehiculo_id:
                # Puede quedar tras liberar vehículo si era otra pareja
                still = AsignacionVehiculo.query.filter_by(user_id=user_id, fecha=fecha).first()
                if still:
                    CoreVehicleAssignmentService.desasignar(
                        still.vehiculo_id, still.user_id, fecha,
                        autor_id, contexto_origen,
                        detalle_extra="Sobreescritura: liberar operario.",
                    )

        nueva = AsignacionVehiculo(
            vehiculo_id=vehiculo_id,
            user_id=user_id,
            fecha=fecha,
            solicitud_id=solicitud_id,
        )
        db.session.add(nueva)

        CoreVehicleAssignmentService._registrar_log(
            user_id, vehiculo_id, fecha, autor_id, contexto_origen,
            es_alta=True, detalle_extra=detalle_extra,
        )

        db.session.flush()
        return nueva

    @staticmethod
    def desasignar(vehiculo_id, user_id, fecha, autor_id, contexto_origen,
                   detalle_extra=None):
        """
        Elimina AsignacionVehiculo (vehiculo_id, user_id, fecha) y registra log.
        Retorna True si borró, False si no existía.
        """
        asig = AsignacionVehiculo.query.filter_by(
            vehiculo_id=vehiculo_id, user_id=user_id, fecha=fecha,
        ).first()
        if not asig:
            return False

        db.session.delete(asig)

        CoreVehicleAssignmentService._registrar_log(
            user_id, vehiculo_id, fecha, autor_id, contexto_origen,
            es_alta=False, detalle_extra=detalle_extra,
        )

        db.session.flush()
        return True

    @staticmethod
    def _registrar_log(user_id, vehiculo_id, fecha, autor_id, contexto_origen,
                       es_alta, detalle_extra=None):
        verbo = "Asignado" if es_alta else "Desasignado"

        vehiculo = Vehiculo.query.get(vehiculo_id)
        user = User.query.get(user_id)
        v_label = CoreVehicleAssignmentService.format_vehiculo_label(vehiculo)
        user_nombre = f"{user.name} {user.lastname}" if user else f"ID {user_id}"

        detail = (
            f"Vehículo {v_label} → {user_nombre} ({fecha.strftime('%d/%m/%Y')}). "
            f"{verbo}."
        )
        if detalle_extra:
            detail = f"{detail} {detalle_extra}"

        log_user_id = None if CoreVehicleAssignmentService._is_system_action(contexto_origen) else autor_id

        db.session.add(SystemLog(
            timestamp=utc_now(),
            user_id=log_user_id,
            category='planificacion',
            action=contexto_origen,
            detail=detail,
            target_user_id=user_id,
            target_date=fecha,
        ))
