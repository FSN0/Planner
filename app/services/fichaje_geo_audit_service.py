# app/services/fichaje_geo_audit_service.py
#
# Datos de geocerca para la auditoría de fichajes (a partir del evento de entrada).

from app.models import EVENTO_ANULACION, EVENTO_ENTRADA, FichajeEvento
from app.services.geocerca_service import (
    GEO_COINCIDE,
    GEO_DUDOSA,
    GEO_NO_APLICA,
    GEO_OBRA_SIN_GEO,
    GEO_SIN_UBICACION,
    geocerca_activa,
)


def _clave(user_id, fecha):
    return (int(user_id), fecha)


def entrada_geo_por_registros(registros):
    """
    Devuelve {registro_id: dict} con el geo de la entrada del día.

    Solo tiene sentido mostrar algo cuando la geocerca está activa en el tenant.
    """
    if not registros or not geocerca_activa():
        return {}

    pares = {_clave(r.user_id, r.fecha) for r in registros}
    if not pares:
        return {}

    user_ids = {p[0] for p in pares}
    fechas = {p[1] for p in pares}

    eventos = (
        FichajeEvento.query
        .filter(
            FichajeEvento.tipo == EVENTO_ENTRADA,
            FichajeEvento.user_id.in_(user_ids),
            FichajeEvento.fecha_laboral.in_(fechas),
        )
        .order_by(FichajeEvento.ocurrido_en.asc(), FichajeEvento.secuencia.asc())
        .all()
    )

    anulaciones = (
        FichajeEvento.query
        .filter(
            FichajeEvento.tipo == EVENTO_ANULACION,
            FichajeEvento.evento_anulado_id.isnot(None),
            FichajeEvento.user_id.in_(user_ids),
            FichajeEvento.fecha_laboral.in_(fechas),
        )
        .all()
    )
    anulados = {a.evento_anulado_id for a in anulaciones}

    por_par = {}
    for ev in eventos:
        if ev.id in anulados:
            continue
        por_par[_clave(ev.user_id, ev.fecha_laboral)] = ev

    resultado = {}
    for reg in registros:
        ev = por_par.get(_clave(reg.user_id, reg.fecha))
        if ev is None:
            continue
        resultado[reg.id] = {
            'geo_estado': ev.geo_estado or GEO_NO_APLICA,
            'distancia_metros': ev.distancia_obra_metros,
            'nota_ubicacion': ev.nota_ubicacion,
            'latitud': ev.latitud,
            'longitud': ev.longitud,
            'precision_metros': ev.precision_metros,
        }
    return resultado


def contar_geo_dudosa(geo_por_registro):
    return sum(
        1 for g in geo_por_registro.values()
        if g.get('geo_estado') == GEO_DUDOSA
    )


def etiqueta_geo_audit(geo_info):
    """Texto corto para ordenar/filtrar en tablas."""
    if not geo_info:
        return ''
    estado = geo_info.get('geo_estado') or GEO_NO_APLICA
    if estado == GEO_DUDOSA:
        dist = geo_info.get('distancia_metros')
        if dist is not None:
            return f'dudosa {int(round(dist))}m'
        return 'dudosa'
    if estado == GEO_COINCIDE:
        return 'ok'
    if estado == GEO_SIN_UBICACION:
        return 'sin gps'
    if estado == GEO_OBRA_SIN_GEO:
        return 'obra sin mapa'
    return ''
