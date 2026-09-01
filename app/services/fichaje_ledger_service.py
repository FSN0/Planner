# app/services/fichaje_ledger_service.py
#
# Libro de eventos de jornada: la fuente de verdad del registro horario.
#
# Reglas que no se pueden romper:
#   - Solo se añaden eventos. Nunca se modifica ni se borra ninguno (la base
#     de datos lo impide con un disparador; esto es la segunda barrera).
#   - Cada evento va encadenado por hash con el anterior del mismo tenant.
#   - Corregir es añadir una anulación con su motivo, no reescribir el pasado.
#
# RegistroFichaje pasa a ser una proyección derivada de estos eventos: conserva
# el flujo de auditoría y conciliación que ya existía, pero los datos de hecho
# (hora de entrada, de salida y obra real) se recalculan siempre desde aquí.

from datetime import timedelta

from sqlalchemy import text

from app import db
from app.models import (
    ANIOS_CONSERVACION_FICHAJES,
    EVENTO_ANULACION,
    EVENTO_ENTRADA,
    EVENTO_PAUSA_FIN,
    EVENTO_PAUSA_INICIO,
    EVENTO_REASIGNACION_OBRA,
    EVENTO_SALIDA,
    ORIGEN_PWA,
    ORIGENES_EVENTO_FICHAJE,
    ORIGENES_REQUIEREN_MOTIVO,
    TIPOS_EVENTO_FICHAJE,
    FichajeEvento,
    RegistroFichaje,
)
from app.utils.timezone_utils import get_app_timezone, utc_now, utc_to_local

# Solo en estos orígenes ficha la persona por sí misma; en el resto el autor
# es quien introduce el dato y hay que dejarlo explícito.
_ORIGENES_AUTOFICHAJE = (ORIGEN_PWA,)


class FichajeLedgerError(Exception):
    """Error de uso del libro de eventos (datos inválidos o regla violada)."""


def _bloquear_cadena():
    """
    Serializa las inserciones del tenant actual mientras dure la transacción.

    Sin esto, dos fichajes simultáneos podrían leer el mismo 'último hash' y
    generar una bifurcación en la cadena. El bloqueo es por esquema, así que
    los tenants no se estorban entre sí.
    """
    db.session.execute(
        text('SELECT pg_advisory_xact_lock(hashtext(current_schema()))')
    )


def _ultimo_evento():
    return (
        FichajeEvento.query
        .order_by(FichajeEvento.secuencia.desc())
        .first()
    )


def _fecha_laboral_por_defecto(ocurrido_en):
    """
    La jornada a la que se imputa el evento, en hora local de la empresa.

    Se usa la zona de la app y no la del usuario porque la jornada es un
    concepto de la empresa: dos trabajadores del mismo tajo tienen que caer
    en el mismo día aunque tengan configuraciones distintas.
    """
    return utc_to_local(ocurrido_en).date()


def registrar_evento(
    user_id,
    tipo,
    origen,
    ocurrido_en=None,
    fecha_laboral=None,
    autor_id=None,
    obra_id=None,
    latitud=None,
    longitud=None,
    precision_metros=None,
    geo_estado=None,
    distancia_obra_metros=None,
    nota_ubicacion=None,
    dispositivo=None,
    ip=None,
    motivo=None,
    evento_anulado_id=None,
    external_ids=None,
    zona_horaria=None,
):
    """
    Añade un evento al libro y devuelve la instancia ya encadenada.

    No hace commit: el llamante decide el alcance de la transacción, para que
    un fichaje y su proyección entren o fallen juntos.
    """
    if tipo not in TIPOS_EVENTO_FICHAJE:
        raise FichajeLedgerError(f"Tipo de evento no válido: {tipo}")
    if origen not in ORIGENES_EVENTO_FICHAJE:
        raise FichajeLedgerError(f"Origen de evento no válido: {origen}")
    if not user_id:
        raise FichajeLedgerError("Un evento de fichaje necesita un trabajador.")

    motivo = (motivo or '').strip() or None

    if origen in ORIGENES_REQUIEREN_MOTIVO and not motivo:
        raise FichajeLedgerError(
            "Los fichajes introducidos manualmente deben indicar el motivo."
        )
    if tipo == EVENTO_ANULACION:
        if not evento_anulado_id:
            raise FichajeLedgerError("Una anulación debe indicar qué evento anula.")
        if not motivo:
            raise FichajeLedgerError("Una anulación debe indicar el motivo.")
    if tipo == EVENTO_REASIGNACION_OBRA:
        if not obra_id:
            raise FichajeLedgerError(
                "Una reasignación debe indicar a qué obra pasan las horas."
            )
        if not motivo:
            raise FichajeLedgerError("Una reasignación debe indicar el motivo.")

    ocurrido_en = (ocurrido_en or utc_now()).replace(microsecond=0)

    _bloquear_cadena()
    anterior = _ultimo_evento()

    evento = FichajeEvento(
        secuencia=(anterior.secuencia + 1) if anterior else 1,
        user_id=user_id,
        tipo=tipo,
        origen=origen,
        fecha_laboral=fecha_laboral or _fecha_laboral_por_defecto(ocurrido_en),
        ocurrido_en=ocurrido_en,
        registrado_en=utc_now().replace(microsecond=0),
        zona_horaria=zona_horaria or get_app_timezone(),
        autor_id=(
            autor_id if autor_id is not None
            else (user_id if origen in _ORIGENES_AUTOFICHAJE else None)
        ),
        obra_id=obra_id,
        latitud=latitud,
        longitud=longitud,
        precision_metros=precision_metros,
        geo_estado=geo_estado,
        distancia_obra_metros=distancia_obra_metros,
        nota_ubicacion=nota_ubicacion,
        dispositivo=(dispositivo or None),
        ip=(ip or None),
        motivo=motivo,
        evento_anulado_id=evento_anulado_id,
        external_ids=external_ids or None,
        hash_previo=anterior.hash if anterior else None,
    )
    evento.hash = evento.calcular_hash()

    db.session.add(evento)
    db.session.flush()
    return evento


def anular_evento(evento_id, motivo, autor_id, origen=None):
    """
    Deja sin efecto un evento sin tocarlo: añade una anulación que lo apunta.
    """
    original = FichajeEvento.query.filter_by(id=evento_id).first()
    if original is None:
        raise FichajeLedgerError("El evento que se intenta anular no existe.")
    if original.tipo == EVENTO_ANULACION:
        raise FichajeLedgerError("Una anulación no se puede anular.")
    if esta_anulado(original.id):
        raise FichajeLedgerError("Ese evento ya estaba anulado.")

    from app.models import ORIGEN_ADMIN

    return registrar_evento(
        user_id=original.user_id,
        tipo=EVENTO_ANULACION,
        origen=origen or ORIGEN_ADMIN,
        fecha_laboral=original.fecha_laboral,
        autor_id=autor_id,
        obra_id=original.obra_id,
        motivo=motivo,
        evento_anulado_id=original.id,
    )


def esta_anulado(evento_id):
    return db.session.query(
        FichajeEvento.query.filter(
            FichajeEvento.tipo == EVENTO_ANULACION,
            FichajeEvento.evento_anulado_id == evento_id,
        ).exists()
    ).scalar()


def vigentes(eventos):
    """
    Quita de una lista las anulaciones y lo que anulan.

    Trabaja sobre una lista ya cargada para que quien necesite varios días
    pueda traérselos de una sola consulta en vez de una por día.
    """
    anulados = {
        e.evento_anulado_id for e in eventos if e.tipo == EVENTO_ANULACION
    }
    return [
        e for e in eventos
        if e.tipo != EVENTO_ANULACION and e.id not in anulados
    ]


def eventos_del_dia(user_id, fecha, incluir_anulados=False):
    """Eventos de una jornada concreta, en orden cronológico."""
    eventos = (
        FichajeEvento.query
        .filter(
            FichajeEvento.user_id == user_id,
            FichajeEvento.fecha_laboral == fecha,
        )
        .order_by(FichajeEvento.ocurrido_en.asc(), FichajeEvento.secuencia.asc())
        .all()
    )
    return eventos if incluir_anulados else vigentes(eventos)


def dia_procede_de_importacion(fecha):
    """
    ¿Esta jornada entró en el libro volcando el histórico anterior?

    Importa porque hay una revisión retrospectiva que vuelve a pedir al ERP
    fechas de hasta un año atrás. Si esos días ya se rellenaron desde la tabla
    antigua, volver a derivarlos del ERP los duplicaría: el volcado y el ERP
    describen los mismos fichajes sin compartir ninguna referencia común.
    """
    from app.models import ORIGEN_MIGRACION

    return db.session.query(
        FichajeEvento.query.filter(
            FichajeEvento.fecha_laboral == fecha,
            FichajeEvento.origen == ORIGEN_MIGRACION,
        ).exists()
    ).scalar()


def eventos_del_dia_por_referencia(fecha, clave_referencia):
    """
    Los eventos de una jornada que vienen de un sistema externo, indexados por
    la referencia de ese sistema: {referencia: {tipo: evento}}.

    Devuelve además el conjunto de referencias que alguien ha anulado a mano
    desde la aplicación. La sincronización tiene que respetarlas: si una persona
    corrigió un fichaje aquí y el ERP sigue mandando el original, volver a
    anotarlo desharía su decisión en cada pasada.
    """
    eventos = (
        FichajeEvento.query
        .filter(FichajeEvento.fecha_laboral == fecha)
        .order_by(FichajeEvento.secuencia.asc())
        .all()
    )

    anulaciones = {
        e.evento_anulado_id: e for e in eventos if e.tipo == EVENTO_ANULACION
    }

    por_referencia = {}
    intervenidas = set()

    for evento in eventos:
        referencia = (evento.external_ids or {}).get(clave_referencia)
        if not referencia:
            continue

        anulacion = anulaciones.get(evento.id)
        if anulacion is None:
            por_referencia.setdefault(referencia, {})[evento.tipo] = evento
        elif anulacion.origen != evento.origen:
            # La anulación no viene del mismo sistema que creó el evento: es una
            # intervención local y manda sobre lo que diga el origen.
            intervenidas.add(referencia)

    return por_referencia, intervenidas


def eventos_del_periodo(user_id, desde, hasta, incluir_anulados=False):
    """
    Los eventos vigentes de un rango, agrupados por jornada.

    Devuelve un diccionario {fecha: [eventos]} con una sola consulta: el
    historial del trabajador puede pedir un año entero y hacerlo día a día
    salían cientos de viajes a la base de datos.
    """
    eventos = (
        FichajeEvento.query
        .filter(
            FichajeEvento.user_id == user_id,
            FichajeEvento.fecha_laboral >= desde,
            FichajeEvento.fecha_laboral <= hasta,
        )
        .order_by(FichajeEvento.ocurrido_en.asc(), FichajeEvento.secuencia.asc())
        .all()
    )

    por_dia = {}
    for evento in (eventos if incluir_anulados else vigentes(eventos)):
        por_dia.setdefault(evento.fecha_laboral, []).append(evento)
    return por_dia


def verificar_cadena(desde_secuencia=None, limite=None):
    """
    Recalcula la cadena y devuelve las incidencias encontradas.

    Es lo que convierte "inalterable" en algo demostrable: si alguien tocó una
    fila por SQL directo, el hash deja de cuadrar y aquí sale.
    """
    consulta = FichajeEvento.query.order_by(FichajeEvento.secuencia.asc())
    if desde_secuencia:
        consulta = consulta.filter(FichajeEvento.secuencia >= desde_secuencia)
    if limite:
        consulta = consulta.limit(limite)

    incidencias = []
    esperado_previo = None
    esperada_secuencia = desde_secuencia or 1

    for evento in consulta:
        if evento.secuencia != esperada_secuencia:
            incidencias.append({
                'secuencia': evento.secuencia,
                'tipo': 'hueco',
                'detalle': (
                    f"Se esperaba la secuencia {esperada_secuencia} "
                    f"y se encontró la {evento.secuencia}."
                ),
            })
            esperada_secuencia = evento.secuencia

        if esperado_previo is not None and evento.hash_previo != esperado_previo:
            incidencias.append({
                'secuencia': evento.secuencia,
                'tipo': 'cadena_rota',
                'detalle': "El enlace con el evento anterior no coincide.",
            })

        if evento.calcular_hash() != evento.hash:
            incidencias.append({
                'secuencia': evento.secuencia,
                'tipo': 'contenido_alterado',
                'detalle': "El contenido no corresponde con su firma.",
            })

        esperado_previo = evento.hash
        esperada_secuencia += 1

    return incidencias


def fecha_limite_conservacion(referencia=None):
    """Fecha antes de la cual ya no es obligatorio conservar registros."""
    ref = referencia or utc_now().date()
    return ref - timedelta(days=365 * ANIOS_CONSERVACION_FICHAJES + 1)


def puede_purgarse(fecha_laboral, referencia=None):
    """
    Los registros de jornada se conservan cuatro años. Cualquier borrado
    debe pasar por aquí antes de tocar nada.
    """
    return fecha_laboral < fecha_limite_conservacion(referencia)


# ---------------------------------------------------------------------------
# Proyección: de eventos a RegistroFichaje
# ---------------------------------------------------------------------------

def proyectar_dia(user_id, fecha):
    """
    Recalcula los datos de hecho del día a partir de los eventos vigentes.

    Solo toca hora de entrada, hora de salida y obra real. El estado de la
    conciliación (correcto, conflicto, resuelto...) es un juicio de la empresa,
    no un hecho, y lo sigue gobernando el flujo de auditoría existente.
    """
    eventos = eventos_del_dia(user_id, fecha)

    entradas = [e for e in eventos if e.tipo == EVENTO_ENTRADA]
    salidas = [e for e in eventos if e.tipo == EVENTO_SALIDA]

    registro = RegistroFichaje.query.filter_by(user_id=user_id, fecha=fecha).first()

    if not eventos:
        return registro

    if registro is None:
        registro = RegistroFichaje(user_id=user_id, fecha=fecha, estado='Pendiente')
        db.session.add(registro)

    registro.check_in = entradas[0].ocurrido_en if entradas else None
    registro.check_out = salidas[-1].ocurrido_en if salidas else None

    # Una reasignación posterior manda sobre la obra con la que se fichó: es
    # exactamente para eso, corregir el destino de unas horas sin tocarlas.
    reasignaciones = [
        e for e in eventos
        if e.tipo == EVENTO_REASIGNACION_OBRA and e.obra_id is not None
    ]
    if reasignaciones:
        registro.obra_real_id = reasignaciones[-1].obra_id
    else:
        obra_declarada = next(
            (e.obra_id for e in entradas if e.obra_id is not None), None
        )
        if obra_declarada is not None:
            registro.obra_real_id = obra_declarada

    db.session.flush()
    return registro


def minutos_trabajados(user_id, fecha):
    """Tiempo efectivo de una jornada, descontando pausas, en minutos."""
    return minutos_de(eventos_del_dia(user_id, fecha))


def minutos_de(eventos):
    """
    Tiempo efectivo que representa una lista de eventos ya cargada.

    Empareja entradas con salidas y pausas con reanudaciones en orden
    cronológico; los eventos sueltos (un olvido de salida) se ignoran en el
    cómputo pero siguen visibles en el libro.
    """
    total = timedelta()
    entrada_abierta = None
    pausa_abierta = None

    for evento in eventos:
        if evento.tipo == EVENTO_ENTRADA and entrada_abierta is None:
            entrada_abierta = evento.ocurrido_en
        elif evento.tipo == EVENTO_SALIDA and entrada_abierta is not None:
            if pausa_abierta is not None:
                total -= evento.ocurrido_en - pausa_abierta
                pausa_abierta = None
            total += evento.ocurrido_en - entrada_abierta
            entrada_abierta = None
        elif evento.tipo == EVENTO_PAUSA_INICIO and pausa_abierta is None:
            pausa_abierta = evento.ocurrido_en
        elif evento.tipo == EVENTO_PAUSA_FIN and pausa_abierta is not None:
            total -= evento.ocurrido_en - pausa_abierta
            pausa_abierta = None

    return max(int(total.total_seconds() // 60), 0)


def jornada_abierta(user_id, fecha=None):
    """
    Devuelve el estado actual del trabajador: si está dentro, en pausa o fuera.

    Lo usa la PWA para saber qué botón mostrar.
    """
    fecha = fecha or utc_to_local(utc_now()).date()
    eventos = eventos_del_dia(user_id, fecha)

    estado = 'fuera'
    obra_id = None
    desde = None

    for evento in eventos:
        if evento.tipo == EVENTO_ENTRADA:
            estado = 'dentro'
            obra_id = evento.obra_id or obra_id
            desde = evento.ocurrido_en
        elif evento.tipo == EVENTO_SALIDA:
            estado = 'fuera'
            desde = evento.ocurrido_en
        elif evento.tipo == EVENTO_PAUSA_INICIO and estado == 'dentro':
            estado = 'pausa'
            desde = evento.ocurrido_en
        elif evento.tipo == EVENTO_PAUSA_FIN and estado == 'pausa':
            estado = 'dentro'
            desde = evento.ocurrido_en

    return {
        'estado': estado,
        'obra_id': obra_id,
        'desde': desde,
        'fecha': fecha,
        'minutos': minutos_trabajados(user_id, fecha),
    }
