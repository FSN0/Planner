"""
Agregación visual del estado de fichaje de un día.

Un trabajador puede tener varias filas RegistroFichaje el mismo día
(multi-obra, paracaidista + plan, etc.). El calendario del trabajador ya
elige un color “final”; el tablero debe usar la misma precedencia.

Ejes de color (relleno de la pelotita):
  rojo    → incidencia grave sin resolver
  naranja → pendiente de decisión humana
  verde   → cerrado OK sin intervención (o resuelto por admin en auditoría)
  violeta → cerrado con intervención humana (p. ej. sobrescrito desde ERP/RRHH)
  gris    → sin datos / solo semillas de sync
"""

# Cerrado OK (incluye resoluciones de auditoría SignaPlan).
FICHAJE_OK = {
    'Correcto',
    'Correcto_Automatico',
    'Cambio_Tajo',
    'Resuelto_Movido',
    'Resuelto_Asignado',
    'Resuelto_Dividido',
    'Resuelto_Ignorado',
    'Resuelto_Falta',
    'Resuelto_Ausencia',
    'Exento_Ausencia',
    'Cerrado_Multiobra',
}

# Cerrado tras intervención externa (RRHH/ERP). Color propio: violeta.
FICHAJE_INTERVENCION = {
    'Sobreescrito_RRHH',
}

# Falta confirmada (planificado + no fichó). Distinto de presencia OK.
FICHAJE_FALTA = {'Falta'}

FICHAJE_ROJO = {'Conflicto', 'Disputa', 'Paracaidista'}
FICHAJE_NARANJA = {'Ausencia', 'Pendiente', 'Retraso'}

# Semillas de sync: no cuentan si el día ya tiene un fichaje/resolución real.
FICHAJE_SEMILLA = {'Sin_Registro'}

COLOR_ROJO = '#ef4444'
COLOR_NARANJA = '#f59e0b'
COLOR_VERDE = '#10b981'
COLOR_VIOLETA = '#7c3aed'
COLOR_FALTA = '#e11d48'
COLOR_GRIS = '#94a3b8'


def _es_ok(est):
    return est in FICHAJE_OK or (est or '').startswith('Resuelto')


def _es_intervencion(est):
    return est in FICHAJE_INTERVENCION


def _filtrar_semillas(limpios):
    """
    Si el día ya tiene un estado “real” (OK, intervención, rojo o naranja),
    las filas Sin_Registro son artefactos de planificación multi-obra y
    no deben teñir la pelotita de naranja.
    """
    tiene_real = any(
        _es_ok(e) or _es_intervencion(e) or e in FICHAJE_ROJO or e in FICHAJE_NARANJA
        for e in limpios
    )
    if not tiene_real:
        return limpios
    return [e for e in limpios if e not in FICHAJE_SEMILLA]


def estado_fichaje_agregado(estados):
    """
    Devuelve un único estado representativo del día para pintar la pelotita.

    Precedencia: rojo > falta > naranja > violeta (intervención) > verde (OK) > gris.
    """
    limpios = [e for e in (estados or []) if e]
    if not limpios:
        return 'Sin_Registro'

    limpios = _filtrar_semillas(limpios)
    if not limpios:
        return 'Sin_Registro'

    if any(est in FICHAJE_ROJO for est in limpios):
        for est in limpios:
            if est in FICHAJE_ROJO:
                return est

    if any(est in FICHAJE_FALTA for est in limpios):
        return 'Falta'

    if any(est in FICHAJE_NARANJA for est in limpios):
        for est in limpios:
            if est in FICHAJE_NARANJA:
                return est

    if any(_es_intervencion(est) for est in limpios):
        for est in limpios:
            if _es_intervencion(est):
                return est

    if all(_es_ok(est) for est in limpios):
        for preferido in (
            'Correcto',
            'Correcto_Automatico',
            'Cambio_Tajo',
            'Resuelto_Asignado',
            'Resuelto_Movido',
            'Resuelto_Dividido',
            'Resuelto_Falta',
            'Resuelto_Ignorado',
            'Resuelto_Ausencia',
            'Cerrado_Multiobra',
            'Exento_Ausencia',
        ):
            if preferido in limpios:
                return preferido
        return limpios[0]

    if any(_es_ok(est) for est in limpios):
        return 'Correcto'

    if all(est in FICHAJE_SEMILLA for est in limpios):
        return 'Sin_Registro'

    return 'Pendiente'


def color_fichaje_agregado(estados):
    """Misma lógica que el calendario del trabajador (hex)."""
    estado = estado_fichaje_agregado(estados)
    if estado in FICHAJE_ROJO:
        return COLOR_ROJO
    if estado in FICHAJE_FALTA:
        return COLOR_FALTA
    if estado in FICHAJE_NARANJA or estado == 'Pendiente':
        return COLOR_NARANJA
    if estado in FICHAJE_INTERVENCION:
        return COLOR_VIOLETA
    if estado == 'Exento_Ausencia':
        return COLOR_VIOLETA
    if _es_ok(estado):
        return COLOR_VERDE
    if estado == 'Sin_Registro':
        return COLOR_GRIS
    return COLOR_NARANJA


def tooltip_fichaje_agregado(estados):
    """Texto corto para title/tooltip de la pelotita."""
    estado = estado_fichaje_agregado(estados)
    return label_estado_fichaje(estado)


def label_estado_fichaje(estado):
    """Etiqueta legible de un estado de RegistroFichaje."""
    labels = {
        'Correcto': 'Correcto',
        'Correcto_Automatico': 'Correcto (auto)',
        'Cambio_Tajo': 'Cambio de tajo',
        'Conflicto': 'Conflicto',
        'Disputa': 'Disputa entre jefes',
        'Paracaidista': 'Paracaidista',
        'Ausencia': 'Ausencia',
        'Falta': 'Falta',
        'Pendiente': 'Pendiente',
        'Retraso': 'Retraso',
        'Sin_Registro': 'Sin fichaje',
        'Sobreescrito_RRHH': 'Corregido por RRHH / ERP',
        'Exento_Ausencia': 'Exento (ausencia)',
        'Cerrado_Multiobra': 'Multi-obra cerrado',
        'Resuelto_Movido': 'Resuelto (movido)',
        'Resuelto_Asignado': 'Resuelto (asignado)',
        'Resuelto_Dividido': 'Resuelto (multi-obra)',
        'Resuelto_Ignorado': 'Resuelto (ignorado)',
        'Resuelto_Falta': 'Resuelto (desasignado)',
        'Resuelto_Ausencia': 'Resuelto (ausencia)',
    }
    if (estado or '').startswith('Resuelto'):
        return labels.get(estado, 'Resuelto / correcto')
    return labels.get(estado, estado or 'Sin datos')


def fichajes_agregados_por_fecha(fecha):
    """Mapa user_id → estado agregado del día (para planificador móvil, APIs)."""
    from collections import defaultdict

    from app.models import RegistroFichaje

    por_usuario = defaultdict(list)
    for f in RegistroFichaje.query.filter_by(fecha=fecha).all():
        por_usuario[f.user_id].append(f.estado)
    return {
        str(uid): estado_fichaje_agregado(estados)
        for uid, estados in por_usuario.items()
    }


def faltas_confirmadas_set(start_date, end_date, user_ids=None, obra_ids=None,
                           end_exclusive=True):
    """
    Conjunto (user_id, fecha, obra_planificada_id) de faltas confirmadas
    en el rango, para pintar bloques fantasma en calendarios.
    """
    from app.models import RegistroFichaje

    q = RegistroFichaje.query.filter(
        RegistroFichaje.estado == 'Falta',
        RegistroFichaje.obra_planificada_id.isnot(None),
        RegistroFichaje.fecha >= start_date,
    )
    if end_exclusive:
        q = q.filter(RegistroFichaje.fecha < end_date)
    else:
        q = q.filter(RegistroFichaje.fecha <= end_date)
    if user_ids is not None:
        ids = list(user_ids) if not isinstance(user_ids, list) else user_ids
        if not ids:
            return set()
        q = q.filter(RegistroFichaje.user_id.in_(ids))
    if obra_ids is not None:
        oids = list(obra_ids) if not isinstance(obra_ids, list) else obra_ids
        if not oids:
            return set()
        q = q.filter(RegistroFichaje.obra_planificada_id.in_(oids))
    return {
        (r.user_id, r.fecha, r.obra_planificada_id)
        for r in q.all()
    }


TOOLTIP_FALTA = 'Falta confirmada: debía acudir y no fichó'
