# app/services/core_assignment_service.py
#
# ÚNICA FUENTE DE LA VERDAD para mutaciones del cuadrante (Asignaciones).
# Todo el proyecto DEBE usar exclusivamente asignar() / desasignar()
# para crear o eliminar objetos Asignacion.

from app import db
from app.utils.timezone_utils import utc_now
from app.models import Asignacion, SystemLog, Obra, User
from app.services.log_coverage import attach_coverage, expand_contiguous


class CoreAssignmentService:

    @staticmethod
    def format_obra_label(obra):
        if not obra:
            return "Obra desconocida"
        codigo = (obra.codigo or "").strip()
        nombre = (obra.nombre or "").strip()
        if codigo and nombre:
            return f"{codigo} — {nombre}"
        return codigo or nombre or f"Obra #{obra.id}"

    @staticmethod
    def asignar(user_id, obra_id, fecha, autor_id, contexto_origen,
                detalle_extra=None, *, company_id=None, solicitud_id=None,
                registrar_log=True):
        """
        Crea una Asignacion. Por defecto registra SystemLog del día.
        autor_id es quien decide (auditor, planificador). None = proceso
        desatendido (p. ej. auto-asignación por fichaje físico).
        En lotes (rangos) pasar registrar_log=False y llamar registrar_log_rango.

        No crea la fila si ese día hay ausencia aprobada (baja y cuadrante
        no conviven). Devuelve None en ese caso.
        """
        from app.services.leave_service import user_has_approved_leave
        if user_has_approved_leave(user_id, fecha):
            return None

        nueva = Asignacion(
            user_id=user_id,
            obra_id=obra_id,
            fecha=fecha,
            company_id=company_id,
            solicitud_id=solicitud_id,
        )
        db.session.add(nueva)

        if registrar_log:
            CoreAssignmentService._registrar_log(
                user_id, obra_id, fecha, autor_id, contexto_origen,
                es_alta=True, detalle_extra=detalle_extra,
            )

        db.session.flush()
        try:
            from app.services.solicitud_service import (
                reconcile_solicitudes_after_cuadrante_change,
            )
            reconcile_solicitudes_after_cuadrante_change(
                obra_id, user_id, fecha, resolved_by_id=autor_id,
            )
        except Exception:
            # El cuadrante manda: un fallo de solicitudes no debe tumbar la asignación.
            import logging
            logging.getLogger(__name__).exception(
                'Post-asignar reconcile solicitudes user=%s obra=%s fecha=%s',
                user_id, obra_id, fecha,
            )
        return nueva

    @staticmethod
    def desasignar(user_id, obra_id, fecha, autor_id, contexto_origen,
                   detalle_extra=None, *, registrar_log=True):
        """
        Elimina la Asignacion (user_id, obra_id, fecha).
        Retorna True si se encontró y borró, False si no existía.
        """
        asig = Asignacion.query.filter_by(
            user_id=user_id, obra_id=obra_id, fecha=fecha,
        ).first()

        if not asig:
            return False

        db.session.delete(asig)

        if registrar_log:
            CoreAssignmentService._registrar_log(
                user_id, obra_id, fecha, autor_id, contexto_origen,
                es_alta=False, detalle_extra=detalle_extra,
            )

        db.session.flush()
        # Evita ObjectDeletedError si más tarde se toca la identidad en sesión.
        try:
            db.session.expunge(asig)
        except Exception:
            pass
        try:
            from app.services.solicitud_service import (
                reconcile_solicitudes_after_cuadrante_change,
            )
            reconcile_solicitudes_after_cuadrante_change(
                obra_id, user_id, fecha, resolved_by_id=autor_id,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'Post-desasignar reconcile solicitudes user=%s obra=%s fecha=%s',
                user_id, obra_id, fecha,
            )
        return True

    @staticmethod
    def registrar_log_rango(user_id, obra_id, fecha_inicio, fecha_fin, n_dias,
                            autor_id, contexto_origen, es_alta,
                            detalle_extra=None, fechas=None):
        """
        UNA entrada de SystemLog por acción (el listado de Planificación
        no se llena con un renglón por día). Persona a día proyecta esa
        fila sobre cada jornada cubierta. El cuadrante se puede borrar;
        este log no.
        """
        days = sorted({d for d in (fechas or []) if d})
        if not days:
            if not fecha_inicio or not n_dias or n_dias < 1:
                return
            last = fecha_fin or fecha_inicio
            span = (last - fecha_inicio).days + 1
            if n_dias == 1:
                days = [fecha_inicio]
            elif n_dias == span:
                days = expand_contiguous(fecha_inicio, last)
            else:
                CoreAssignmentService._registrar_log_rango_compacto(
                    user_id, obra_id, fecha_inicio, last, n_dias,
                    autor_id, contexto_origen, es_alta, detalle_extra,
                )
                return

        if len(days) == 1:
            CoreAssignmentService._registrar_log(
                user_id, obra_id, days[0], autor_id, contexto_origen,
                es_alta=es_alta, detalle_extra=detalle_extra,
            )
            return

        CoreAssignmentService._registrar_log_rango_compacto(
            user_id, obra_id, days[0], days[-1], len(days),
            autor_id, contexto_origen, es_alta, detalle_extra,
            fechas=days,
        )

    @staticmethod
    def _registrar_log_rango_compacto(user_id, obra_id, fecha_inicio, fecha_fin,
                                      n_dias, autor_id, contexto_origen, es_alta,
                                      detalle_extra=None, fechas=None):
        verbo = "Asignado" if es_alta else "Desasignado"
        obra = Obra.query.get(obra_id)
        user = User.query.get(user_id)
        obra_label = CoreAssignmentService.format_obra_label(obra)
        user_nombre = f"{user.name} {user.lastname}" if user else f"ID {user_id}"
        fi = fecha_inicio.strftime('%d/%m/%Y') if fecha_inicio else '?'
        ff = fecha_fin.strftime('%d/%m/%Y') if fecha_fin else '?'
        detail = f"{verbo} {user_nombre} → '{obra_label}' ({fi} → {ff}, {n_dias} días)."
        if detalle_extra:
            detail = f"{detail} {detalle_extra}"
        detail = attach_coverage(detail, fechas)
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
    def _registrar_log(user_id, obra_id, fecha, autor_id, contexto_origen,
                       es_alta, detalle_extra=None):
        verbo = "Asignado" if es_alta else "Desasignado"

        obra = Obra.query.get(obra_id)
        user = User.query.get(user_id)
        obra_label = CoreAssignmentService.format_obra_label(obra)
        user_nombre = f"{user.name} {user.lastname}" if user else f"ID {user_id}"

        detail = f"{verbo} {user_nombre} → '{obra_label}' ({fecha.strftime('%d/%m/%Y')})."
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
