# app/services/mapa_fichajes_service.py
#
# Mapa consultivo: obras geolocalizadas y entradas con GPS por obra.

from datetime import date, timedelta

from app.models import EVENTO_ENTRADA, FichajeEvento, Obra, ROLE_JEFE, User
from app.services.fichaje_ledger_service import vigentes
from app.services.geocerca_service import (
    GEO_COINCIDE,
    GEO_DUDOSA,
    obra_tiene_geolocalizacion,
    radio_default_metros,
)
from app.utils.timezone_utils import today_local


MAX_RANGO_DIAS = 90
DEFAULT_RANGO_DIAS = 1


def _obras_query(user):
    q = Obra.query.filter(Obra.is_deleted.is_(False))
    if user and getattr(user, 'role', None) == ROLE_JEFE:
        q = q.filter(Obra.jefe_obra_id == user.id)
    return q


def _obra_visible(obra_id, user):
    return _obras_query(user).filter(Obra.id == obra_id).first()


def normalizar_rango(fecha_desde, fecha_hasta):
    today = today_local()
    if fecha_desde is None:
        fecha_desde = today
    if fecha_hasta is None:
        fecha_hasta = fecha_desde
    if fecha_hasta < fecha_desde:
        fecha_desde, fecha_hasta = fecha_hasta, fecha_desde
    if (fecha_hasta - fecha_desde).days > MAX_RANGO_DIAS:
        fecha_desde = fecha_hasta - timedelta(days=MAX_RANGO_DIAS)
    return fecha_desde, fecha_hasta


def listar_obras_mapa(user):
    obras = _obras_query(user).order_by(Obra.nombre.asc()).all()
    con_ubicacion = []
    sin_ubicacion = []
    for obra in obras:
        base = {
            'id': obra.id,
            'nombre': obra.nombre,
            'codigo': obra.codigo or '',
        }
        if obra_tiene_geolocalizacion(obra):
            con_ubicacion.append({
                **base,
                'lat': obra.latitud,
                'lng': obra.longitud,
                'ubicacion': obra.ubicacion or '',
            })
        else:
            sin_ubicacion.append(base)
    return {
        'obras': con_ubicacion,
        'sin_ubicacion': sin_ubicacion,
        'radio_metros': radio_default_metros(),
    }


def fichajes_mapa_obra(obra_id, user, fecha_desde=None, fecha_hasta=None, solo_dudosos=False):
    obra = _obra_visible(obra_id, user)
    if obra is None:
        return None

    fecha_desde, fecha_hasta = normalizar_rango(fecha_desde, fecha_hasta)

    eventos = (
        FichajeEvento.query
        .filter(
            FichajeEvento.obra_id == obra_id,
            FichajeEvento.fecha_laboral >= fecha_desde,
            FichajeEvento.fecha_laboral <= fecha_hasta,
        )
        .all()
    )
    entradas = [e for e in vigentes(eventos) if e.tipo == EVENTO_ENTRADA]

    user_ids = {e.user_id for e in entradas}
    users = {
        u.id: u
        for u in User.query.filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    puntos = []
    stats = {
        'entradas': len(entradas),
        'con_gps': 0,
        'sin_gps': 0,
        'coincide': 0,
        'dudosa': 0,
        'otros': 0,
    }

    for ev in entradas:
        if ev.latitud is None or ev.longitud is None:
            stats['sin_gps'] += 1
            continue
        stats['con_gps'] += 1
        estado = ev.geo_estado or ''
        if estado == GEO_COINCIDE:
            stats['coincide'] += 1
        elif estado == GEO_DUDOSA:
            stats['dudosa'] += 1
        else:
            stats['otros'] += 1

        if solo_dudosos and estado != GEO_DUDOSA:
            continue

        u = users.get(ev.user_id)
        nombre = f'{u.name} {u.lastname}'.strip() if u else f'#{ev.user_id}'
        puntos.append({
            'id': ev.id,
            'lat': ev.latitud,
            'lng': ev.longitud,
            'user_id': ev.user_id,
            'user_nombre': nombre,
            'fecha': ev.fecha_laboral.isoformat(),
            'hora': ev.ocurrido_en.strftime('%H:%M') if ev.ocurrido_en else '',
            'geo_estado': estado,
            'distancia_metros': ev.distancia_obra_metros,
            'nota': (ev.nota_ubicacion or '').strip() or None,
            'precision_metros': ev.precision_metros,
        })

    return {
        'obra': {
            'id': obra.id,
            'nombre': obra.nombre,
            'codigo': obra.codigo or '',
            'lat': obra.latitud,
            'lng': obra.longitud,
            'ubicacion': obra.ubicacion or '',
            'tiene_pin': obra_tiene_geolocalizacion(obra),
        },
        'desde': fecha_desde.isoformat(),
        'hasta': fecha_hasta.isoformat(),
        'radio_metros': radio_default_metros(),
        'puntos': puntos,
        'stats': stats,
        'solo_dudosos': bool(solo_dudosos),
    }
