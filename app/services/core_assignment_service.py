# app/services/core_assignment_service.py
#
# ÚNICA FUENTE DE LA VERDAD para mutaciones del cuadrante (Asignaciones).
# Todo el proyecto DEBE usar exclusivamente asignar() / desasignar()
# para crear o eliminar objetos Asignacion.

from app import db
from app.utils.timezone_utils import utc_now
from app.models import Asignacion, SystemLog, Obra, User


class CoreAssignmentService:

    @staticmethod
    def asignar(user_id, obra_id, fecha, autor_id, contexto_origen,
                detalle_extra=None, *, company_id=None, solicitud_id=None):
        """
        Crea una Asignacion y registra un SystemLog en la misma transacción.
        Hace flush() para garantizar integridad referencial; el commit()
        queda como responsabilidad del flujo superior.

        Retorna el objeto Asignacion recién creado.
        """
        nueva = Asignacion(
            user_id=user_id,
            obra_id=obra_id,
            fecha=fecha,
            company_id=company_id,
            solicitud_id=solicitud_id,
        )
        db.session.add(nueva)

        CoreAssignmentService._registrar_log(
            user_id, obra_id, fecha, autor_id, contexto_origen,
            es_alta=True, detalle_extra=detalle_extra,
        )

        db.session.flush()
        return nueva

    @staticmethod
    def desasignar(user_id, obra_id, fecha, autor_id, contexto_origen,
                   detalle_extra=None):
        """
        Elimina la Asignacion que coincida con (user_id, obra_id, fecha)
        y registra un SystemLog en la misma transacción.
        Hace flush(); el commit() queda para el flujo superior.

        Retorna True si se encontró y borró, False si no existía.
        """
        asig = Asignacion.query.filter_by(
            user_id=user_id, obra_id=obra_id, fecha=fecha,
        ).first()

        if not asig:
            return False

        db.session.delete(asig)

        CoreAssignmentService._registrar_log(
            user_id, obra_id, fecha, autor_id, contexto_origen,
            es_alta=False, detalle_extra=detalle_extra,
        )

        db.session.flush()
        return True

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------
    @staticmethod
    def _registrar_log(user_id, obra_id, fecha, autor_id, contexto_origen,
                       es_alta, detalle_extra=None):
        verbo = "Asignado" if es_alta else "Desasignado"

        obra = Obra.query.get(obra_id)
        user = User.query.get(user_id)
        obra_nombre = obra.nombre if obra else f"Obra ID {obra_id}"
        user_nombre = f"{user.name} {user.lastname}" if user else f"ID {user_id}"

        detail = f"{verbo} {user_nombre} → '{obra_nombre}' ({fecha.strftime('%d/%m/%Y')})."
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
