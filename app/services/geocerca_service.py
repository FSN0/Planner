# app/services/geocerca_service.py
#
# Geocerca por obra: distancia al fichar, sugerencia de obra cercana y estado
# de auditoría. No bloquea el fichaje salvo que el tenant exija GPS.

import math

from app.models import EVENTO_ENTRADA, FichajeEvento, Obra
from app.services.config_service import get_tenant_config

CONFIG_GEOCERCA_RADIO = 'fichaje_geocerca_radio_default'
RADIO_DEFAULT_METROS = 150

GEO_NO_APLICA = 'no_aplica'
GEO_SIN_UBICACION = 'sin_ubicacion'
GEO_COINCIDE = 'coincide'
GEO_DUDOSA = 'dudosa'
GEO_OBRA_SIN_GEO = 'obra_sin_geo'


def radio_default_metros():
    try:
        valor = int(get_tenant_config(CONFIG_GEOCERCA_RADIO, default=RADIO_DEFAULT_METROS))
    except (TypeError, ValueError):
        valor = RADIO_DEFAULT_METROS
    return max(25, min(valor, 5000))


def obra_tiene_geolocalizacion(obra):
    if obra is None:
        return False
    return obra.latitud is not None and obra.longitud is not None


def radio_obra_metros(obra):
    return radio_default_metros()


def distancia_metros(lat1, lon1, lat2, lon2):
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def tenant_tiene_obras_geolocalizadas():
    return (
        Obra.query
        .filter(
            Obra.is_deleted.is_(False),
            Obra.latitud.isnot(None),
            Obra.longitud.isnot(None),
        )
        .limit(1)
        .first()
        is not None
    )


def geocerca_activa():
    from app.services.fichaje_operario_service import geolocalizacion_activa
    return geolocalizacion_activa() and tenant_tiene_obras_geolocalizadas()


def distancia_a_obra(obra, latitud, longitud):
    if not obra_tiene_geolocalizacion(obra):
        return None
    return distancia_metros(latitud, longitud, obra.latitud, obra.longitud)


def obra_en_radio(obra, latitud, longitud):
    distancia = distancia_a_obra(obra, latitud, longitud)
    if distancia is None:
        return False, None
    return distancia <= radio_obra_metros(obra), distancia


def evaluar_geo_fichaje(obra, latitud, longitud):
    from app.services.fichaje_operario_service import geolocalizacion_activa

    if not geolocalizacion_activa():
        return GEO_NO_APLICA, None
    if latitud is None or longitud is None:
        return GEO_SIN_UBICACION, None
    if not geocerca_activa():
        return GEO_NO_APLICA, None
    if not obra_tiene_geolocalizacion(obra):
        return GEO_OBRA_SIN_GEO, None

    dentro, distancia = obra_en_radio(obra, latitud, longitud)
    if dentro:
        return GEO_COINCIDE, distancia
    return GEO_DUDOSA, distancia


def obras_en_radio(latitud, longitud, obras):
    if latitud is None or longitud is None:
        return []

    cercanas = []
    for obra in obras:
        dentro, distancia = obra_en_radio(obra, latitud, longitud)
        if dentro:
            cercanas.append({'obra': obra, 'distancia': distancia})

    cercanas.sort(key=lambda item: item['distancia'])
    return cercanas


def ultima_obra_entrada_id(user_id, antes_de_fecha):
    evento = (
        FichajeEvento.query
        .filter(
            FichajeEvento.user_id == user_id,
            FichajeEvento.tipo == EVENTO_ENTRADA,
            FichajeEvento.obra_id.isnot(None),
            FichajeEvento.fecha_laboral < antes_de_fecha,
        )
        .order_by(FichajeEvento.ocurrido_en.desc())
        .first()
    )
    return evento.obra_id if evento else None


def preseleccion_obra_id(user_id, fecha, planificadas, otras, latitud=None, longitud=None):
    todas = list(planificadas) + list(otras)
    if not todas:
        return None

    if geocerca_activa() and latitud is not None and longitud is not None:
        cercanas = obras_en_radio(latitud, longitud, todas)
        if not cercanas:
            return None

        ids_cercanas = {item['obra'].id for item in cercanas}
        ultima = ultima_obra_entrada_id(user_id, fecha)
        if ultima in ids_cercanas:
            return ultima

        ids_plan = {o.id for o in planificadas}
        for item in cercanas:
            if item['obra'].id in ids_plan:
                return item['obra'].id

        return cercanas[0]['obra'].id

    if planificadas:
        return planificadas[0].id
    return None


def serializar_obras_geo(obras):
    return [
        {
            'id': o.id,
            'nombre': o.nombre,
            'lat': o.latitud,
            'lng': o.longitud,
            'radio': radio_default_metros() if obra_tiene_geolocalizacion(o) else None,
        }
        for o in obras
        if obra_tiene_geolocalizacion(o)
    ]


def normalizar_modo_geo_config(valor):
    valor = str(valor or '').strip().lower()
    if valor in ('activada', 'opcional', 'obligatoria', 'sí', 'si', 'true', '1'):
        return 'activada'
    return 'desactivada'


def modo_geo_exigir_desde_config(valor_geo):
    return str(valor_geo or '').strip().lower() == 'obligatoria'
