"""Desvío de fichaje: planificado en X, ficha en Y.

Contrato de producto (a favor / en contra por lado):
- Jefe de X (plan):
    Liberar          → a favor del desvío
    Mantener falta   → en contra (sigue debiendo venir a X)
- Jefe de Y (ficha):
    Aceptar          → a favor (se queda en Y)
    Rechazar         → en contra (fichaje no vale en Y)
- Mismo jefe / oficina:
    Confirmar        → Liberar + Aceptar
    Mantener         → Mantener falta + Rechazar
    (+ Ignorar oficina: archiva sin tocar cuadrante)

Matriz al decidir ambos lados:
- Liberar + Aceptar           → mueve cuadrante X→Y (Resuelto_Movido)
- Mantener falta + Rechazar   → falta en X, fichaje Y no oficial (Resuelto_Ausencia)
- Cruce                       → Disputa (oficina)

Los cambios de cuadrante se aplican solo al cerrar la matriz (o Confirmar/Mantener).
"""
from __future__ import annotations

import logging

from app.models import Obra, ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH
from app.services.core_assignment_service import CoreAssignmentService
from app.utils.timezone_utils import utc_now

logger = logging.getLogger(__name__)

ACCION_LIBERAR_PLAZA = 'liberar_plaza'
ACCION_MANTENER_FALTA = 'mantener_falta'
ACCION_ACEPTAR_ENTRADA = 'aceptar_entrada'
ACCION_RECHAZAR_ENTRADA = 'rechazar_entrada'
ACCION_CONFIRMAR_DESVIO = 'confirmar_desvio'
ACCION_RECHAZAR_DESVIO = 'rechazar_desvio'

DECISION_LIBERAR = 'liberar'
DECISION_MANTENER_FALTA = 'mantener_falta'
DECISION_ACEPTAR = 'aceptar'
DECISION_RECHAZAR = 'rechazar'

ESTADO_DISPUTA = 'Disputa'

_ACCIONES_DESVIO = frozenset({
    ACCION_LIBERAR_PLAZA,
    ACCION_MANTENER_FALTA,
    ACCION_ACEPTAR_ENTRADA,
    ACCION_RECHAZAR_ENTRADA,
    ACCION_CONFIRMAR_DESVIO,
    ACCION_RECHAZAR_DESVIO,
})

_ROLES_OFICINA = frozenset({ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH})


class DesvioFichajeError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def es_desvio_plan_vs_real(registro):
    """Conflicto abierto con obra planificada distinta de la fichada."""
    if not registro:
        return False
    if (registro.estado or '') != 'Conflicto':
        return False
    plan = registro.obra_planificada_id
    real = registro.obra_real_id
    return bool(plan and real and plan != real)


def es_desvio_disputa(registro):
    if not registro or (registro.estado or '') != ESTADO_DISPUTA:
        return False
    plan = registro.obra_planificada_id
    real = registro.obra_real_id
    return bool(plan and real and plan != real)


def es_desvio_accionable(registro):
    """Conflicto o disputa (oficina puede forzar cierre)."""
    return es_desvio_plan_vs_real(registro) or es_desvio_disputa(registro)


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


def decision_plan(registro):
    return getattr(registro, 'desvio_decision_plan', None) or None


def decision_real(registro):
    return getattr(registro, 'desvio_decision_real', None) or None


def obras_del_jefe(user):
    if not user or getattr(user, 'role', None) != ROLE_JEFE:
        return []
    return [o.id for o in Obra.query.filter_by(jefe_obra_id=user.id).all()]


def _es_oficina(user):
    return getattr(user, 'role', None) in _ROLES_OFICINA


def lados_visibles_para(registro, user):
    if not es_desvio_accionable(registro) or not user:
        return set()
    if _es_oficina(user):
        return {'plan', 'real'}
    if getattr(user, 'role', None) != ROLE_JEFE:
        return set()
    mias = set(obras_del_jefe(user))
    lados = set()
    if registro.obra_planificada_id in mias:
        lados.add('plan')
    if registro.obra_real_id in mias:
        lados.add('real')
    return lados


def lados_pendientes_para(registro, user):
    if es_desvio_disputa(registro):
        # Los jefes ya hablaron; solo oficina actúa.
        return {'plan', 'real'} if _es_oficina(user) else set()
    visibles = lados_visibles_para(registro, user)
    pendientes = set()
    if 'plan' in visibles and not desvio_ack_plan_hecho(registro):
        pendientes.add('plan')
    if 'real' in visibles and not desvio_ack_real_hecho(registro):
        pendientes.add('real')
    return pendientes


def debe_mostrar_pendiente_a(registro, user):
    if es_desvio_disputa(registro):
        return _es_oficina(user)
    if not es_desvio_plan_vs_real(registro):
        return True
    if _es_oficina(user):
        return not desvio_completo(registro)
    return bool(lados_pendientes_para(registro, user))


def _marcar_decision_plan(registro, user, decision):
    registro.desvio_decision_plan = decision
    registro.desvio_ack_plan_at = utc_now()
    registro.desvio_ack_plan_by_id = user.id if user else None


def _marcar_decision_real(registro, user, decision):
    registro.desvio_decision_real = decision
    registro.desvio_ack_real_at = utc_now()
    registro.desvio_ack_real_by_id = user.id if user else None


def _liberar_plaza_plan(registro, actor):
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


def _asegurar_asignacion_plan(registro, actor):
    from app.models import Asignacion

    plan_id = registro.obra_planificada_id
    if not plan_id:
        return
    existe = Asignacion.query.filter_by(
        user_id=registro.user_id,
        fecha=registro.fecha,
        obra_id=plan_id,
    ).first()
    if existe:
        return
    CoreAssignmentService.asignar(
        registro.user_id,
        plan_id,
        registro.fecha,
        actor.id if actor else None,
        'Desvío fichaje: mantener falta en plan',
    )


def _quitar_asignacion_real(registro, actor):
    from app.models import Asignacion

    real_id = registro.obra_real_id
    if not real_id:
        return
    asignaciones = Asignacion.query.filter_by(
        user_id=registro.user_id,
        fecha=registro.fecha,
        obra_id=real_id,
    ).all()
    for asig in asignaciones:
        CoreAssignmentService.desasignar(
            asig.user_id,
            asig.obra_id,
            asig.fecha,
            actor.id if actor else None,
            'Desvío fichaje: rechazar entrada',
        )


def _labels_obras(registro):
    plan_lbl = CoreAssignmentService.format_obra_label(
        Obra.query.get(registro.obra_planificada_id)
    ) if registro.obra_planificada_id else '—'
    real_lbl = CoreAssignmentService.format_obra_label(
        Obra.query.get(registro.obra_real_id)
    ) if registro.obra_real_id else '—'
    return plan_lbl, real_lbl


def _aplicar_matriz(registro, actor):
    """Con ambos lados decididos: mueve, mantiene falta o marca Disputa."""
    if not desvio_completo(registro):
        return {'resolved': False, 'disputa': False}

    plan_d = decision_plan(registro)
    real_d = decision_real(registro)
    plan_lbl, real_lbl = _labels_obras(registro)
    registro.estado_antes_resolucion = (
        registro.estado_antes_resolucion
        or ('Disputa' if es_desvio_disputa(registro) else 'Conflicto')
    )
    registro.resuelto_por_id = actor.id if actor else registro.resuelto_por_id
    registro.fecha_auditoria = utc_now()

    if plan_d == DECISION_LIBERAR and real_d == DECISION_ACEPTAR:
        _liberar_plaza_plan(registro, actor)
        _aceptar_entrada_real(registro, actor)
        registro.estado = 'Resuelto_Movido'
        registro.notas_resolucion = (
            f"Desvío cerrado: liberada plaza en '{plan_lbl}' "
            f"y aceptada entrada en '{real_lbl}'."
        )
        return {'resolved': True, 'disputa': False}

    if plan_d == DECISION_MANTENER_FALTA and real_d == DECISION_RECHAZAR:
        _asegurar_asignacion_plan(registro, actor)
        _quitar_asignacion_real(registro, actor)
        registro.estado = 'Resuelto_Ausencia'
        registro.notas_resolucion = (
            f"Desvío rechazado: se mantiene falta en '{plan_lbl}' "
            f"y no se acepta el fichaje en '{real_lbl}'."
        )
        return {'resolved': True, 'disputa': False}

    # Cruce → oficina
    registro.estado = ESTADO_DISPUTA
    registro.notas_resolucion = (
        f"Disputa entre jefes (plan={plan_d}, fichaje={real_d}): "
        f"'{plan_lbl}' vs '{real_lbl}'. Requiere oficina."
    )
    return {'resolved': False, 'disputa': True}


def _autorizar_accion(registro, user, accion):
    if es_desvio_disputa(registro):
        if not _es_oficina(user):
            raise DesvioFichajeError(
                'Este desvío está en disputa; solo oficina puede cerrarlo.',
                status=403,
            )
        if accion not in (ACCION_CONFIRMAR_DESVIO, ACCION_RECHAZAR_DESVIO):
            raise DesvioFichajeError(
                'En disputa usa Confirmar o Mantener.',
                status=400,
            )
        return

    if not es_desvio_plan_vs_real(registro):
        raise DesvioFichajeError('Este registro no es un desvío plan→ficha.', status=400)

    pendientes = lados_pendientes_para(registro, user)
    gestiona_ambos = lados_visibles_para(registro, user) == {'plan', 'real'} or _es_oficina(user)

    if accion in (ACCION_CONFIRMAR_DESVIO, ACCION_RECHAZAR_DESVIO):
        if gestiona_ambos or _es_oficina(user):
            return
        raise DesvioFichajeError(
            'Solo puedes cerrar el desvío completo si gestionas ambas obras.',
            status=403,
        )

    if accion in (ACCION_LIBERAR_PLAZA, ACCION_MANTENER_FALTA):
        if pendientes == {'plan', 'real'}:
            raise DesvioFichajeError(
                'Usa Confirmar o Mantener para cerrar el desvío completo.',
                status=400,
            )
        if 'plan' not in pendientes:
            raise DesvioFichajeError('No te corresponde decidir el lado del plan.', status=403)
        return

    if accion in (ACCION_ACEPTAR_ENTRADA, ACCION_RECHAZAR_ENTRADA):
        if pendientes == {'plan', 'real'}:
            raise DesvioFichajeError(
                'Usa Confirmar o Mantener para cerrar el desvío completo.',
                status=400,
            )
        if 'real' not in pendientes:
            raise DesvioFichajeError('No te corresponde decidir el lado del fichaje.', status=403)
        return

    raise DesvioFichajeError('Acción de desvío no reconocida.', status=400)


def aplicar_accion_desvio(registro, accion, user):
    """
    Aplica decisión de un lado o cierre completo.
    Devuelve dict: resolved, disputa, dismiss_for_viewer, message, ...
    """
    if accion not in _ACCIONES_DESVIO:
        raise DesvioFichajeError('Acción de desvío no reconocida.', status=400)
    if not es_desvio_accionable(registro):
        raise DesvioFichajeError('Este registro no es un desvío plan→ficha.', status=400)

    _autorizar_accion(registro, user, accion)

    if accion == ACCION_LIBERAR_PLAZA:
        _marcar_decision_plan(registro, user, DECISION_LIBERAR)
        msg = 'Registrado: liberar plaza (pendiente del otro jefe).'
    elif accion == ACCION_MANTENER_FALTA:
        _marcar_decision_plan(registro, user, DECISION_MANTENER_FALTA)
        msg = 'Registrado: mantener falta en la obra del plan.'
    elif accion == ACCION_ACEPTAR_ENTRADA:
        _marcar_decision_real(registro, user, DECISION_ACEPTAR)
        msg = 'Registrado: aceptar entrada (pendiente del otro jefe).'
    elif accion == ACCION_RECHAZAR_ENTRADA:
        _marcar_decision_real(registro, user, DECISION_RECHAZAR)
        msg = 'Registrado: rechazar entrada en la obra del fichaje.'
    elif accion == ACCION_CONFIRMAR_DESVIO:
        _marcar_decision_plan(registro, user, DECISION_LIBERAR)
        _marcar_decision_real(registro, user, DECISION_ACEPTAR)
        msg = 'Desvío confirmado en ambas obras.'
    else:  # rechazar_desvio
        _marcar_decision_plan(registro, user, DECISION_MANTENER_FALTA)
        _marcar_decision_real(registro, user, DECISION_RECHAZAR)
        msg = 'Desvío rechazado: se mantiene la falta del plan.'

    cierre = _aplicar_matriz(registro, user)
    if cierre.get('resolved'):
        msg = registro.notas_resolucion or msg
    elif cierre.get('disputa'):
        msg = registro.notas_resolucion or 'Desvío en disputa: requiere oficina.'

    dismiss = (
        cierre.get('resolved')
        or cierre.get('disputa')
        or not lados_pendientes_para(registro, user)
    )
    return {
        'resolved': bool(cierre.get('resolved')),
        'disputa': bool(cierre.get('disputa')),
        'dismiss_for_viewer': dismiss,
        'message': msg,
        'ack_plan': desvio_ack_plan_hecho(registro),
        'ack_real': desvio_ack_real_hecho(registro),
        'decision_plan': decision_plan(registro),
        'decision_real': decision_real(registro),
        'estado': registro.estado,
    }


def botones_desvio_para(registro, user):
    """Botones según rol: a favor + en contra, o cierre completo."""
    if not es_desvio_accionable(registro) or not user:
        return []
    pendientes = lados_pendientes_para(registro, user)
    if not pendientes:
        return []

    gestiona_ambos = (
        lados_visibles_para(registro, user) == {'plan', 'real'}
        or _es_oficina(user)
    )

    if pendientes == {'plan', 'real'} and gestiona_ambos:
        return [
            {
                'accion': ACCION_CONFIRMAR_DESVIO,
                'label': 'Confirmar',
                'title': 'Valida el desvío: libera la plaza del plan y acepta la entrada',
                'style': 'primary',
            },
            {
                'accion': ACCION_RECHAZAR_DESVIO,
                'label': 'Mantener',
                'title': 'Rechaza el desvío: mantiene la falta en el plan y no acepta el fichaje',
                'style': 'warning',
            },
        ]

    if pendientes == {'plan'}:
        return [
            {
                'accion': ACCION_LIBERAR_PLAZA,
                'label': 'Liberar',
                'title': 'A favor: no viene a tu obra; se liberará su plaza al cerrar el caso',
                'style': 'danger',
            },
            {
                'accion': ACCION_MANTENER_FALTA,
                'label': 'Falta',
                'title': 'En contra: debía venir a tu obra; se mantiene la falta',
                'style': 'warning',
            },
        ]

    if pendientes == {'real'}:
        return [
            {
                'accion': ACCION_ACEPTAR_ENTRADA,
                'label': 'Aceptar',
                'title': 'A favor: acepta en tu obra a quien venía de otra',
                'style': 'primary',
            },
            {
                'accion': ACCION_RECHAZAR_ENTRADA,
                'label': 'Rechazar',
                'title': 'En contra: ha fichado aquí pero no lo das por bueno en tu obra',
                'style': 'danger',
            },
        ]

    return []


def contexto_desvio_para_plantilla(registro, user):
    if not es_desvio_accionable(registro):
        return None
    jp, jr = jefes_desvio(registro)
    lados = lados_visibles_para(registro, user)
    # Oficina ve ambas; no marcamos «Tuya» (no es jefe de obra).
    lados_mia = set() if _es_oficina(user) else lados
    return {
        'es_desvio': True,
        'disputa': es_desvio_disputa(registro),
        'mismo_jefe': bool(jp and jr and jp == jr),
        'ack_plan': desvio_ack_plan_hecho(registro),
        'ack_real': desvio_ack_real_hecho(registro),
        'decision_plan': decision_plan(registro),
        'decision_real': decision_real(registro),
        'botones': botones_desvio_para(registro, user),
        'pendientes_viewer': sorted(lados_pendientes_para(registro, user)),
        'lados_viewer': sorted(lados_mia),
        'mia_plan': 'plan' in lados_mia,
        'mia_real': 'real' in lados_mia,
    }


def enriquecer_pendientes_desvio(pendientes, user):
    out = []
    for reg in pendientes:
        if es_desvio_accionable(reg) and not debe_mostrar_pendiente_a(reg, user):
            continue
        reg.desvio_ui = contexto_desvio_para_plantilla(reg, user)
        out.append(reg)
    return out


def notificar_desvio_inmediato(registro):
    if not es_desvio_plan_vs_real(registro):
        return
    try:
        from app.services.email_service import notificar_desvio_fichaje
        notificar_desvio_fichaje(registro)
    except Exception:
        logger.exception(
            'No se pudo notificar desvío fichaje id=%s', getattr(registro, 'id', None)
        )


def limpiar_acks_desvio(registro):
    registro.desvio_ack_plan_at = None
    registro.desvio_ack_plan_by_id = None
    registro.desvio_ack_real_at = None
    registro.desvio_ack_real_by_id = None
    registro.desvio_decision_plan = None
    registro.desvio_decision_real = None
