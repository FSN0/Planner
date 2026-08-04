# app/services/fichaje_erp_ledger_service.py
#
# Vuelca al libro de eventos lo que el ERP dice de una jornada.
#
# El problema que resuelve: la sincronización se ejecuta muchas veces al día
# sobre la misma fecha, y cada pasada vuelve a leer los mismos apuntes de Odoo.
# El libro es de solo añadir, así que no se puede escribir a ciegas o cada día
# acabaría con catorce entradas repetidas. Lo que se hace es reconciliar:
# comparar lo que el ERP dice ahora con lo que el libro ya tiene, y anotar
# únicamente la diferencia.
#
# Del ERP solo se lee. Nunca se escribe nada allí: si alguien corrige un fichaje
# en Odoo, aquí queda anotada la corrección; en Odoo no se toca nada.

import logging

from app import db
from app.models import (
    EVENTO_ENTRADA,
    EVENTO_REASIGNACION_OBRA,
    EVENTO_SALIDA,
    ORIGEN_ERP,
    Obra,
    User,
)
from app.services.fichaje_ledger_service import (
    FichajeLedgerError,
    anular_evento,
    dia_procede_de_importacion,
    eventos_del_dia_por_referencia,
    registrar_evento,
)
from app.utils.timezone_utils import parse_odoo_datetime

logger = logging.getLogger(__name__)

CLAVE_REFERENCIA = 'erp_ref'


def _referencia(fichaje):
    """Identidad del apunte en el sistema de origen, estable entre pasadas."""
    externo = fichaje.get('registro_external_id')
    if not externo:
        return None
    modelo = fichaje.get('origen_modelo') or 'erp'
    return f'{modelo}:{externo}'


def _momento(valor):
    """Los segundos se recortan porque el libro guarda así los instantes."""
    instante = parse_odoo_datetime(valor)
    return instante.replace(microsecond=0) if instante else None


def _estado_deseado(fichajes, fecha_obj):
    """
    Lo que el ERP afirma ahora mismo sobre la jornada, por apunte.

    Se trabaja con los apuntes sin fusionar, a diferencia del motor de auditoría
    que los agrupa por obra: el libro debe reflejar cada marca tal cual la tiene
    el ERP, no un resumen ya interpretado.
    """
    deseado = {}

    for fichaje in fichajes:
        referencia = _referencia(fichaje)
        if not referencia:
            # Un adaptador que no da identidad no puede reconciliarse. Se avisa
            # una vez y se deja fuera: es preferible a duplicar cada pasada.
            logger.warning(
                'Fichaje del ERP sin identidad de registro; no entra en el libro.'
            )
            continue

        entrada = _momento(fichaje.get('check_in'))
        if entrada is None:
            continue

        usuario = User.query.filter(
            User.external_ids['odoo'].astext == str(fichaje.get('empleado_external_id'))
        ).first()
        if usuario is None:
            continue

        obra = None
        if fichaje.get('obra_external_id'):
            obra = Obra.query.filter(
                Obra.external_ids['odoo'].astext == str(fichaje['obra_external_id'])
            ).first()

        deseado[referencia] = {
            'user_id': usuario.id,
            'obra_id': obra.id if obra else None,
            'fecha_laboral': fecha_obj,
            EVENTO_ENTRADA: entrada,
            EVENTO_SALIDA: _momento(fichaje.get('check_out')),
            'autor': fichaje.get('autor'),
            'nota': fichaje.get('note'),
        }

    return deseado


def _anotar(referencia, datos, tipo, momento):
    registrar_evento(
        user_id=datos['user_id'],
        tipo=tipo,
        origen=ORIGEN_ERP,
        ocurrido_en=momento,
        fecha_laboral=datos['fecha_laboral'],
        obra_id=datos['obra_id'],
        external_ids={
            CLAVE_REFERENCIA: referencia,
            'erp_autor': datos.get('autor'),
            'erp_nota': datos.get('nota'),
        },
    )


def _obra_vigente(existentes):
    """
    A qué obra están imputadas ahora mismo las horas de este apunte.

    Manda la última reasignación si la hay; si no, la obra con la que se anotó
    la entrada.
    """
    reasignacion = existentes.get(EVENTO_REASIGNACION_OBRA)
    if reasignacion is not None:
        return reasignacion.obra_id

    entrada = existentes.get(EVENTO_ENTRADA)
    return entrada.obra_id if entrada is not None else None


def _nombre_obra(obra_id):
    if not obra_id:
        return 'sin obra'
    obra = Obra.query.filter_by(id=obra_id).first()
    return obra.nombre if obra else f'obra {obra_id}'


def _reasignar_obra(referencia, datos, existentes, obra_anterior_id):
    """
    Anota que las horas pasan a imputarse a otra obra.

    En obra es corriente que alguien fiche en el tajo equivocado y que
    administración lo corrija después en el ERP. Eso no rectifica la jornada:
    las horas trabajadas son las mismas y sus marcas de tiempo no se tocan.
    """
    # Lleva la hora de la entrada, no la de ahora: así queda colocado junto a la
    # jornada a la que se refiere. Cuándo se detectó la reimputación ya lo dice
    # 'registrado_en', y la distancia entre ambos es precisamente el dato útil.
    momento = existentes[EVENTO_ENTRADA].ocurrido_en

    registrar_evento(
        user_id=datos['user_id'],
        tipo=EVENTO_REASIGNACION_OBRA,
        origen=ORIGEN_ERP,
        ocurrido_en=momento,
        fecha_laboral=datos['fecha_laboral'],
        obra_id=datos['obra_id'],
        motivo=(
            f'Reimputado en el sistema de origen: de '
            f'{_nombre_obra(obra_anterior_id)} a {_nombre_obra(datos["obra_id"])}. '
            f'Las horas registradas no varían.'
        ),
        external_ids={
            CLAVE_REFERENCIA: referencia,
            'obra_anterior_id': obra_anterior_id,
            'erp_autor': datos.get('autor'),
        },
    )


def reflejar_jornada_del_erp(fecha_obj, fichajes):
    """
    Deja el libro de esa jornada de acuerdo con lo que dice el ERP.

    Devuelve un recuento de lo anotado. No hace commit: se ejecuta dentro de la
    transacción de la sincronización para que el libro y la auditoría entren o
    fallen juntos.
    """
    if dia_procede_de_importacion(fecha_obj):
        logger.info(
            'La jornada %s se rellenó volcando el histórico anterior; la '
            'revisión retrospectiva del ERP no la toca.', fecha_obj
        )
        return {'omitida_por_importacion': True}

    deseado = _estado_deseado(fichajes, fecha_obj)
    registrado, intervenidas = eventos_del_dia_por_referencia(
        fecha_obj, CLAVE_REFERENCIA
    )

    resumen = {
        'altas': 0, 'correcciones': 0, 'retiradas': 0,
        'reasignaciones': 0, 'respetadas': 0,
    }

    for referencia, datos in deseado.items():
        if referencia in intervenidas:
            # Alguien corrigió esto a mano en la aplicación. Su decisión manda:
            # volver a anotarlo la desharía en cada pasada de la sincronización.
            resumen['respetadas'] += 1
            continue

        existentes = registrado.get(referencia, {})
        obra_anterior_id = _obra_vigente(existentes)
        marcas_rehechas = False

        for tipo in (EVENTO_ENTRADA, EVENTO_SALIDA):
            momento = datos[tipo]
            anotado = existentes.get(tipo)

            if momento is None:
                if anotado is not None:
                    # Estaba y el ERP ya no lo da: alguien reabrió o borró la
                    # salida allí. Se anula, no se borra.
                    anular_evento(
                        anotado.id,
                        motivo=(
                            f'El sistema de origen ya no informa de esta marca '
                            f'({referencia}).'
                        ),
                        autor_id=None,
                        origen=ORIGEN_ERP,
                    )
                    resumen['retiradas'] += 1
                continue

            if anotado is None:
                _anotar(referencia, datos, tipo, momento)
                resumen['altas'] += 1
                marcas_rehechas = True
            elif anotado.ocurrido_en != momento:
                # Alguien ha editado la hora en el ERP. Queda la anterior, la
                # anulación con su motivo y la nueva: los tres hechos.
                anular_evento(
                    anotado.id,
                    motivo=(
                        f'Corregido en el sistema de origen: pasa de '
                        f'{anotado.ocurrido_en:%H:%M:%S} a {momento:%H:%M:%S} UTC '
                        f'(referencia {referencia}).'
                    ),
                    autor_id=None,
                    origen=ORIGEN_ERP,
                )
                _anotar(referencia, datos, tipo, momento)
                resumen['correcciones'] += 1
                marcas_rehechas = True

        # Las marcas que se acaban de escribir ya llevan la obra buena; anotar
        # además una reasignación sería contar dos veces el mismo cambio.
        if (
            not marcas_rehechas
            and EVENTO_ENTRADA in existentes
            and obra_anterior_id != datos['obra_id']
        ):
            _reasignar_obra(referencia, datos, existentes, obra_anterior_id)
            resumen['reasignaciones'] += 1

    # Apuntes que el libro tenía y el ERP ya no reporta: se han borrado allí.
    for referencia, existentes in registrado.items():
        if referencia in deseado or referencia in intervenidas:
            continue
        for tipo, evento in existentes.items():
            if tipo == EVENTO_REASIGNACION_OBRA:
                # Anular una reasignación devolvería las horas a la obra
                # equivocada. Lo que se retira son las marcas de tiempo.
                continue
            anular_evento(
                evento.id,
                motivo=(
                    f'El apunte {referencia} ha desaparecido del sistema de '
                    f'origen para esta jornada.'
                ),
                autor_id=None,
                origen=ORIGEN_ERP,
            )
            resumen['retiradas'] += 1

    db.session.flush()
    return resumen


def reflejar_sin_romper_la_sincronizacion(fecha_obj, fichajes):
    """
    Igual que la anterior, pero convierte un fallo de regla en un aviso.

    Un error de datos en un apunte suelto no debe tumbar la sincronización
    entera del tenant, que es lo que mantiene la planificación al día.

    Quedarse a medias no corrompe nada: lo ya anotado es válido y la siguiente
    pasada reconcilia el resto, porque la comparación se hace siempre contra lo
    que hay en el libro y no contra un estado guardado aparte.
    """
    try:
        return reflejar_jornada_del_erp(fecha_obj, fichajes)
    except FichajeLedgerError:
        logger.exception('El volcado de fichajes del ERP al libro no se completó.')
        return None
