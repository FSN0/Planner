# app/services/fichaje_operario_service.py
#
# Lo que el trabajador puede hacer desde su móvil: fichar y consultar sus
# propios registros. Se apoya en el libro de eventos, que es quien garantiza
# que lo fichado no se puede alterar después.
#
# Dos capas: el módulo comercial fichaje_operario (superadmin /alta) y el
# interruptor del cliente fichaje_operario_activo («Fichajes»). Sin módulo
# no hay portal de fichaje. Con módulo apagado, tampoco. El alta pública deja ambos on.

from datetime import timedelta

from app import db
from app.models import (
    EVENTO_ENTRADA,
    EVENTO_PAUSA_FIN,
    EVENTO_PAUSA_INICIO,
    EVENTO_SALIDA,
    EVENTO_CONFORME_JORNADA,
    ORIGEN_PWA,
    Asignacion,
    Obra,
    RegistroFichaje,
)
from app.services.config_service import get_tenant_config
from app.services.core_assignment_service import CoreAssignmentService
from app.services.fichaje_ledger_service import (
    FichajeLedgerError,
    eventos_del_dia,
    eventos_del_periodo,
    jornada_abierta,
    minutos_de,
    proyectar_dia,
    registrar_evento,
)
from app.utils.timezone_utils import today_local, utc_now

CONFIG_FICHAJE_OPERARIO = 'fichaje_operario_activo'
CONFIG_FICHAJE_GEO = 'fichaje_geolocalizacion'
CONFIG_FICHAJE_GEO_EXIGIR = 'fichaje_geolocalizacion_exigir'
CONFIG_FICHAJE_ASKED = 'onboarding_fichaje_asked'

# Misma etiqueta que el sync de Odoo: el cuadrante refleja el fichaje físico.
CONTEXTO_FICHAJE_PWA = 'Auto-asignación por Fichaje Físico'

GEO_DESACTIVADA = 'desactivada'
GEO_ACTIVADA = 'activada'
GEO_OPCIONES = (GEO_DESACTIVADA, GEO_ACTIVADA)

# Transiciones válidas: de qué estado se puede pasar a qué acción.
_TRANSICIONES = {
    EVENTO_ENTRADA: ('fuera',),
    EVENTO_SALIDA: ('dentro', 'pausa'),
    EVENTO_PAUSA_INICIO: ('dentro',),
    EVENTO_PAUSA_FIN: ('pausa',),
}

_MENSAJE_TRANSICION = {
    EVENTO_ENTRADA: 'Ya tienes la jornada iniciada.',
    EVENTO_SALIDA: 'No tienes ninguna jornada abierta que cerrar.',
    EVENTO_PAUSA_INICIO: 'Solo puedes iniciar una pausa con la jornada abierta.',
    EVENTO_PAUSA_FIN: 'No tienes ninguna pausa abierta.',
}


def tenant_tiene_fichaje_operario_module():
    """
    El PWA del operario es un módulo comercial/funcional independiente.
    Si no está activado en el tenant, no enseñamos sus ajustes ni abrimos el portal de fichaje.
    """
    from flask import g, has_app_context

    if not has_app_context():
        return False
    tenant = getattr(g, 'current_tenant', None)
    modulos = getattr(tenant, 'modulos_activos', {}) or {}
    return bool(modulos.get('fichaje_operario'))


def fichaje_operario_activo():
    """¿Este tenant deja fichar a sus operarios desde el móvil?"""
    if not tenant_tiene_fichaje_operario_module():
        return False
    return str(get_tenant_config(CONFIG_FICHAJE_OPERARIO, default='False')) == 'True'


def tenant_muestra_auditoria_fichajes():
    """
    Auditoría de fichajes en menú, panel y correos.

    - Cliente con Odoo (p. ej. Soltec): sí, aunque no tenga portal de fichaje propio.
    - Alta con módulo de fichaje: solo si el interruptor «Fichajes» está on.
    - Superadmin sin Odoo ni módulo: no.
    """
    from flask import g, has_app_context

    if not has_app_context():
        return False
    tenant = getattr(g, 'current_tenant', None)
    mods = getattr(tenant, 'modulos_activos', None) or {}
    if mods.get('odoo'):
        return True
    if mods.get('fichaje_operario'):
        return str(get_tenant_config(CONFIG_FICHAJE_OPERARIO, default='False')) == 'True'
    return False


def usuario_ve_estado_fichaje(user) -> bool:
    """Pelotitas de fichaje en tablero, calendarios, etc."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if not tenant_muestra_auditoria_fichajes():
        return False
    from app.services.permission_service import user_can
    return user_can(user, 'auditoria_fichajes', 'r')


def activar_fichajes_alta():
    """Alta pública: Fichajes on, oficina on, ubicación no (default)."""
    from app.services.config_service import set_tenant_config
    from app.services.oficina_obra_service import (
        CONFIG_OBRA_OFICINA,
        sincronizar_obra_oficina,
    )

    set_tenant_config(CONFIG_FICHAJE_OPERARIO, 'True')
    marcar_fichaje_preferencia_decidida()
    set_tenant_config(CONFIG_OBRA_OFICINA, 'True')
    sincronizar_obra_oficina(True)
    db.session.commit()


def fichaje_preferencia_decidida():
    """True si el admin ya respondió sí/no al fichaje en el onboarding."""
    return str(get_tenant_config(CONFIG_FICHAJE_ASKED, default='False')) == 'True'


def marcar_fichaje_preferencia_decidida():
    from app.services.config_service import set_tenant_config
    set_tenant_config(CONFIG_FICHAJE_ASKED, 'True')


def modo_geolocalizacion():
    """
    Cómo trata este tenant la ubicación al fichar.

    La geolocalización es valor de plan de pago. En free siempre queda
    desactivada, aunque en configuración figure otra cosa.
    """
    from app.services.geocerca_service import normalizar_modo_geo_config
    from app.services.plan_service import plan_incluye_geolocalizacion

    if not plan_incluye_geolocalizacion():
        return GEO_DESACTIVADA
    valor = get_tenant_config(CONFIG_FICHAJE_GEO, default=GEO_DESACTIVADA)
    return (
        GEO_ACTIVADA
        if normalizar_modo_geo_config(valor) == GEO_ACTIVADA
        else GEO_DESACTIVADA
    )


def geolocalizacion_activa():
    return modo_geolocalizacion() == GEO_ACTIVADA


def geolocalizacion_exigir():
    """Si la geo está activada, ¿es obligatorio tener GPS para fichar?"""
    from app.services.geocerca_service import (
        modo_geo_exigir_desde_config,
        normalizar_modo_geo_config,
    )

    if not geolocalizacion_activa():
        return False
    if str(get_tenant_config(CONFIG_FICHAJE_GEO_EXIGIR, default='False')) == 'True':
        return True
    valor = get_tenant_config(CONFIG_FICHAJE_GEO, default=GEO_DESACTIVADA)
    return modo_geo_exigir_desde_config(valor)


def obras_del_dia(user_id, fecha=None):
    """Obras en las que el trabajador está planificado hoy (hecho o inercia)."""
    fecha = fecha or today_local()
    planificadas = (
        Obra.query
        .join(Asignacion, Asignacion.obra_id == Obra.id)
        .filter(Asignacion.user_id == user_id, Asignacion.fecha == fecha)
        .order_by(Obra.nombre.asc())
        .all()
    )
    if planificadas:
        return planificadas
    from app.services.inercia_service import casa_en_fecha, es_dia_laborable
    if not es_dia_laborable(fecha):
        return []
    casa_id = casa_en_fecha(user_id, fecha)
    if not casa_id:
        return []
    casa = Obra.query.filter_by(id=casa_id).first()
    return [casa] if casa and not getattr(casa, 'is_deleted', False) else []


def obras_seleccionables(user_id, fecha=None):
    """
    Lo que se le ofrece elegir al fichar: primero sus obras del día y, detrás,
    el resto de obras vivas (incluida Oficina si el tenant la tiene activa).

    En construcción es habitual que a alguien lo manden a un tajo que no estaba
    planificado. Bloquearlo obligaría a no fichar, que es peor que fichar en el
    sitio equivocado: la auditoría ya detecta esas discrepancias.
    """
    from app.services.oficina_obra_service import es_obra_oficina, oficina_activa

    fecha = fecha or today_local()
    planificadas = [
        o for o in obras_del_dia(user_id, fecha)
        if not getattr(o, 'is_deleted', False)
    ]
    ids_planificadas = {o.id for o in planificadas}

    otras = (
        Obra.query
        .filter(
            Obra.is_deleted.is_(False),
            Obra.estado.in_(['En Curso', 'PLANIFICADA']),
        )
        .order_by(Obra.nombre.asc())
        .all()
    )
    otras = [o for o in otras if o.id not in ids_planificadas]

    if oficina_activa():
        oficina = next((o for o in otras if es_obra_oficina(o)), None)
        if oficina:
            otras = [oficina] + [o for o in otras if o.id != oficina.id]

    return planificadas, otras


def estado_para_pantalla(user, fecha=None):
    """Todo lo que necesita la pantalla de fichaje en una sola llamada."""
    import json

    from app.services.geocerca_service import (
        geocerca_activa,
        preseleccion_obra_id,
        serializar_obras_geo,
        ultima_obra_entrada_id,
    )

    fecha = fecha or today_local()
    estado = jornada_abierta(user.id, fecha)
    planificadas, otras = obras_seleccionables(user.id, fecha)

    obra_actual = None
    if estado['obra_id']:
        obra_actual = Obra.query.filter_by(id=estado['obra_id']).first()

    todas = planificadas + otras
    obra_preseleccionada_id = preseleccion_obra_id(
        user.id, fecha, planificadas, otras,
    )
    ultima_obra_id = ultima_obra_entrada_id(user.id, fecha)

    return {
        'estado': estado['estado'],
        'desde': estado['desde'],
        'minutos': estado['minutos'],
        'fecha': fecha,
        'obra_actual': obra_actual,
        'obras_planificadas': planificadas,
        'otras_obras': otras,
        'modo_geo': modo_geolocalizacion(),
        'geo_exigir': geolocalizacion_exigir(),
        'geocerca_activa': geocerca_activa(),
        'obras_geo_json': json.dumps(serializar_obras_geo(todas)),
        'obra_preseleccionada_id': obra_preseleccionada_id,
        'ultima_obra_entrada_id': ultima_obra_id,
        'eventos': eventos_del_dia(user.id, fecha),
        'conforme': dia_tiene_conforme(user.id, fecha),
        'puede_conformar': puede_conformar_jornada(user.id, fecha),
    }


def _validar_transicion(user_id, tipo, fecha):
    estado = jornada_abierta(user_id, fecha)['estado']
    if estado not in _TRANSICIONES.get(tipo, ()):
        raise FichajeLedgerError(_MENSAJE_TRANSICION.get(tipo, 'Acción no permitida.'))


def _validar_geo(latitud, longitud):
    if not geolocalizacion_activa():
        return None, None, False
    if geolocalizacion_exigir() and (latitud is None or longitud is None):
        raise FichajeLedgerError(
            'Esta empresa exige registrar la ubicación al fichar. '
            'Activa la localización en tu móvil y vuelve a intentarlo.'
        )
    return latitud, longitud, True


def asegurar_asignacion_por_fichaje(user, obra_id, fecha):
    """
    Si el operario ficha en una obra, el tablero debe mostrarlo ahí.

    Sin esto el fichaje queda solo en el libro legal y el cuadrante le sigue
    tratando como libre. Si ya tenía otra obra ese día, se mueve a la que
    acaba de fichar (misma idea que «Mover» en auditoría).
    """
    ya = Asignacion.query.filter_by(
        user_id=user.id, obra_id=obra_id, fecha=fecha,
    ).first()
    if ya:
        return ya

    otras = Asignacion.query.filter(
        Asignacion.user_id == user.id,
        Asignacion.fecha == fecha,
        Asignacion.obra_id != obra_id,
    ).all()
    for a in otras:
        CoreAssignmentService.desasignar(
            a.user_id,
            a.obra_id,
            a.fecha,
            user.id,
            CONTEXTO_FICHAJE_PWA,
            'Reasignado al fichar en otra obra.',
            registrar_log=False,
        )

    return CoreAssignmentService.asignar(
        user.id,
        obra_id,
        fecha,
        user.id,
        CONTEXTO_FICHAJE_PWA,
        company_id=user.company_id,
    )


def fichar(user, tipo, obra_id=None, latitud=None, longitud=None,
           precision_metros=None, ip=None, dispositivo=None,
           nota_ubicacion=None):
    """
    Registra un fichaje del trabajador y actualiza la proyección del día.

    Devuelve el estado actualizado de la pantalla. Lanza FichajeLedgerError si
    la acción no encaja con la jornada actual.
    """
    if not fichaje_operario_activo():
        raise FichajeLedgerError('El fichaje desde el móvil no está activado en tu empresa.')
    if tipo not in _TRANSICIONES:
        raise FichajeLedgerError('Acción de fichaje no reconocida.')

    fecha = today_local()
    _validar_transicion(user.id, tipo, fecha)

    latitud, longitud, guardar_geo = _validar_geo(latitud, longitud)
    if not guardar_geo:
        latitud = longitud = precision_metros = None

    obra = None
    if tipo == EVENTO_ENTRADA:
        if not obra_id:
            raise FichajeLedgerError('Indica en qué obra vas a trabajar.')
        obra = Obra.query.filter_by(id=obra_id).first()
        if obra is None:
            raise FichajeLedgerError('Esa obra no existe.')
    else:
        # Las salidas y pausas heredan la obra de la entrada en curso.
        obra_id = jornada_abierta(user.id, fecha)['obra_id']
        if obra_id:
            obra = Obra.query.filter_by(id=obra_id).first()

    from app.services.geocerca_service import evaluar_geo_fichaje

    geo_estado, distancia_obra = evaluar_geo_fichaje(obra, latitud, longitud)
    nota_ubicacion = (nota_ubicacion or '').strip() or None

    registrar_evento(
        user_id=user.id,
        tipo=tipo,
        origen=ORIGEN_PWA,
        fecha_laboral=fecha,
        obra_id=obra.id if obra else obra_id,
        latitud=latitud,
        longitud=longitud,
        precision_metros=precision_metros,
        geo_estado=geo_estado,
        distancia_obra_metros=distancia_obra,
        nota_ubicacion=nota_ubicacion,
        ip=ip,
        dispositivo=dispositivo,
    )

    if tipo == EVENTO_ENTRADA and obra is not None:
        from app.services.inercia_service import (
            aceptar_primer_fichaje,
            casa_en_fecha,
            clasificar_entrada_fichaje,
        )
        ya_planificado = Asignacion.query.filter_by(
            user_id=user.id, obra_id=obra.id, fecha=fecha,
        ).first() is not None
        otras_hoy = Asignacion.query.filter(
            Asignacion.user_id == user.id,
            Asignacion.fecha == fecha,
            Asignacion.obra_id != obra.id,
        ).all()
        casa_id = None
        if not ya_planificado and not otras_hoy:
            casa_id = casa_en_fecha(user.id, fecha)
        clasif = clasificar_entrada_fichaje(
            obra_fichada_id=obra.id,
            planificado_en_obra_fichada=ya_planificado,
            otras_obras_planificadas_ids=[a.obra_id for a in otras_hoy],
            casa_obra_id=casa_id,
            aceptar_primer_fichaje=aceptar_primer_fichaje(),
        )
        # Desvío X→Y: no mover el cuadrante hasta que el jefe del plan libere.
        # En el resto de casos el tablero debe reflejar dónde ha fichado.
        if clasif.estado != 'Conflicto':
            asegurar_asignacion_por_fichaje(user, obra.id, fecha)
        proyectar_dia(user.id, fecha)
        registro = RegistroFichaje.query.filter_by(
            user_id=user.id, fecha=fecha,
        ).first()
        if registro is not None:
            registro.estado = clasif.estado
            registro.obra_planificada_id = clasif.obra_planificada_id
            registro.obra_real_id = obra.id
            if clasif.estado == 'Conflicto':
                from app.services.desvio_fichaje_service import limpiar_acks_desvio
                limpiar_acks_desvio(registro)
        db.session.commit()
        if registro is not None and clasif.estado == 'Conflicto':
            from app.services.desvio_fichaje_service import notificar_desvio_inmediato
            notificar_desvio_inmediato(registro)
        return estado_para_pantalla(user, fecha)

    proyectar_dia(user.id, fecha)
    db.session.commit()

    return estado_para_pantalla(user, fecha)


def dia_tiene_conforme(user_id, fecha):
    """¿El trabajador ya firmó/confirmó esa jornada en el libro?"""
    from app.services.fichaje_ledger_service import eventos_del_dia
    return any(e.tipo == EVENTO_CONFORME_JORNADA for e in eventos_del_dia(user_id, fecha))


def puede_conformar_jornada(user_id, fecha):
    """
    Solo se puede conformar un día cerrado (con salida) y sin conforme previo.
    Así el informe puede mostrar la aceptación del interesado.
    """
    from app.services.tenant_modules import conforme_jornada_activo
    if not conforme_jornada_activo():
        return False
    if dia_tiene_conforme(user_id, fecha):
        return False
    estado = jornada_abierta(user_id, fecha)
    if estado['estado'] != 'fuera':
        return False
    eventos = eventos_del_dia(user_id, fecha)
    tiene_entrada = any(e.tipo == EVENTO_ENTRADA for e in eventos)
    tiene_salida = any(e.tipo == EVENTO_SALIDA for e in eventos)
    return bool(tiene_entrada and tiene_salida)


def conformar_jornada(user, fecha=None, ip=None, dispositivo=None):
    """
    Registra el conforme del trabajador sobre su jornada del día.

    Queda en el libro inalterable (append-only + hash). Es la pieza que
    sustituye la firma manuscrita en el informe de inspección.
    """
    if not fichaje_operario_activo():
        raise FichajeLedgerError('El fichaje desde el móvil no está activado en tu empresa.')
    from app.services.tenant_modules import conforme_jornada_activo
    if not conforme_jornada_activo():
        raise FichajeLedgerError('Tu empresa no usa la firma de jornada.')

    fecha = fecha or today_local()
    if not puede_conformar_jornada(user.id, fecha):
        if dia_tiene_conforme(user.id, fecha):
            raise FichajeLedgerError('Esta jornada ya está firmada.')
        raise FichajeLedgerError(
            'Solo puedes firmar la jornada cuando hayas fichado entrada y salida.'
        )

    registrar_evento(
        user_id=user.id,
        tipo=EVENTO_CONFORME_JORNADA,
        origen=ORIGEN_PWA,
        fecha_laboral=fecha,
        autor_id=user.id,
        ip=ip,
        dispositivo=dispositivo,
        motivo='Conforme del trabajador con el registro de jornada del día.',
    )
    db.session.commit()
    return estado_para_pantalla(user, fecha)


def historial(user_id, desde=None, hasta=None):
    """
    Los registros del trabajador, día a día.

    La norma exige que pueda consultarlos en cualquier momento, así que esto
    no depende de que la empresa le dé permiso.
    """
    hasta = hasta or today_local()
    desde = desde or (hasta - timedelta(days=30))

    por_dia = eventos_del_periodo(user_id, desde, hasta)

    dias = []
    for fecha in sorted(por_dia, reverse=True):
        eventos = por_dia[fecha]
        entradas = [e for e in eventos if e.tipo == EVENTO_ENTRADA]
        salidas = [e for e in eventos if e.tipo == EVENTO_SALIDA]
        conformes = [e for e in eventos if e.tipo == EVENTO_CONFORME_JORNADA]
        dias.append({
            'fecha': fecha,
            'entrada': entradas[0].ocurrido_en if entradas else None,
            'salida': salidas[-1].ocurrido_en if salidas else None,
            'obra': entradas[0].obra if entradas else None,
            'minutos': minutos_de(eventos),
            'eventos': eventos,
            'conforme': bool(conformes),
            'conforme_en': conformes[-1].ocurrido_en if conformes else None,
            'puede_conformar': (
                bool(entradas and salidas)
                and not conformes
                and fecha == today_local()
            ),
        })

    return {
        'desde': desde,
        'hasta': hasta,
        'dias': dias,
        'minutos_totales': sum(d['minutos'] for d in dias),
        'generado_en': utc_now(),
    }


def borrar_fichaje_tutorial(dni, fecha=None):
    """
    Quita el fichaje de prueba del recorrido inicial.

    La persona y la obra se quedan; el marcaje no es un fichaje real y no
    debe permanecer en el libro ni en auditoría.
    """
    from sqlalchemy import func, text

    from app.ddl import desproteger_libro_fichajes, proteger_libro_fichajes
    from app.models import FichajeEvento, User

    dni = (dni or '').strip().upper()
    if not dni:
        return False

    user = User.query.filter(func.upper(User.dni) == dni).first()
    if user is None or getattr(user, 'is_deleted', False):
        return False
    if user.role == 'admin':
        return False

    fecha = fecha or today_local()

    RegistroFichaje.query.filter_by(user_id=user.id, fecha=fecha).delete(
        synchronize_session=False
    )

    schema = db.session.execute(text('SELECT current_schema()')).scalar()
    if not schema or schema == 'public':
        db.session.commit()
        return True

    desproteger_libro_fichajes(
        lambda sql: db.session.execute(text(sql)),
        schema,
    )
    try:
        FichajeEvento.query.filter(
            FichajeEvento.user_id == user.id,
            FichajeEvento.fecha_laboral == fecha,
        ).delete(synchronize_session=False)
        restantes = (
            FichajeEvento.query
            .order_by(FichajeEvento.secuencia.asc(), FichajeEvento.id.asc())
            .all()
        )
        # Dos pases: la secuencia es única y no se puede pisar al compactar.
        for i, evento in enumerate(restantes, start=1):
            evento.secuencia = 1_000_000 + i
        db.session.flush()
        prev_hash = None
        for i, evento in enumerate(restantes, start=1):
            evento.secuencia = i
            evento.hash_previo = prev_hash
            evento.hash = evento.calcular_hash()
            prev_hash = evento.hash
        db.session.flush()
    finally:
        proteger_libro_fichajes(
            lambda sql: db.session.execute(text(sql)),
            schema,
        )

    db.session.commit()
    return True

