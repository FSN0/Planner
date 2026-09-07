"""Desvío de fichaje: planificado en X, ficha en Y.

Un solo RegistroFichaje en Conflicto, dos firmas cuando los jefes son distintos:
- lado plan (X): liberar plaza
- lado real (Y): aceptar entrada

Si el mismo jefe gestiona ambas obras (o un admin fuerza), una sola acción cierra todo.
No se mueve la asignación al fichar: eso lo hace la firma del plan / confirmar.
"""
from __future__ import annotations

import logging

from app import db
from app.models import Obra, RegistroFichaje, ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH
from app.services.core_assignment_service import CoreAssignmentService
from app.utils.timezone_utils import utc_now

logger = logging.getLogger(__name__)

ACCION_LIBERAR_PLAZA = 'liberar_plaza'
ACCION_ACEPTAR_ENTRADA = 'aceptar_entrada'
ACCION_CONFIRMAR_DESVIO = 'confirmar_desvio'

_ACCIONES_DESVIO = frozenset({
    ACCION_LIBERAR_PLAZA,
    ACCION_ACEPTAR_ENTRADA,
    ACCION_CONFIRMAR_DESVIO,
})


class DesvioFichajeError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def es_desvio_plan_vs_real(registro):
    """Conflicto (u homólogo) con obra planificada distinta de la fichada."""
    if not registro:
        return False
    if (registro.estado or '') != 'Conflicto':
        return False
    plan = registro.obra_planificada_id
    real = registro.obra_real_id
    return bool(plan and real and plan != real)


def _jefe_obra_id(obra_id):
    if not obra_id:
        return None
    obra = Obra.query.get(obra_id)
    return obra.jefe_obra_id if obra else None


def jefes_desvio(registro):
    return (
        _jefe_obra_id(registro.obra_planificada_id),
        _jefe_obra_id(registro.obra_real_id),
    )


def mismo_jefe_desvio(registro):
    jp, jr = jefes_desvio(registro)
    return bool(jp and jr and jp == jr)


def desvio_ack_plan_hecho(registro):
    return bool(getattr(registro, 'desvio_ack_plan_at', None))


def desvio_ack_real_hecho(registro):
    return bool(getattr(registro, 'desvio_ack_real_at', None))


def desvio_completo(registro):
    return desvio_ack_plan_hecho(registro) and desvio_ack_real_hecho(registro)


def obras_del_jefe(user):
    if not user or getattr(user, 'role', None) != ROLE_JEFE:
        return []
    return [o.id for o in Obra.query.filter_by(jefe_obra_id=user.id).all()]


def lados_visibles_para(registro, user):
    """Qué lados del desvío gestiona este usuario: plan, real, ambos."""
    if not es_desvio_plan_vs_real(registro) or not user:
        return set()
    role = getattr(user, 'role', None)
    if role in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH):
        return {'plan', 'real'}
    if role != ROLE_JEFE:
        return set()
    mias = set(obras_del_jefe(user))
    lados = set()
    if registro.obra_planificada_id in mias:
        lados.add('plan')
    if registro.obra_real_id in mias:
        lados.add('real')
    return lados


def lados_pendientes_para(registro, user):
    """Lados que aún puede firmar este usuario."""
    visibles = lados_visibles_para(registro, user)
    pendientes = set()
    if 'plan' in visibles and not desvio_ack_plan_hecho(registro):
        pendientes.add('plan')
    if 'real' in visibles and not desvio_ack_real_hecho(registro):
        pendientes.add('real')
    return pendientes


def debe_mostrar_pendiente_a(registro, user):
    """Fila de auditoría: visible si al usuario le queda algo por firmar (o es admin)."""
    if not es_desvio_plan_vs_real(registro):
        return True
    if getattr(user, 'role', None) in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH):
        return not desvio_completo(registro)
    return bool(lados_pendientes_para(registro, user))


def _marcar_ack_plan(registro, user):
    if desvio_ack_plan_hecho(registro):
        return False
    registro.desvio_ack_plan_at = utc_now()
    registro.desvio_ack_plan_by_id = user.id if user else None
    return True


def _marcar_ack_real(registro, user):
    if desvio_ack_real_hecho(registro):
        return False
    registro.desvio_ack_real_at = utc_now()
    registro.desvio_ack_real_by_id = user.id if user else None
    return True


def _liberar_plaza_plan(registro, actor):
    """Quita la asignación de la obra planificada (X)."""
    from app.models import Asignacion

    plan_id = registro.obra_planificada_id
    if not plan_id:
        return
    asignaciones = Asignacion.query.filter_by(
        user_id=registro.user_id,
        fecha=registro.fecha,
        obra_id=plan_id,
    ).all()
    for asig in asignaciones:
        CoreAssignmentService.desasignar(
            asig.user_id,
            asig.obra_id,
            asig.fecha,
            actor.id if actor else None,
            'Desvío fichaje: liberar plaza',
        )


def _aceptar_entrada_real(registro, actor):
    """Asegura asignación en la obra fichada (Y)."""
    from app.models import Asignacion

    real_id = registro.obra_real_id
    if not real_id:
        return
    existe = Asignacion.query.filter_by(
        user_id=registro.user_id,
        fecha=registro.fecha,
        obra_id=real_id,
    ).first()
    if existe:
        return
    CoreAssignmentService.asignar(
        registro.user_id,
        real_id,
        registro.fecha,
        actor.id if actor else None,
        'Desvío fichaje: aceptar entrada',
    )


def _cerrar_si_completo(registro, actor):
    if not desvio_completo(registro):
        return False
    registro.estado_antes_resolucion = registro.estado_antes_resolucion or 'Conflicto'
    registro.estado = 'Resuelto_Movido'
    registro.resuelto_por_id = actor.id if actor else registro.resuelto_por_id
    registro.fecha_auditoria = utc_now()
    plan_lbl = CoreAssignmentService.format_obra_label(
        Obra.query.get(registro.obra_planificada_id)
    ) if registro.obra_planificada_id else '—'
    real_lbl = CoreAssignmentService.format_obra_label(
        Obra.query.get(registro.obra_real_id)
    ) if registro.obra_real_id else '—'
    registro.notas_resolucion = (
        f"Desvío cerrado: liberada plaza en '{plan_lbl}' "
        f"y aceptada entrada en '{real_lbl}'."
    )
    return True


def _autorizar_accion(registro, user, accion):
    pendientes = lados_pendientes_para(registro, user)
    if accion == ACCION_LIBERAR_PLAZA:
        if 'plan' not in pendientes and not (
            getattr(user, 'role', None) in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH)
            and not desvio_ack_plan_hecho(registro)
        ):
            raise DesvioFichajeError('No te corresponde liberar la plaza del plan.', status=403)
        return
    if accion == ACCION_ACEPTAR_ENTRADA:
        if 'real' not in pendientes and not (
            getattr(user, 'role', None) in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH)
            and not desvio_ack_real_hecho(registro)
        ):
            raise DesvioFichajeError('No te corresponde aceptar la entrada en esta obra.', status=403)
        return
    if accion == ACCION_CONFIRMAR_DESVIO:
        # Mismo jefe con ambos lados, o admin/laboral.
        role = getattr(user, 'role', None)
        if role in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH):
            return
        if lados_visibles_para(registro, user) == {'plan', 'real'}:
            return
        raise DesvioFichajeError(
            'Solo puedes confirmar el desvío completo si gestionas ambas obras.',
            status=403,
        )
    raise DesvioFichajeError('Acción de desvío no reconocida.', status=400)


def aplicar_accion_desvio(registro, accion, user):
    """
    Aplica liberar / aceptar / confirmar.
    Devuelve dict: resolved, dismiss_for_viewer, message.
    """
    if accion not in _ACCIONES_DESVIO:
        raise DesvioFichajeError('Acción de desvío no reconocida.', status=400)
    if not es_desvio_plan_vs_real(registro):
        raise DesvioFichajeError('Este registro no es un desvío plan→ficha.', status=400)

    _autorizar_accion(registro, user, accion)

    if accion == ACCION_LIBERAR_PLAZA:
        _liberar_plaza_plan(registro, user)
        _marcar_ack_plan(registro, user)
        msg = 'Plaza liberada en la obra planificada.'
    elif accion == ACCION_ACEPTAR_ENTRADA:
        _aceptar_entrada_real(registro, user)
        _marcar_ack_real(registro, user)
        msg = 'Entrada aceptada en la obra del fichaje.'
    else:  # confirmar_desvio
        if not desvio_ack_plan_hecho(registro):
            _liberar_plaza_plan(registro, user)
            _marcar_ack_plan(registro, user)
        if not desvio_ack_real_hecho(registro):
            _aceptar_entrada_real(registro, user)
            _marcar_ack_real(registro, user)
        msg = 'Desvío confirmado en ambas obras.'

    resolved = _cerrar_si_completo(registro, user)
    if resolved:
        msg = registro.notas_resolucion or msg

    dismiss = resolved or not lados_pendientes_para(registro, user)
    return {
        'resolved': resolved,
        'dismiss_for_viewer': dismiss,
        'message': msg,
        'ack_plan': desvio_ack_plan_hecho(registro),
        'ack_real': desvio_ack_real_hecho(registro),
    }


def botones_desvio_para(registro, user):
    """Lista de botones {accion, label, title, style} para la UI."""
    if not es_desvio_plan_vs_real(registro) or not user:
        return []
    pendientes = lados_pendientes_para(registro, user)
    if not pendientes:
        return []

    visibles = lados_visibles_para(registro, user)
    role = getattr(user, 'role', None)
    es_oficina = role in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH)
    gestiona_ambos = visibles == {'plan', 'real'} or es_oficina

    botones = []
    if pendientes == {'plan', 'real'} and gestiona_ambos:
        botones.append({
            'accion': ACCION_CONFIRMAR_DESVIO,
            'label': 'Confirmar desvío',
            'title': 'Libera la plaza del plan y acepta la entrada en la obra fichada',
            'style': 'primary',
        })
        if not es_oficina:
            return botones

    if 'plan' in pendientes:
        botones.append({
            'accion': ACCION_LIBERAR_PLAZA,
            'label': 'Liberar plaza',
            'title': 'Confirma que no viene a tu obra; ya fichó en otra',
            'style': 'danger',
        })
    if 'real' in pendientes:
        botones.append({
            'accion': ACCION_ACEPTAR_ENTRADA,
            'label': 'Aceptar entrada',
            'title': 'Acepta en tu obra a quien venía planificado de otra',
            'style': 'primary',
        })
    return botones


def contexto_desvio_para_plantilla(registro, user):
    if not es_desvio_plan_vs_real(registro):
        return None
    jp, jr = jefes_desvio(registro)
    return {
        'es_desvio': True,
        'mismo_jefe': bool(jp and jr and jp == jr),
        'ack_plan': desvio_ack_plan_hecho(registro),
        'ack_real': desvio_ack_real_hecho(registro),
        'botones': botones_desvio_para(registro, user),
        'pendientes_viewer': sorted(lados_pendientes_para(registro, user)),
    }


def enriquecer_pendientes_desvio(pendientes, user):
    """Filtra filas de desvío ya firmadas por este viewer y adjunta contexto UI."""
    out = []
    for reg in pendientes:
        if es_desvio_plan_vs_real(reg) and not debe_mostrar_pendiente_a(reg, user):
            continue
        reg.desvio_ui = contexto_desvio_para_plantilla(reg, user)
        out.append(reg)
    return out


def notificar_desvio_inmediato(registro):
    """Mail al instante a jefes de plan y de ficha (deduplicado)."""
    if not es_desvio_plan_vs_real(registro):
        return
    try:
        from app.services.email_service import notificar_desvio_fichaje
        notificar_desvio_fichaje(registro)
    except Exception:
        logger.exception(
            'No se pudo notificar desvío fichaje id=%s', getattr(registro, 'id', None)
        )
