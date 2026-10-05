# app/services/core_vehicle_assignment_service.py
#
# ÚNICA FUENTE DE LA VERDAD para mutaciones de AsignacionVehiculo.
# Usar exclusivamente asignar() / desasignar() / marcar_no_usada().

from app import db
from app.utils.timezone_utils import utc_now
from app.models import AsignacionVehiculo, SystemLog, Vehiculo, User

EFECTIVA = AsignacionVehiculo.ESTADO_EFECTIVA
NO_USADA = AsignacionVehiculo.ESTADO_NO_USADA


class CoreVehicleAssignmentService:

    @staticmethod
    def format_vehiculo_label(vehiculo):
        if not vehiculo:
            return "Vehículo desconocido"
        return vehiculo.label()

    @staticmethod
    def get_efectiva_user(user_id, fecha):
        return AsignacionVehiculo.query.filter_by(
            user_id=user_id, fecha=fecha, estado=EFECTIVA,
        ).first()

    @staticmethod
    def get_efectiva_vehiculo(vehiculo_id, fecha):
        return AsignacionVehiculo.query.filter_by(
            vehiculo_id=vehiculo_id, fecha=fecha, estado=EFECTIVA,
        ).first()

    @staticmethod
    def asignar(vehiculo_id, user_id, fecha, autor_id, contexto_origen,
                detalle_extra=None, *, solicitud_id=None, overwrite=False,
                registrar_log=True, notas=None, estado=None):
        """
        Crea o reutiliza AsignacionVehiculo efectiva (por defecto).
        En lotes: registrar_log=False + registrar_log_rango.
        """
        estado = estado or EFECTIVA
        existing_same = AsignacionVehiculo.query.filter_by(
            vehiculo_id=vehiculo_id, user_id=user_id, fecha=fecha,
        ).first()
        if existing_same:
            changed = False
            if existing_same.estado != estado:
                existing_same.estado = estado
                changed = True
            if notas is not None and (existing_same.notas or '') != notas:
                existing_same.notas = notas
                changed = True
            if solicitud_id is not None and existing_same.solicitud_id != solicitud_id:
                existing_same.solicitud_id = solicitud_id
                changed = True
            if changed:
                db.session.flush()
            return existing_same

        conflict_vehicle = None
        conflict_user = None
        if estado == EFECTIVA:
            conflict_vehicle = CoreVehicleAssignmentService.get_efectiva_vehiculo(vehiculo_id, fecha)
            conflict_user = CoreVehicleAssignmentService.get_efectiva_user(user_id, fecha)

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
                    registrar_log=registrar_log,
                )
            if conflict_user and conflict_user.vehiculo_id != vehiculo_id:
                still = CoreVehicleAssignmentService.get_efectiva_user(user_id, fecha)
                if still:
                    CoreVehicleAssignmentService.desasignar(
                        still.vehiculo_id, still.user_id, fecha,
                        autor_id, contexto_origen,
                        detalle_extra="Sobreescritura: liberar operario.",
                        registrar_log=registrar_log,
                    )

        nueva = AsignacionVehiculo(
            vehiculo_id=vehiculo_id,
            user_id=user_id,
            fecha=fecha,
            solicitud_id=solicitud_id,
            estado=estado,
            notas=notas,
        )
        db.session.add(nueva)

        if registrar_log:
            CoreVehicleAssignmentService._registrar_log(
                user_id, vehiculo_id, fecha, autor_id, contexto_origen,
                es_alta=True, detalle_extra=detalle_extra,
            )

        db.session.flush()
        return nueva

    @staticmethod
    def marcar_no_usada(vehiculo_id, user_id, fecha, autor_id, contexto_origen,
                        notas=None, *, registrar_log=True):
        """Pasa una asignación (normalmente efectiva) a rastro no_usada."""
        asig = AsignacionVehiculo.query.filter_by(
            vehiculo_id=vehiculo_id, user_id=user_id, fecha=fecha,
        ).first()
        if not asig:
            return CoreVehicleAssignmentService.asignar(
                vehiculo_id, user_id, fecha, autor_id, contexto_origen,
                detalle_extra="Rastro plan no usado.",
                registrar_log=registrar_log,
                notas=notas,
                estado=NO_USADA,
            )
        asig.estado = NO_USADA
        if notas is not None:
            asig.notas = notas
        if registrar_log:
            CoreVehicleAssignmentService._registrar_log(
                user_id, vehiculo_id, fecha, autor_id, contexto_origen,
                es_alta=False,
                detalle_extra='Marcado como planificado no usado.',
            )
        db.session.flush()
        return asig

    @staticmethod
    def desasignar(vehiculo_id, user_id, fecha, autor_id, contexto_origen,
                   detalle_extra=None, *, registrar_log=True):
        """
        Elimina AsignacionVehiculo (vehiculo_id, user_id, fecha).
        Retorna True si borró, False si no existía.
        """
        asig = AsignacionVehiculo.query.filter_by(
            vehiculo_id=vehiculo_id, user_id=user_id, fecha=fecha,
        ).first()
        if not asig:
            return False

        db.session.delete(asig)

        if registrar_log:
            CoreVehicleAssignmentService._registrar_log(
                user_id, vehiculo_id, fecha, autor_id, contexto_origen,
                es_alta=False, detalle_extra=detalle_extra,
            )

        db.session.flush()
        return True

    @staticmethod
    def registrar_log_rango(user_id, vehiculo_id, fecha_inicio, fecha_fin, n_dias,
                            autor_id, contexto_origen, es_alta,
                            detalle_extra=None):
        """Una sola entrada de log para un rango de vehículo."""
        if not n_dias or n_dias < 1:
            return
        if n_dias == 1 and fecha_inicio and fecha_fin and fecha_inicio == fecha_fin:
            CoreVehicleAssignmentService._registrar_log(
                user_id, vehiculo_id, fecha_inicio, autor_id, contexto_origen,
                es_alta=es_alta, detalle_extra=detalle_extra,
            )
            return

        verbo = "Asignado" if es_alta else "Desasignado"
        vehiculo = Vehiculo.query.get(vehiculo_id)
        user = User.query.get(user_id)
        v_label = CoreVehicleAssignmentService.format_vehiculo_label(vehiculo)
        user_nombre = f"{user.name} {user.lastname}" if user else f"ID {user_id}"
        fi = fecha_inicio.strftime('%d/%m/%Y') if fecha_inicio else '?'
        ff = fecha_fin.strftime('%d/%m/%Y') if fecha_fin else '?'
        detail = (
            f"Vehículo {v_label} → {user_nombre} ({fi} → {ff}, {n_dias} días). "
            f"{verbo}."
        )
        if detalle_extra:
            detail = f"{detail} {detalle_extra}"

        db.session.add(SystemLog(
            timestamp=utc_now(),
            user_id=autor_id,
            category='planificacion',
            action=contexto_origen,
            detail=detail,
            target_user_id=user_id,
            target_date=fecha_inicio,
        ))

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

        db.session.add(SystemLog(
            timestamp=utc_now(),
            user_id=autor_id,
            category='planificacion',
            action=contexto_origen,
            detail=detail,
            target_user_id=user_id,
            target_date=fecha,
        ))
