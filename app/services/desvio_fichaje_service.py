"""Desvío de fichaje: planificado en X, ficha en Y.

Contrato de producto:
- Un desvío por cada obra de plan afectada (multi-plan → N filas).
- El fichaje en Y es único: aceptar propaga a todos los hermanos
  (mismo user/fecha/obra_real).
- El fichaje físico no se «rechaza»; solo se decide el cuadrante.
- Jefe de X (plan): Desasignar | Confirmar falta (solo cierra el lado plan;
  el fichaje en Y sigue pendiente hasta Aceptar).
- Jefe de Y (ficha): Aceptar (integrar al cuadrante).
- Mismo jefe / oficina: Desasignar y aceptar | Falta+aceptar (cierre completo).

Matriz:
- Liberar + Aceptar     → mueve X→Y (Resuelto_Movido)
- Falta + Aceptar       → Falta en X (sigue planificado), Y aceptada
"""
from __future__ import annotations

import json
import logging

from app.models import Obra, ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH
from app.services.core_assignment_service import CoreAssignmentService
from app.utils.timezone_utils import utc_now

logger = logging.getLogger(__name__)

# Obras «comodín» (p. ej. Varios): el fichaje real no entra en desvío/ausencia/
# paracaidista; se revisa en la sección Comodín hasta corrección RRHH/Odoo.
CONFIG_OBRAS_COMODIN = 'fichaje_obras_comodin'


def parse_obras_comodin_ids(raw) -> set:
    """Parsea JSON `[1,2]` o lista CSV a set de int."""
    if raw is None or raw == '':
        return set()
    if isinstance(raw, (set, frozenset, list, tuple)):
        out = set()
        for x in raw:
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                continue
        return out
    text = str(raw).strip()
    if not text:
        return set()
    if text.startswith('['):
        try:
            data = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            data = None
        if isinstance(data, list):
            return parse_obras_comodin_ids(data)
    out = set()
    for part in text.replace(';', ',').split(','):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def obras_comodin_ids() -> set:
    """IDs de obra comodín del tenant actual (vacío = feature apagada)."""
    try:
        from app.services.config_service import get_tenant_config
        return parse_obras_comodin_ids(get_tenant_config(CONFIG_OBRAS_COMODIN, default=''))
    except Exception:
        logger.debug('obras_comodin_ids: sin config de tenant', exc_info=True)
        return set()


def es_obra_comodin(obra_id, comodin_ids=None) -> bool:
    if not obra_id:
        return False
    ids = obras_comodin_ids() if comodin_ids is None else parse_obras_comodin_ids(comodin_ids)
    try:
        return int(obra_id) in ids
    except (TypeError, ValueError):
        return False


def serialize_obras_comodin_ids(ids) -> str:
    cleaned = sorted(parse_obras_comodin_ids(ids))
    return json.dumps(cleaned)


def _comodin_nombre_codigo_sets(comodin_ids) -> tuple:
    """Nombres/códigos de las obras comodín (match por etiqueta si hay IDs duplicados)."""
    ids = parse_obras_comodin_ids(comodin_ids)
    names: set = set()
    codes: set = set()
    if not ids:
        return names, codes
    try:
        for o in Obra.query.filter(Obra.id.in_(ids)).all():
            n = (getattr(o, 'nombre', None) or '').strip().casefold()
            c = (getattr(o, 'codigo', None) or '').strip().casefold()
            if n:
                names.add(n)
            if c:
                codes.add(c)
    except Exception:
        logger.debug('comodin nombre/codigo: sin obras', exc_info=True)
    return names, codes


def registro_es_comodin(registro, comodin_ids=None, *, _names=None, _codes=None) -> bool:
    """True si el fichaje real es en obra comodín (por id o por código/nombre)."""
    ids = obras_comodin_ids() if comodin_ids is None else parse_obras_comodin_ids(comodin_ids)
    if not ids:
        return False
    rid = getattr(registro, 'obra_real_id', None)
    if es_obra_comodin(rid, ids):
        return True
    obra = getattr(registro, 'obra_real', None)
    if obra is None:
        return False
    if es_obra_comodin(getattr(obra, 'id', None), ids):
        return True
    if _names is None or _codes is None:
        _names, _codes = _comodin_nombre_codigo_sets(ids)
    n = (getattr(obra, 'nombre', None) or '').strip().casefold()
    c = (getattr(obra, 'codigo', None) or '').strip().casefold()
    if n and n in _names:
        return True
    if c and c in _codes:
        return True
    return False

ACCION_LIBERAR_PLAZA = 'liberar_plaza'
ACCION_MANTENER_FALTA = 'mantener_falta'
ACCION_ACEPTAR_ENTRADA = 'aceptar_entrada'
ACCION_RECHAZAR_ENTRADA = 'rechazar_entrada'  # legado; ya no se ofrece en UI
ACCION_CONFIRMAR_DESVIO = 'confirmar_desvio'
ACCION_RECHAZAR_DESVIO = 'rechazar_desvio'  # legado; ahora = falta en plan + aceptar Y

DECISION_LIBERAR = 'liberar'
DECISION_MANTENER_FALTA = 'mantener_falta'
DECISION_ACEPTAR = 'aceptar'
DECISION_RECHAZAR = 'rechazar'

ESTADO_DISPUTA = 'Disputa'
ESTADO_FALTA = 'Falta'

_ESTADOS_ABIERTOS_PLAN = frozenset({
    'Sin_Registro', 'Ausencia', 'Conflicto', 'Disputa', 'Cerrado_Multiobra', ESTADO_FALTA,
})

_ACCIONES_DESVIO = frozenset({
    ACCION_LIBERAR_PLAZA,
    ACCION_MANTENER_FALTA,
    ACCION_ACEPTAR_ENTRADA,
    ACCION_RECHAZAR_ENTRADA,
    ACCION_CONFIRMAR_DESVIO,
    ACCION_RECHAZAR_DESVIO,
})

_ROLES_OFICINA_LEGACY = frozenset({ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH})


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
    """
    Oficina = ve/actúa en ambos lados del desvío (como admin).

    Se decide por alcance de auditoría «todos», no por rol hardcodeado.
    Así un Director RRHH custom con alcance all ve lo mismo que admin.
    """
    if not user:
        return False
    if getattr(user, 'role', None) == ROLE_ADMIN:
        return True
    try:
        from app.services.panel_scope_service import (
            PANEL_AUDITORIA_FICHAJES,
            user_panel_mode,
        )
        return user_panel_mode(user, PANEL_AUDITORIA_FICHAJES) == 'office'
    except Exception:
        return getattr(user, 'role', None) in _ROLES_OFICINA_LEGACY


def _obras_ids_custodia_auditoria(user):
    """Obras del alcance de custodia (jefe propio o jefes concretos)."""
    from app.services.panel_scope_service import (
        PANEL_AUDITORIA_FICHAJES,
        user_custody_jefe_ids,
        user_panel_mode,
    )
    if user_panel_mode(user, PANEL_AUDITORIA_FICHAJES) != 'custody':
        return set()
    jefe_ids = user_custody_jefe_ids(user, PANEL_AUDITORIA_FICHAJES)
    if not jefe_ids:
        return set()
    return {
        o.id
        for o in Obra.query.filter(Obra.jefe_obra_id.in_(jefe_ids)).all()
    }


def lados_visibles_para(registro, user):
    if not es_desvio_accionable(registro) or not user:
        return set()
    if _es_oficina(user):
        return {'plan', 'real'}
    mias = _obras_ids_custodia_auditoria(user)
    if not mias and getattr(user, 'role', None) == ROLE_JEFE:
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
            detalle_extra=(
                f"Se libera la plaza en "
                f"'{CoreAssignmentService.format_obra_label(Obra.query.get(plan_id))}'."
            ),
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
        detalle_extra=(
            f"Se asigna a la obra del fichaje "
            f"'{CoreAssignmentService.format_obra_label(Obra.query.get(real_id))}'."
        ),
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
        detalle_extra=(
            f"Se conserva la plaza en '{CoreAssignmentService.format_obra_label(Obra.query.get(plan_id))}'."
        ),
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
            detalle_extra=(
                f"Se quita la asignación de la obra del fichaje "
                f"'{CoreAssignmentService.format_obra_label(Obra.query.get(real_id))}'."
            ),
        )


def _labels_obras(registro):
    plan_lbl = CoreAssignmentService.format_obra_label(
        Obra.query.get(registro.obra_planificada_id)
    ) if registro.obra_planificada_id else '—'
    real_lbl = CoreAssignmentService.format_obra_label(
        Obra.query.get(registro.obra_real_id)
    ) if registro.obra_real_id else '—'
    return plan_lbl, real_lbl


def _label_decision(decision: str | None) -> str:
    """Etiqueta corta para notas internas / disputa."""
    return {
        DECISION_LIBERAR: 'desasignar',
        DECISION_MANTENER_FALTA: 'confirmar falta',
        DECISION_ACEPTAR: 'aceptar entrada',
        DECISION_RECHAZAR: 'rechazar entrada',
    }.get(decision or '', decision or '—')


def label_resolucion_plan(decision: str | None) -> str:
    """Texto UI del lado plan (misma semántica que los botones)."""
    return {
        DECISION_LIBERAR: 'Desasignado',
        DECISION_MANTENER_FALTA: 'Falta confirmada',
    }.get(decision or '', 'Resuelto')


def label_resolucion_real(decision: str | None) -> str:
    """Texto UI del lado fichaje."""
    return {
        DECISION_ACEPTAR: 'Aceptado',
        DECISION_RECHAZAR: 'Aceptado',
    }.get(decision or '', 'Aceptado')


def _marcar_falta_plan(registro, actor, nota=None):
    """Confirma falta real en la obra del plan (sigue planificado, estado Falta)."""
    from app.services.inercia_service import cortar_casa

    _asegurar_asignacion_plan(registro, actor)
    # Trazabilidad en cuadrante sí; fantasma al día siguiente no (no estuvo).
    if registro.user_id and registro.fecha:
        cortar_casa(registro.user_id, registro.fecha, actor.id if actor else None)
    plan_lbl, real_lbl = _labels_obras(registro)
    registro.estado_antes_resolucion = (
        registro.estado_antes_resolucion
        or ('Disputa' if es_desvio_disputa(registro) else 'Conflicto')
    )
    registro.estado = ESTADO_FALTA
    registro.resuelto_por_id = actor.id if actor else registro.resuelto_por_id
    registro.fecha_auditoria = utc_now()
    registro.notas_resolucion = nota or (
        f"Falta confirmada en '{plan_lbl}'"
        + (f" (había fichado en '{real_lbl}')." if real_lbl and real_lbl != '—' else '.')
    )
    return {'resolved': True, 'disputa': False, 'falta': True}


def _aplicar_matriz(registro, actor):
    """Con ambos lados decididos: mueve o marca falta en plan (el fichaje no se niega)."""
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
            f"Desvío cerrado: se libera la plaza en '{plan_lbl}' "
            f"y se acepta el fichaje en '{real_lbl}'. "
            f"El operario queda asignado a '{real_lbl}'."
        )
        return {'resolved': True, 'disputa': False}

    # Falta en plan + aceptar (o legado rechazar): el fichaje físico no se borra.
    if plan_d == DECISION_MANTENER_FALTA and real_d in (DECISION_ACEPTAR, DECISION_RECHAZAR):
        _aceptar_entrada_real(registro, actor)
        return _marcar_falta_plan(
            registro,
            actor,
            nota=(
                f"Falta confirmada en '{plan_lbl}'. "
                f"El fichaje en '{real_lbl}' queda registrado."
            ),
        )

    # Cruce raro (liberar + rechazar legado) → oficina
    registro.estado = ESTADO_DISPUTA
    registro.notas_resolucion = (
        f"Disputa entre jefes: en el plan ('{plan_lbl}') se decidió "
        f"«{_label_decision(plan_d)}» y en el fichaje ('{real_lbl}') se decidió "
        f"«{_label_decision(real_d)}». Las decisiones no cuadran; requiere oficina."
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

    gestiona_ambos = lados_visibles_para(registro, user) == {'plan', 'real'} or _es_oficina(user)

    if accion in (ACCION_CONFIRMAR_DESVIO, ACCION_RECHAZAR_DESVIO):
        if gestiona_ambos or _es_oficina(user):
            return
        raise DesvioFichajeError(
            'Solo puedes cerrar el desvío completo si gestionas ambas obras.',
            status=403,
        )

    visibles = lados_visibles_para(registro, user)
    if accion in (ACCION_LIBERAR_PLAZA, ACCION_MANTENER_FALTA):
        if 'plan' not in visibles and not _es_oficina(user):
            raise DesvioFichajeError('No te corresponde decidir el lado del plan.', status=403)
        if desvio_ack_plan_hecho(registro):
            raise DesvioFichajeError('El lado del plan ya está decidido.', status=400)
        return

    if accion in (ACCION_ACEPTAR_ENTRADA, ACCION_RECHAZAR_ENTRADA):
        if 'real' not in visibles and not _es_oficina(user):
            raise DesvioFichajeError('No te corresponde decidir el lado del fichaje.', status=403)
        if desvio_ack_real_hecho(registro):
            raise DesvioFichajeError('El lado del fichaje ya está decidido.', status=400)
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
    plan_lbl, real_lbl = _labels_obras(registro)

    afectados_ids = {registro.id}

    if accion == ACCION_LIBERAR_PLAZA:
        # Desasignar ya (como en Ausencias): no espera al otro lado.
        _marcar_decision_plan(registro, user, DECISION_LIBERAR)
        _liberar_plaza_plan(registro, user)
        if desvio_ack_real_hecho(registro):
            _aceptar_entrada_real(registro, user)
            registro.estado_antes_resolucion = registro.estado_antes_resolucion or 'Conflicto'
            registro.estado = 'Resuelto_Movido'
            registro.resuelto_por_id = user.id if user else registro.resuelto_por_id
            registro.fecha_auditoria = utc_now()
            registro.notas_resolucion = (
                f"Desasignado de '{plan_lbl}' y fichaje aceptado en '{real_lbl}'."
            )
            return {
                'resolved': True,
                'disputa': False,
                'dismiss_for_viewer': True,
                'message': registro.notas_resolucion,
                'ack_plan': True,
                'ack_real': True,
                'decision_plan': decision_plan(registro),
                'decision_real': decision_real(registro),
                'estado': registro.estado,
                'afectados_ids': list(afectados_ids),
            }
        msg = (
            f"Desasignado de '{plan_lbl}'. "
            f"Pendiente aceptar el fichaje en '{real_lbl}'."
        )
    elif accion == ACCION_MANTENER_FALTA:
        # Confirmar falta en el plan: solo cierra el lado plan.
        # El fichaje en Y sigue pendiente (igual que Desasignar).
        from app.services.inercia_service import cortar_casa
        _marcar_decision_plan(registro, user, DECISION_MANTENER_FALTA)
        _asegurar_asignacion_plan(registro, user)
        if registro.user_id and registro.fecha:
            cortar_casa(registro.user_id, registro.fecha, user.id if user else None)
        if desvio_ack_real_hecho(registro):
            _aceptar_entrada_real(registro, user)
            cierre = _marcar_falta_plan(
                registro,
                user,
                nota=(
                    f"Falta confirmada en '{plan_lbl}'. "
                    f"El fichaje en '{real_lbl}' queda registrado."
                ),
            )
            return {
                'resolved': True,
                'disputa': False,
                'dismiss_for_viewer': True,
                'message': registro.notas_resolucion,
                'ack_plan': True,
                'ack_real': True,
                'decision_plan': decision_plan(registro),
                'decision_real': decision_real(registro),
                'estado': registro.estado,
                'afectados_ids': list(afectados_ids),
                'falta': True,
            }
        msg = (
            f"Falta confirmada en '{plan_lbl}'. "
            f"Pendiente aceptar el fichaje en '{real_lbl}'."
        )
    elif accion == ACCION_ACEPTAR_ENTRADA:
        _marcar_decision_real(registro, user, DECISION_ACEPTAR)
        _aceptar_entrada_real(registro, user)
        afectados_ids |= _propagar_ack_real_hermanos(registro, user)
        msg = (
            f"Fichaje aceptado en '{real_lbl}' "
            f"(vale para todos los desvíos de este fichaje). "
            f"Pendiente desasignar o confirmar falta en '{plan_lbl}'."
        )
    elif accion == ACCION_RECHAZAR_ENTRADA:
        # Legado: el fichaje no se niega; se trata como aceptar sin integrar plaza.
        _marcar_decision_real(registro, user, DECISION_ACEPTAR)
        afectados_ids |= _propagar_ack_real_hermanos(registro, user)
        msg = (
            f"Fichaje en '{real_lbl}' registrado (ya no se puede rechazar). "
            f"Pendiente decidir la plaza en '{plan_lbl}'."
        )
    elif accion == ACCION_CONFIRMAR_DESVIO:
        _marcar_decision_plan(registro, user, DECISION_LIBERAR)
        _marcar_decision_real(registro, user, DECISION_ACEPTAR)
        afectados_ids |= _propagar_ack_real_hermanos(registro, user)
        msg = (
            f"Desvío confirmado: liberar '{plan_lbl}' y aceptar fichaje en '{real_lbl}'."
        )
    else:  # rechazar_desvio → falta en plan + aceptar Y (sin negar fichaje)
        _marcar_decision_plan(registro, user, DECISION_MANTENER_FALTA)
        _marcar_decision_real(registro, user, DECISION_ACEPTAR)
        afectados_ids |= _propagar_ack_real_hermanos(registro, user)
        msg = (
            f"Falta en '{plan_lbl}' y fichaje aceptado en '{real_lbl}'."
        )

    cierre = _aplicar_matriz(registro, user)
    if cierre.get('resolved'):
        msg = registro.notas_resolucion or msg
    elif cierre.get('disputa'):
        msg = registro.notas_resolucion or (
            f"Disputa entre jefes sobre '{plan_lbl}' vs '{real_lbl}': requiere oficina."
        )

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
        'afectados_ids': list(afectados_ids),
    }


def botones_desvio_para(registro, user):
    """
    Botones del desvío expandido = mismos de Ausencia + Sin planificar.

    Plan (ausencia / pendiente): Desasignar | Confirmar falta
    Real (sin planificar): Aceptar
    """
    if not es_desvio_accionable(registro) or not user:
        return []
    pendientes = lados_pendientes_para(registro, user)
    if not pendientes:
        return []

    gestiona_ambos = (
        lados_visibles_para(registro, user) == {'plan', 'real'}
        or _es_oficina(user)
    )

    botones = []
    if 'plan' in pendientes:
        botones.extend([
            {
                'accion': ACCION_LIBERAR_PLAZA,
                'label': 'Desasignar',
                'title': 'Quita la planificación de esta obra (estaba mal / ya no aplica)',
                'style': 'warning',
                'lado': 'plan',
            },
            {
                'accion': ACCION_MANTENER_FALTA,
                'label': 'Confirmar falta',
                'title': 'Falta real: sigue planificado con marca de falta en el calendario',
                'style': 'danger',
                'lado': 'plan',
            },
        ])
    if 'real' in pendientes:
        botones.append({
            'accion': ACCION_ACEPTAR_ENTRADA,
            'label': 'Aceptar',
            'title': 'Asigna oficialmente a la obra del fichaje',
            'style': 'primary',
            'lado': 'real',
        })
    if pendientes == {'plan', 'real'} and gestiona_ambos:
        botones.insert(0, {
            'accion': ACCION_CONFIRMAR_DESVIO,
            'label': 'Desasignar y aceptar',
            'title': 'Atajo: quita el plan y acepta el fichaje de una vez',
            'style': 'primary',
            'lado': 'ambos',
        })
    return botones


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
        'ack_plan_label': (
            label_resolucion_plan(decision_plan(registro))
            if desvio_ack_plan_hecho(registro) else None
        ),
        'ack_real_label': (
            label_resolucion_real(decision_real(registro))
            if desvio_ack_real_hecho(registro) else None
        ),
        'botones': botones_desvio_para(registro, user),
        'pendientes_viewer': sorted(lados_pendientes_para(registro, user)),
        'lados_viewer': sorted(lados_mia),
        'mia_plan': 'plan' in lados_mia,
        'mia_real': 'real' in lados_mia,
    }


def _nombre_usuario(user):
    if not user:
        return None
    return f"{(user.name or '').strip()} {(user.lastname or '').strip()}".strip() or None


def _meta_desvio_batch(registros):
    """Quién planificó / quién aceptó, para el panel expandido. Nunca debe tumbar la UI."""
    from datetime import timedelta

    from app.models import SystemLog, User
    from app.services.core_assignment_service import CoreAssignmentService
    from app.services.log_coverage import planif_detail_covers_day

    regs = [r for r in (registros or []) if r and r.user_id and r.fecha]
    if not regs:
        return {}

    user_ids = {r.user_id for r in regs}
    jefe_ids = set()
    ack_ids = set()
    obra_ids = set()
    for r in regs:
        if r.obra_planificada_id:
            obra_ids.add(r.obra_planificada_id)
        if r.obra_real_id:
            obra_ids.add(r.obra_real_id)
        if getattr(r, 'desvio_ack_plan_by_id', None):
            ack_ids.add(r.desvio_ack_plan_by_id)
        if getattr(r, 'desvio_ack_real_by_id', None):
            ack_ids.add(r.desvio_ack_real_by_id)

    obras = {
        o.id: o for o in Obra.query.filter(Obra.id.in_(obra_ids)).all()
    } if obra_ids else {}
    for o in obras.values():
        if o.jefe_obra_id:
            jefe_ids.add(o.jefe_obra_id)

    fechas = {r.fecha for r in regs}
    min_f, max_f = min(fechas), max(fechas)
    logs = (
        SystemLog.query.filter(
            SystemLog.category == 'planificacion',
            SystemLog.target_user_id.in_(user_ids),
            SystemLog.target_date.isnot(None),
            SystemLog.target_date <= max_f,
            SystemLog.target_date >= (min_f - timedelta(days=400)),
        )
        .order_by(SystemLog.timestamp.desc())
        .all()
    )
    autor_ids = {lg.user_id for lg in logs if lg.user_id}
    need_users = user_ids | jefe_ids | ack_ids | autor_ids
    users = {
        u.id: u for u in User.query.filter(User.id.in_(need_users)).all()
    } if need_users else {}

    planif_por_clave = {}
    for lg in logs:
        detail = lg.detail or ''
        if 'Asignado' not in detail or not lg.target_user_id:
            continue
        for r in regs:
            if r.user_id != lg.target_user_id:
                continue
            if not planif_detail_covers_day(detail, r.fecha):
                continue
            oid = r.obra_planificada_id
            if not oid:
                continue
            obra = obras.get(oid)
            if not obra:
                continue
            label = CoreAssignmentService.format_obra_label(obra)
            codigo = (obra.codigo or '').strip()
            nombre = (obra.nombre or '').strip()
            if not (
                (label and label in detail)
                or (codigo and codigo in detail)
                or (nombre and nombre in detail)
            ):
                continue
            key = (r.user_id, r.fecha, oid)
            if key not in planif_por_clave:
                planif_por_clave[key] = lg

    out = {}
    for r in regs:
        obra_plan = obras.get(r.obra_planificada_id) if r.obra_planificada_id else None
        planif_log = planif_por_clave.get(
            (r.user_id, r.fecha, r.obra_planificada_id)
        ) if r.obra_planificada_id else None
        planif_autor = users.get(planif_log.user_id) if planif_log and planif_log.user_id else None
        jefe_plan = (
            users.get(obra_plan.jefe_obra_id)
            if obra_plan and obra_plan.jefe_obra_id else None
        )
        ack_plan_u = users.get(getattr(r, 'desvio_ack_plan_by_id', None))
        ack_real_u = users.get(getattr(r, 'desvio_ack_real_by_id', None))

        out[r.id] = {
            'planificado_por': _nombre_usuario(planif_autor) or _nombre_usuario(jefe_plan),
            'planificado_por_es_jefe': bool(not planif_autor and jefe_plan),
            'ack_plan_por': _nombre_usuario(ack_plan_u),
            'ack_real_por': _nombre_usuario(ack_real_u),
        }
    return out


def enriquecer_pendientes_desvio(pendientes, user):
    # Meta es opcional: si falla, la UI de desvío (P/F + botones) sigue intacta.
    meta_map = {}
    try:
        meta_map = _meta_desvio_batch(
            [r for r in pendientes if es_desvio_accionable(r)]
        )
    except Exception:
        logger.exception('meta desvío (planificador/aceptador) falló; UI básica OK')

    out = []
    for reg in pendientes:
        if es_desvio_accionable(reg) and not debe_mostrar_pendiente_a(reg, user):
            continue
        ctx = contexto_desvio_para_plantilla(reg, user)
        if ctx and reg.id in meta_map:
            ctx.update(meta_map[reg.id])
        reg.desvio_ui = ctx
        out.append(reg)
    return out


class DesvioEspejoView:
    """
    Vista proxy de un Conflicto para listarlo también en Ausencias (lado plan)
    o Sin planificar (lado real), sin duplicar el registro en BD.
    """

    __slots__ = ('_reg', 'desvio_espejo', 'desvio_ui')

    def __init__(self, registro, lado):
        self._reg = registro
        self.desvio_espejo = lado  # 'plan' | 'real'
        self.desvio_ui = getattr(registro, 'desvio_ui', None)

    def __getattr__(self, name):
        return getattr(self._reg, name)


def repartir_secciones_auditoria(pendientes, comodin_ids=None):
    """
    Conflicto/Disputa → desviaciones.
    Ausencia + espejo plan de desvíos aún sin ack_plan → ausencias.
    Paracaidista + espejo real de desvíos aún sin ack_real → sin planificar.

    Si obra_real está en obras comodín del tenant → sección «comodin» (sin
    espejos en ausencias/paracaidistas ni fila en desviaciones).

    Si un lado del desvío ya está resuelto (ack), no se proyecta en Ausencias /
    Sin planificar: esa decisión ya está tomada; el desvío sigue arriba hasta
    cerrar el otro lado (el panel resuelto se ve en verde ahí).
    """
    ids_comodin = (
        obras_comodin_ids() if comodin_ids is None else parse_obras_comodin_ids(comodin_ids)
    )
    names_comodin, codes_comodin = _comodin_nombre_codigo_sets(ids_comodin)
    conflictos = []
    ausencias = []
    paracaidistas = []
    comodin = []
    for r in pendientes or []:
        if registro_es_comodin(
            r, ids_comodin, _names=names_comodin, _codes=codes_comodin,
        ):
            comodin.append(r)
            continue
        if r.estado in ('Conflicto', 'Disputa'):
            conflictos.append(r)
            ui = getattr(r, 'desvio_ui', None) or {}
            if ui.get('es_desvio'):
                if r.obra_planificada_id and not ui.get('ack_plan'):
                    ausencias.append(DesvioEspejoView(r, 'plan'))
                if r.obra_real_id and not ui.get('ack_real'):
                    paracaidistas.append(DesvioEspejoView(r, 'real'))
        elif r.estado == 'Ausencia':
            ausencias.append(r)
        elif r.estado == 'Paracaidista':
            paracaidistas.append(r)
    enriquecer_problema_ausencias(ausencias)
    return {
        'conflictos': conflictos,
        'ausencias': ausencias,
        'paracaidistas': paracaidistas,
        'comodin': comodin,
    }


# Problema visible en cola Ausencias (UI).
AUSENCIA_NO_HA_FICHADO = 'no_ha_fichado'          # rojo: cero marcas ese día
AUSENCIA_PENDIENTE_OBRA = 'pendiente_otra_obra'   # azul: fichó en otra del plan
AUSENCIA_FICHO_OTRA = 'ficho_otra_obra'           # ámbar: espejo de desvío plan≠real


def enriquecer_problema_ausencias(ausencias):
    """Clasifica cada fila de Ausencias para el texto/color del problema.

    - Espejo plan de Conflicto → «Fichó en otra obra» (fuera de plan).
    - Ausencia pura + marca en otra obra ese día → «Pendiente en esta obra».
    - Ausencia pura sin ninguna marca → «No ha fichado».
    """
    from app.models import RegistroFichaje

    seeds = []
    for r in ausencias or []:
        if getattr(r, 'desvio_espejo', None) == 'plan':
            # No mutar DesvioEspejoView (__slots__); la plantilla usa es_espejo.
            continue
        seeds.append(r)

    if not seeds:
        return

    user_ids = {getattr(r, 'user_id', None) for r in seeds}
    user_ids.discard(None)
    fechas = {getattr(r, 'fecha', None) for r in seeds}
    fechas.discard(None)
    hermanos_por_clave = {}
    if user_ids and fechas:
        hermanos = (
            RegistroFichaje.query
            .filter(
                RegistroFichaje.user_id.in_(user_ids),
                RegistroFichaje.fecha.in_(fechas),
                RegistroFichaje.obra_real_id.isnot(None),
            )
            .all()
        )
        for h in hermanos:
            hermanos_por_clave.setdefault((h.user_id, h.fecha), []).append(h)

    for r in seeds:
        plan_id = getattr(r, 'obra_planificada_id', None)
        clave = (getattr(r, 'user_id', None), getattr(r, 'fecha', None))
        ficho_en = None
        for h in hermanos_por_clave.get(clave, []):
            if h.id == getattr(r, 'id', None):
                continue
            if h.obra_real_id and h.obra_real_id != plan_id:
                ficho_en = getattr(h, 'obra_real', None)
                break
        if ficho_en is not None:
            r.ausencia_problema = AUSENCIA_PENDIENTE_OBRA
            r.ausencia_ficho_en = ficho_en
        else:
            r.ausencia_problema = AUSENCIA_NO_HA_FICHADO
            r.ausencia_ficho_en = None


def notificar_desvio_inmediato(registro, *, omitir_lado_real=False):
    """Desvío plan≠real → matriz ``desvio_fichaje`` (debounce/digest/inmediato/off).

    No notifica si el fichaje real es en obra comodín (cola de seguimiento, no desvío).
    """
    if registro is not None and registro_es_comodin(registro):
        return
    from app.services.email_service import notificar_desvio_fichaje
    notificar_desvio_fichaje(registro, omitir_lado_real=omitir_lado_real)


def limpiar_acks_desvio(registro):
    registro.desvio_ack_plan_at = None
    registro.desvio_ack_plan_by_id = None
    registro.desvio_ack_real_at = None
    registro.desvio_ack_real_by_id = None
    registro.desvio_decision_plan = None
    registro.desvio_decision_real = None


def hermanos_desvio_mismo_fichaje(registro):
    """Otros Conflicto/Disputa del mismo user/fecha/obra_real (fichaje compartido)."""
    from app.models import RegistroFichaje

    if not registro or not registro.obra_real_id:
        return []
    return (
        RegistroFichaje.query.filter(
            RegistroFichaje.user_id == registro.user_id,
            RegistroFichaje.fecha == registro.fecha,
            RegistroFichaje.obra_real_id == registro.obra_real_id,
            RegistroFichaje.id != registro.id,
            RegistroFichaje.estado.in_(['Conflicto', ESTADO_DISPUTA]),
        ).all()
    )


def _propagar_ack_real_hermanos(registro, user):
    """Aceptar Y una vez: copia ack_real a todos los desvíos del mismo fichaje."""
    ids = set()
    for herm in hermanos_desvio_mismo_fichaje(registro):
        if not desvio_ack_real_hecho(herm):
            _marcar_decision_real(herm, user, DECISION_ACEPTAR)
        ids.add(herm.id)
        # Si el plan ya había decidido, cierra la matriz del hermano.
        if desvio_completo(herm):
            _aplicar_matriz(herm, user)
    return ids


def materializar_conflictos_entrada(
    *,
    user_id,
    fecha,
    obra_real_id,
    obras_plan_ids,
    check_in=None,
    check_out=None,
    nota_odoo=None,
):
    """
    Crea/actualiza un Conflicto por cada obra de plan distinta de la fichada.
    Comparte obra_real y horarios. Devuelve (regs_conflicto, regs_nuevos_a_notificar).
    """
    from app import db
    from app.models import RegistroFichaje

    plan_ids = []
    seen = set()
    for oid in obras_plan_ids or []:
        if not oid or oid == obra_real_id or oid in seen:
            continue
        seen.add(oid)
        plan_ids.append(oid)

    conflictos = []
    a_notificar = []
    for plan_id in plan_ids:
        reg = RegistroFichaje.query.filter_by(
            user_id=user_id,
            fecha=fecha,
            obra_planificada_id=plan_id,
        ).first()
        if reg is None:
            reg = RegistroFichaje(
                user_id=user_id,
                fecha=fecha,
                obra_planificada_id=plan_id,
                obra_real_id=obra_real_id,
                estado='Conflicto',
                check_in=check_in,
                check_out=check_out,
                nota_odoo=nota_odoo,
            )
            db.session.add(reg)
            limpiar_acks_desvio(reg)
            conflictos.append(reg)
            a_notificar.append(reg)
            continue

        est = reg.estado or ''
        # Si ya resolvió/confirmó falta, no reabrir salvo que el fichaje gane
        # (eso lo hace resolver_plan_cumplido_por_fichaje al fichar en el plan).
        if est.startswith('Resuelto') or est == ESTADO_FALTA:
            continue
        if est in ('Correcto', 'Correcto_Automatico', 'Cambio_Tajo'):
            continue

        prev = est
        reg.obra_real_id = obra_real_id
        reg.estado = 'Conflicto'
        if check_in is not None:
            reg.check_in = check_in
        if check_out is not None:
            reg.check_out = check_out
        if nota_odoo:
            reg.nota_odoo = nota_odoo
        if prev != 'Conflicto':
            limpiar_acks_desvio(reg)
            a_notificar.append(reg)
        conflictos.append(reg)

    db.session.flush()
    return conflictos, a_notificar


def resolver_plan_cumplido_por_fichaje(user_id, fecha, obra_id, check_in=None):
    """
    Si el operario acaba fichando en una obra del plan, esa pata deja de ser
    pendiente/conflicto/falta anticipada: el fichaje gana.
    """
    from app.models import RegistroFichaje

    regs = RegistroFichaje.query.filter_by(
        user_id=user_id,
        fecha=fecha,
        obra_planificada_id=obra_id,
    ).all()
    cerrados = []
    for reg in regs:
        est = reg.estado or ''
        if est in (
            'Conflicto', ESTADO_DISPUTA, 'Ausencia', 'Sin_Registro',
            'Cerrado_Multiobra', ESTADO_FALTA, 'Retraso',
            'Resuelto_Ausencia', 'Resuelto_Falta', 'Resuelto_Ignorado',
        ):
            reg.estado = 'Correcto'
            reg.obra_real_id = obra_id
            if check_in is not None:
                reg.check_in = check_in
            reg.notas_resolucion = 'Cumplió el plan: fichó en esta obra.'
            limpiar_acks_desvio(reg)
            cerrados.append(reg)
    return cerrados


def hora_limite_entrada_str():
    """Hora de corte de entrada (HH:MM) del tenant; default 08:30."""
    from app.services.config_service import get_tenant_config
    from app.services.notification_catalog import DEFAULT_HORA_LIMITE_ENTRADA

    raw = get_tenant_config(
        'hora_limite_entrada',
        default=DEFAULT_HORA_LIMITE_ENTRADA,
    )
    return (raw or DEFAULT_HORA_LIMITE_ENTRADA).strip() or DEFAULT_HORA_LIMITE_ENTRADA


def ya_paso_hora_limite_entrada(ahora=None):
    """True si la hora local del tenant ya alcanzó la hora límite de entrada."""
    from datetime import datetime

    from app.utils.timezone_utils import now_local
    from app.services.notification_catalog import DEFAULT_HORA_LIMITE_ENTRADA

    ahora = ahora or now_local()
    hora_str = hora_limite_entrada_str()
    try:
        corte = datetime.strptime(hora_str, '%H:%M').time()
    except ValueError:
        corte = datetime.strptime(DEFAULT_HORA_LIMITE_ENTRADA, '%H:%M').time()
    return ahora.time() >= corte


# Prefijo en notas: historial lo marca como origen automático (no cola).
PREFIJO_FALTA_PARCIAL_AUTO = 'Auto: falta confirmada'


def _fichaje_real_otra_obra_ese_dia(user_id, fecha, obra_planificada_id):
    """Obra donde sí fichó ese día, distinta de la pata de plan pendiente (o None)."""
    from app.models import RegistroFichaje

    hermanos = (
        RegistroFichaje.query
        .filter(
            RegistroFichaje.user_id == user_id,
            RegistroFichaje.fecha == fecha,
            RegistroFichaje.obra_real_id.isnot(None),
        )
        .all()
    )
    for h in hermanos:
        if h.obra_real_id and h.obra_real_id != obra_planificada_id:
            return getattr(h, 'obra_real', None) or Obra.query.get(h.obra_real_id)
    return None


def _aplicar_falta_confirmada_auto(registro, ficho_en):
    """Igual que el botón «Confirmar falta», sin actor humano."""
    from app.services.inercia_service import cortar_casa

    _asegurar_asignacion_plan(registro, actor=None)
    if registro.user_id and registro.fecha:
        cortar_casa(registro.user_id, registro.fecha, autor_id=None)
    plan_lbl, _ = _labels_obras(registro)
    otra_lbl = CoreAssignmentService.format_obra_label(ficho_en) if ficho_en else 'otra obra'
    registro.estado_antes_resolucion = registro.estado_antes_resolucion or registro.estado
    registro.estado = ESTADO_FALTA
    registro.resuelto_por_id = None
    registro.fecha_auditoria = utc_now()
    registro.notas_resolucion = (
        f"{PREFIJO_FALTA_PARCIAL_AUTO}: no fichó en '{plan_lbl}' "
        f"(sí fichó en '{otra_lbl}')."
    )


def es_falta_parcial_auto(registro) -> bool:
    notas = getattr(registro, 'notas_resolucion', None) or ''
    return (
        getattr(registro, 'estado', None) == ESTADO_FALTA
        and notas.startswith(PREFIJO_FALTA_PARCIAL_AUTO)
    )


def consolidar_pendientes_a_ausencia(fecha):
    """
    Sin_Registro sin fichaje → Ausencia (aún no es Falta).

    Multi-plan (fichó en otra obra): solo si el día ya cerró (fecha < hoy)
    se autorresuelve como «Confirmar falta». En el día en curso queda
    Ausencia/Sin_Registro («aún sin fichar») por si ficha más tarde.

    Se usa al pasar la hora límite del propio día y al cerrar días anteriores.
    No toca Conflicto/Paracaidista ni filas con check_in.
    Si más tarde ficha en la obra del plan, ``resolver_plan_cumplido_por_fichaje``
    quita la ausencia.
    """
    from app.models import RegistroFichaje
    from app.services.leave_service import user_has_approved_leave
    from app.utils.timezone_utils import today_local

    dia_cerrado = fecha < today_local()
    candidatos = RegistroFichaje.query.filter(
        RegistroFichaje.fecha == fecha,
        RegistroFichaje.estado == 'Sin_Registro',
    ).all()
    n = 0
    for reg in candidatos:
        if reg.check_in or reg.obra_real_id:
            continue
        if user_has_approved_leave(reg.user_id, fecha):
            reg.estado = 'Exento_Ausencia'
            reg.notas_resolucion = 'Cubierto por ausencia planificada (no cuenta como ausencia).'
            n += 1
            continue
        ficho_en = _fichaje_real_otra_obra_ese_dia(
            reg.user_id, fecha, reg.obra_planificada_id,
        )
        if dia_cerrado and ficho_en is not None:
            _aplicar_falta_confirmada_auto(reg, ficho_en)
            n += 1
            continue
        reg.estado = 'Ausencia'
        reg.notas_resolucion = 'Pendiente de resolución: no fichó en la obra del plan ese día.'
        n += 1

    if dia_cerrado:
        n += autorresolver_ausencias_parciales(fecha)
    return n


def autorresolver_ausencias_parciales(fecha):
    """Ausencia/Sin_Registro + fichaje en otra obra → Falta. Solo días ya cerrados."""
    from app.models import RegistroFichaje
    from app.utils.timezone_utils import today_local

    if fecha >= today_local():
        return 0

    pendientes = RegistroFichaje.query.filter(
        RegistroFichaje.fecha == fecha,
        RegistroFichaje.estado.in_(('Ausencia', 'Sin_Registro')),
    ).all()
    n = 0
    for reg in pendientes:
        if reg.check_in or reg.obra_real_id:
            continue
        ficho_en = _fichaje_real_otra_obra_ese_dia(
            reg.user_id, fecha, reg.obra_planificada_id,
        )
        if ficho_en is None:
            continue
        _aplicar_falta_confirmada_auto(reg, ficho_en)
        n += 1
    return n


def reabrir_auto_faltas_parciales_dia_curso(hoy=None):
    """Deshace Falta automática multi-plan del día en curso (aún pueden fichar)."""
    from app.models import RegistroFichaje
    from app.utils.timezone_utils import today_local

    hoy = hoy or today_local()
    regs = RegistroFichaje.query.filter(
        RegistroFichaje.fecha >= hoy,
        RegistroFichaje.estado == ESTADO_FALTA,
        RegistroFichaje.notas_resolucion.like(f'{PREFIJO_FALTA_PARCIAL_AUTO}%'),
    ).all()
    for reg in regs:
        reg.estado = 'Sin_Registro'
        reg.notas_resolucion = None
        reg.fecha_auditoria = None
        reg.resuelto_por_id = None
        reg.estado_antes_resolucion = None
    return len(regs)


def autorresolver_faltas_parciales_abiertas(*, desde=None, hasta=None):
    """Backfill: cierra patas multi-plan de días YA CERRADOS (nunca el día en curso).

    Incluye Ausencia y Sin_Registro sin marca en esa obra si el mismo día
    ya hay fichaje real en otra. Devuelve cuántas resolvió.
    """
    from datetime import timedelta

    from app.models import RegistroFichaje
    from app.utils.timezone_utils import today_local

    ayer = today_local() - timedelta(days=1)
    if hasta is None or hasta > ayer:
        hasta = ayer
    if desde is not None and desde > hasta:
        return 0

    q = RegistroFichaje.query.filter(
        RegistroFichaje.estado.in_(('Ausencia', 'Sin_Registro')),
        RegistroFichaje.check_in.is_(None),
        RegistroFichaje.obra_real_id.is_(None),
    )
    if desde is not None:
        q = q.filter(RegistroFichaje.fecha >= desde)
    if hasta is not None:
        q = q.filter(RegistroFichaje.fecha <= hasta)
    pendientes = q.all()
    if not pendientes:
        return 0

    # Una sola pasada de hermanos por (user, fecha).
    user_ids = {r.user_id for r in pendientes if r.user_id}
    fechas = {r.fecha for r in pendientes if r.fecha}
    hermanos_por_clave = {}
    if user_ids and fechas:
        for h in (
            RegistroFichaje.query
            .filter(
                RegistroFichaje.user_id.in_(user_ids),
                RegistroFichaje.fecha.in_(fechas),
                RegistroFichaje.obra_real_id.isnot(None),
            )
            .all()
        ):
            hermanos_por_clave.setdefault((h.user_id, h.fecha), []).append(h)

    n = 0
    for reg in pendientes:
        clave = (reg.user_id, reg.fecha)
        ficho_en = None
        for h in hermanos_por_clave.get(clave, []):
            if h.id == reg.id:
                continue
            if h.obra_real_id and h.obra_real_id != reg.obra_planificada_id:
                ficho_en = getattr(h, 'obra_real', None) or Obra.query.get(h.obra_real_id)
                break
        if ficho_en is None:
            continue
        _aplicar_falta_confirmada_auto(reg, ficho_en)
        n += 1
    return n


# --- Odoo manda --------------------------------------------------------------
# Cuando RRHH corrige un día en Odoo (cambia/borra un fichaje), esa corrección es
# la realidad: no se pide acción a nadie, pero se conserva la trazabilidad del plan.

ESTADO_ACEPTADO_ODOO = 'Aceptado_Odoo'
PREFIJO_FALTA_AUTO = 'Falta automática'

_ESTADOS_PATA_PLAN_ABIERTA = ('Sin_Registro', 'Ausencia', 'Conflicto', ESTADO_DISPUTA, 'Cerrado_Multiobra')


def es_falta_automatica(registro) -> bool:
    return (
        getattr(registro, 'estado', None) == ESTADO_FALTA
        and (getattr(registro, 'notas_resolucion', None) or '').startswith(PREFIJO_FALTA_AUTO)
    )


def usuarios_con_correccion_odoo(fecha) -> set:
    """IDs de usuario con alguna fila `Sobreescrito_RRHH` ese día (RRHH tocó Odoo)."""
    from app.models import RegistroFichaje

    rows = (
        RegistroFichaje.query
        .with_entities(RegistroFichaje.user_id)
        .filter(
            RegistroFichaje.fecha == fecha,
            RegistroFichaje.estado == 'Sobreescrito_RRHH',
        )
        .distinct()
        .all()
    )
    return {uid for (uid,) in rows if uid}


def aplicar_correccion_odoo_dia(user_id, fecha) -> int:
    """Patas del plan que siguen abiertas en un día corregido por RRHH → Falta automática.

    Equivale a pulsar «Confirmar falta» (más aceptar el fichaje, si lo había),
    pero sin intervención. Lo ya resuelto por una persona no se toca.
    Devuelve cuántas patas se cerraron.
    """
    from app.models import RegistroFichaje
    from app.services.inercia_service import cortar_casa

    regs = RegistroFichaje.query.filter(
        RegistroFichaje.user_id == user_id,
        RegistroFichaje.fecha == fecha,
        RegistroFichaje.obra_planificada_id.isnot(None),
        RegistroFichaje.estado.in_(_ESTADOS_PATA_PLAN_ABIERTA),
    ).all()
    cerradas = 0
    for reg in regs:
        previo = reg.estado
        plan_lbl, real_lbl = _labels_obras(reg)
        if reg.obra_real_id and reg.obra_real_id != reg.obra_planificada_id:
            _marcar_decision_plan(reg, None, DECISION_MANTENER_FALTA)
            _marcar_decision_real(reg, None, DECISION_ACEPTAR)
            _aceptar_entrada_real(reg, None)
            nota = (
                f"{PREFIJO_FALTA_AUTO} en '{plan_lbl}': RRHH corrigió el día en Odoo. "
                f"El fichaje en '{real_lbl}' se acepta desde Odoo."
            )
        else:
            nota = (
                f"{PREFIJO_FALTA_AUTO} en '{plan_lbl}': RRHH corrigió el día en Odoo "
                f"y no hay fichaje en esta obra."
            )
        _asegurar_asignacion_plan(reg, None)
        cortar_casa(user_id, fecha, None)
        reg.estado_antes_resolucion = reg.estado_antes_resolucion or previo
        reg.estado = ESTADO_FALTA
        reg.resuelto_por_id = None
        reg.fecha_auditoria = utc_now()
        reg.notas_resolucion = nota
        cerradas += 1
    return cerradas
