# app/services/fichaje_operario_service.py
#
# Lo que el trabajador puede hacer desde su móvil: fichar y consultar sus
# propios registros. Se apoya en el libro de eventos, que es quien garantiza
# que lo fichado no se puede alterar después.
#
# El acceso de operarios está apagado por defecto en cada tenant. Se enciende
# desde Configuración, y hasta entonces el rol 'operario' sigue sin poder
# entrar en la aplicación, igual que antes.

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
CONFIG_FICHAJE_ASKED = 'onboarding_fichaje_asked'

# Misma etiqueta que el sync de Odoo: el cuadrante refleja el fichaje físico.
CONTEXTO_FICHAJE_PWA = 'Auto-asignación por Fichaje Físico'

GEO_DESACTIVADA = 'desactivada'
GEO_OPCIONAL = 'opcional'
GEO_OBLIGATORIA = 'obligatoria'
GEO_OPCIONES = (GEO_DESACTIVADA, GEO_OPCIONAL, GEO_OBLIGATORIA)

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
    Si no está activado en el tenant, no enseñamos sus ajustes ni abrimos /mi.
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
    from app.services.plan_service import plan_incluye_geolocalizacion

    if not plan_incluye_geolocalizacion():
        return GEO_DESACTIVADA
    valor = str(get_tenant_config(CONFIG_FICHAJE_GEO, default=GEO_DESACTIVADA))
    return valor if valor in GEO_OPCIONES else GEO_DESACTIVADA


def obras_del_dia(user_id, fecha=None):
    """Obras en las que el trabajador está planificado hoy."""
    fecha = fecha or today_local()
    return (
        Obra.query
        .join(Asignacion, Asignacion.obra_id == Obra.id)
        .filter(Asignacion.user_id == user_id, Asignacion.fecha == fecha)
        .order_by(Obra.nombre.asc())
        .all()
    )


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
    fecha = fecha or today_local()
    estado = jornada_abierta(user.id, fecha)
    planificadas, otras = obras_seleccionables(user.id, fecha)

    obra_actual = None
    if estado['obra_id']:
        obra_actual = Obra.query.filter_by(id=estado['obra_id']).first()

    return {
        'estado': estado['estado'],
        'desde': estado['desde'],
        'minutos': estado['minutos'],
        'fecha': fecha,
        'obra_actual': obra_actual,
        'obras_planificadas': planificadas,
        'otras_obras': otras,
        'modo_geo': modo_geolocalizacion(),
        'eventos': eventos_del_dia(user.id, fecha),
        'conforme': dia_tiene_conforme(user.id, fecha),
        'puede_conformar': puede_conformar_jornada(user.id, fecha),
    }


def _validar_transicion(user_id, tipo, fecha):
    estado = jornada_abierta(user_id, fecha)['estado']
    if estado not in _TRANSICIONES.get(tipo, ()):
        raise FichajeLedgerError(_MENSAJE_TRANSICION.get(tipo, 'Acción no permitida.'))


def _validar_geo(latitud, longitud):
    modo = modo_geolocalizacion()
    if modo == GEO_DESACTIVADA:
        return None, None, None
    if modo == GEO_OBLIGATORIA and (latitud is None or longitud is None):
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
           precision_metros=None, ip=None, dispositivo=None):
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

    registrar_evento(
        user_id=user.id,
        tipo=tipo,
        origen=ORIGEN_PWA,
        fecha_laboral=fecha,
        obra_id=obra.id if obra else obra_id,
        latitud=latitud,
        longitud=longitud,
        precision_metros=precision_metros,
        ip=ip,
        dispositivo=dispositivo,
    )

    if tipo == EVENTO_ENTRADA and obra is not None:
        # ¿Ya estaba en el cuadrante de esa obra? Si no:
        # - plan en otra obra hoy → Conflicto (desviación)
        # - sin plan en todo el día → Paracaidista (sin planificar)
        ya_planificado = Asignacion.query.filter_by(
            user_id=user.id, obra_id=obra.id, fecha=fecha,
        ).first() is not None
        plan_otro = Asignacion.query.filter(
            Asignacion.user_id == user.id,
            Asignacion.fecha == fecha,
            Asignacion.obra_id != obra.id,
        ).first()
        asegurar_asignacion_por_fichaje(user, obra.id, fecha)
        proyectar_dia(user.id, fecha)
        registro = RegistroFichaje.query.filter_by(
            user_id=user.id, fecha=fecha,
        ).first()
        if registro is not None:
            if ya_planificado:
                registro.estado = 'Correcto'
                registro.obra_planificada_id = obra.id
            elif plan_otro:
                registro.estado = 'Conflicto'
                registro.obra_planificada_id = plan_otro.obra_id
                registro.obra_real_id = obra.id
            else:
                registro.estado = 'Paracaidista'
                # El cuadrante ya tiene la asignación; en auditoría sigue
                # como «sin planificar» hasta que alguien lo acepte.
                registro.obra_planificada_id = None
                registro.obra_real_id = obra.id
        db.session.commit()
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
