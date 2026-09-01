# app/utils/obra_geo.py

UBICACION_MAX_LEN = 100


def _float_or_none(valor):
    if valor in (None, ''):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def truncar_ubicacion(texto):
    if not texto:
        return None
    texto = str(texto).strip()
    if not texto:
        return None
    return texto[:UBICACION_MAX_LEN]


def parse_obra_geo_form(form):
    lat = _float_or_none(form.get('latitud'))
    lng = _float_or_none(form.get('longitud'))

    if lat is None and lng is None:
        return None, None
    if lat is None or lng is None:
        return None, None
    return lat, lng


def aplicar_obra_geo_form(obra, form):
    lat, lng = parse_obra_geo_form(form)
    obra.latitud = lat
    obra.longitud = lng
    ubicacion = truncar_ubicacion(form.get('ubicacion'))
    if ubicacion:
        obra.ubicacion = ubicacion


def aplicar_obra_geo_json(obra, data):
    lat = _float_or_none(data.get('latitud'))
    lng = _float_or_none(data.get('longitud'))
    ubicacion = truncar_ubicacion(data.get('ubicacion'))
    limpiar = data.get('limpiar') in (True, 'true', '1', 1)

    if limpiar:
        obra.latitud = None
        obra.longitud = None
        obra.ubicacion = None
        return

    if lat is None or lng is None:
        raise ValueError('Marca un punto en el mapa antes de guardar la ubicación.')

    obra.latitud = lat
    obra.longitud = lng
    obra.ubicacion = ubicacion
