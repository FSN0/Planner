"""Auditoría de fichajes: cumplimiento del plan y calidad de la planificación.

Responde a: ¿se ficha donde se planificó?, ¿qué jefes de obra planifican bien?,
¿cuánto tiene que corregir RRHH en Odoo?, ¿quién acumula incidencias?

Todo sale de `RegistroFichaje` (una fila por pata de plan o por fichaje), que ya
conserva el historial de plan contra realidad; aquí solo se agrega.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from app.models import Obra, RegistroFichaje, User
from app.services.auditoria_casos_service import parsear_correccion_odoo

_CUMPLE = ('Correcto', 'Retraso')
_OTRA_OBRA = ('Conflicto', 'Disputa', 'Resuelto_Movido')
_SIN_PLANIFICAR = ('Paracaidista', 'Resuelto_Asignado', 'Aceptado_Odoo')
_SIN_PLAN_NO_CUENTA = ('Exento_Ausencia', 'Sin_Registro')

# Umbrales de «lectura» por jefe (sobre días-persona planificados).
_UMBRAL_SIN_PLAN = 0.10
_UMBRAL_CORRECCIONES = 0.08
_UMBRAL_CUMPLIMIENTO_BAJO = 85.0
_UMBRAL_CUMPLIMIENTO_BUENO = 93.0


def _lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _pct(parte: int, total: int) -> float | None:
    return round(100.0 * parte / total, 1) if total else None


def _nombre(u) -> str:
    return f"{(u.name or '').strip()} {(u.lastname or '').strip()}".strip() if u else ''


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _lectura(planificados: int, cumple: int, sin_plan: int, correcciones: int) -> tuple[str, str]:
    """Texto breve y tono (ok/warn/bad/neutral) para la fila de un jefe de obra."""
    if not planificados:
        return ('Sin días planificados en el periodo', 'neutral')
    pct = 100.0 * cumple / planificados
    if sin_plan / planificados >= _UMBRAL_SIN_PLAN:
        return ('Mucha gente ficha sin estar planificada', 'bad')
    if correcciones / planificados >= _UMBRAL_CORRECCIONES:
        return ('RRHH corrige a menudo su planificación', 'warn')
    if pct < _UMBRAL_CUMPLIMIENTO_BAJO:
        return ('Bajo cumplimiento del plan', 'bad')
    if pct >= _UMBRAL_CUMPLIMIENTO_BUENO:
        return ('Planificación fiable', 'ok')
    return ('Cumplimiento aceptable', 'neutral')


class _Nota:
    """Adaptador mínimo para reutilizar `parsear_correccion_odoo` sin cargar la fila."""

    __slots__ = ('notas_resolucion',)

    def __init__(self, notas):
        self.notas_resolucion = notas


def _ids_por_busqueda(q_text: str) -> tuple[set[int] | None, set[int] | None]:
    """User ids y obra ids que coinciden con la búsqueda (None = sin filtro)."""
    from sqlalchemy import and_, func, or_

    q_text = ' '.join((q_text or '').split())
    if not q_text:
        return None, None
    like = f'%{q_text}%'
    blob = func.concat(
        func.coalesce(User.name, ''), ' ',
        func.coalesce(User.lastname, ''), ' ',
        func.coalesce(User.dni, ''),
    )
    tokens = [t for t in q_text.split() if t]
    user_match = or_(
        User.name.ilike(like),
        User.lastname.ilike(like),
        User.dni.ilike(like),
        blob.ilike(like),
    )
    if len(tokens) > 1:
        user_match = or_(user_match, and_(*[blob.ilike(f'%{tok}%') for tok in tokens]))
    user_ids = {u.id for u in User.query.with_entities(User.id).filter(user_match).limit(500)}
    obra_ids = {
        o.id for o in Obra.query.with_entities(Obra.id).filter(
            or_(Obra.codigo.ilike(like), Obra.nombre.ilike(like)),
        ).limit(500)
    }
    return user_ids, obra_ids


def calcular_cumplimiento(desde: date, hasta: date, *, scope_clause=None, hoy: date, q: str = '') -> dict:
    """Agrega cumplimiento y calidad de planificación entre `desde` y `hasta`.

    El día en curso se excluye: aún puede cambiar. `scope_clause` aplica el
    alcance de obras de quien mira (un jefe solo se ve a sí mismo).
    `q` filtra por persona (nombre/DNI) u obra.
    """
    from sqlalchemy import and_, or_

    hasta = min(hasta, hoy - timedelta(days=1))
    if desde > hasta:
        desde = hasta

    query = RegistroFichaje.query.with_entities(
        RegistroFichaje.user_id,
        RegistroFichaje.fecha,
        RegistroFichaje.obra_planificada_id,
        RegistroFichaje.obra_real_id,
        RegistroFichaje.estado,
        RegistroFichaje.notas_resolucion,
    ).filter(
        RegistroFichaje.fecha >= desde,
        RegistroFichaje.fecha <= hasta,
    )
    if scope_clause is not None:
        query = query.filter(scope_clause)
    user_ids, obra_ids_q = _ids_por_busqueda(q)
    if user_ids is not None:
        # Sin coincidencias → vacío; si hay, persona O obra mencionada.
        if not user_ids and not obra_ids_q:
            query = query.filter(RegistroFichaje.id == -1)
        else:
            partes = []
            if user_ids:
                partes.append(RegistroFichaje.user_id.in_(user_ids))
            if obra_ids_q:
                partes.append(or_(
                    RegistroFichaje.obra_planificada_id.in_(obra_ids_q),
                    RegistroFichaje.obra_real_id.in_(obra_ids_q),
                ))
            query = query.filter(or_(*partes))
    filas = query.all()

    obra_ids: set[int] = set()
    for f in filas:
        for oid in (f.obra_planificada_id, f.obra_real_id):
            if oid:
                obra_ids.add(oid)
        if f.estado == 'Sobreescrito_RRHH':
            antes = _int_or_none((f.notas_resolucion or '').split('||')[0])
            if antes:
                obra_ids.add(antes)
    obras = {o.id: o for o in Obra.query.filter(Obra.id.in_(obra_ids)).all()} if obra_ids else {}

    def jefe_de(oid):
        o = obras.get(oid)
        return o.jefe_obra_id if o else None

    semanas = defaultdict(lambda: defaultdict(int))
    jefes = defaultdict(lambda: defaultdict(int))
    jefe_obras = defaultdict(set)
    personas = defaultdict(lambda: defaultdict(int))
    total = defaultdict(int)

    for f in filas:
        est = f.estado or ''
        sem = _lunes(f.fecha)
        plan_id, real_id = f.obra_planificada_id, f.obra_real_id
        jp, jr = jefe_de(plan_id), jefe_de(real_id)

        if plan_id and est not in _SIN_PLAN_NO_CUENTA:
            semanas[sem]['planificados'] += 1
            total['planificados'] += 1
            if jp:
                jefes[jp]['planificados'] += 1
                jefe_obras[jp].add(plan_id)
            if est in _CUMPLE:
                semanas[sem]['cumple'] += 1
                total['cumple'] += 1
                if jp:
                    jefes[jp]['cumple'] += 1

        if est == 'Falta':
            semanas[sem]['faltas'] += 1
            total['faltas'] += 1
            personas[f.user_id]['faltas'] += 1
            if jp:
                jefes[jp]['faltas'] += 1

        if est in _OTRA_OBRA and plan_id and real_id and plan_id != real_id:
            total['otra_obra'] += 1
            personas[f.user_id]['otra_obra'] += 1

        es_sin_plan = est in _SIN_PLANIFICAR or (
            real_id and not plan_id
            and est not in _SIN_PLAN_NO_CUENTA and est != 'Sobreescrito_RRHH'
        )
        if es_sin_plan:
            semanas[sem]['sin_planificar'] += 1
            total['sin_planificar'] += 1
            personas[f.user_id]['sin_planificar'] += 1
            if jr:
                jefes[jr]['sin_planificar'] += 1
                jefe_obras[jr].add(real_id)

        if est == 'Aceptado_Odoo':
            semanas[sem]['alta_no_planificada'] += 1
            total['correcciones'] += 1
        elif est == 'Sobreescrito_RRHH':
            corr = parsear_correccion_odoo(_Nota(f.notas_resolucion))
            clave = 'borrado' if corr['borrado'] else 'cambio_obra'
            semanas[sem][clave] += 1
            total['correcciones'] += 1
            antes = _int_or_none(corr['obra_antes_id'])
            ja = jefe_de(antes)
            if ja:
                jefes[ja]['correcciones'] += 1
                jefe_obras[ja].add(antes)

    # Serie semanal continua (también semanas sin datos).
    etiquetas, cumplimiento, cambio_obra, borrado, alta, faltas = [], [], [], [], [], []
    cur = _lunes(desde)
    lunes_fin = _lunes(hasta)
    while cur <= lunes_fin:
        s = semanas.get(cur, {})
        etiquetas.append(cur.strftime('%d/%m'))
        cumplimiento.append(_pct(s.get('cumple', 0), s.get('planificados', 0)))
        cambio_obra.append(s.get('cambio_obra', 0))
        borrado.append(s.get('borrado', 0))
        alta.append(s.get('alta_no_planificada', 0))
        faltas.append(s.get('faltas', 0))
        cur += timedelta(days=7)

    # Tabla por jefe de obra.
    jefe_users = {
        u.id: u for u in User.query.filter(User.id.in_(list(jefes.keys()))).all()
    } if jefes else {}
    tabla_jefes = []
    for jid, m in jefes.items():
        planificados = m['planificados']
        lectura, tono = _lectura(planificados, m['cumple'], m['sin_planificar'], m['correcciones'])
        nombres_obra = sorted({(obras[o].nombre or '').strip() for o in jefe_obras[jid] if o in obras})
        extra = f' +{len(nombres_obra) - 3}' if len(nombres_obra) > 3 else ''
        tabla_jefes.append({
            'jefe_id': jid,
            'jefe': _nombre(jefe_users.get(jid)) or f'Jefe #{jid}',
            'obras': ', '.join(nombres_obra[:3]) + extra,
            'planificados': planificados,
            'cumplimiento': _pct(m['cumple'], planificados),
            'sin_planificar': m['sin_planificar'],
            'correcciones': m['correcciones'],
            'faltas': m['faltas'],
            'lectura': lectura,
            'tono': tono,
        })
    # Los que más atención piden, primero.
    peso_tono = {'bad': 0, 'warn': 1, 'neutral': 2, 'ok': 3}
    tabla_jefes.sort(key=lambda r: (peso_tono[r['tono']], -(r['sin_planificar'] + r['correcciones'])))

    # Personas con más incidencias.
    user_rows = {
        u.id: u for u in User.query.filter(User.id.in_(list(personas.keys()))).all()
    } if personas else {}
    tabla_personas = []
    for uid, m in personas.items():
        if not (m['faltas'] or m['otra_obra'] or m['sin_planificar']):
            continue
        tabla_personas.append({
            'user_id': uid,
            'persona': _nombre(user_rows.get(uid)) or f'#{uid}',
            'faltas': m['faltas'],
            'otra_obra': m['otra_obra'],
            'sin_planificar': m['sin_planificar'],
        })
    tabla_personas.sort(key=lambda r: (-r['faltas'], -r['otra_obra'], -r['sin_planificar']))

    return {
        'desde': desde.isoformat(),
        'hasta': hasta.isoformat(),
        'kpis': {
            'planificados': total['planificados'],
            'cumplimiento': _pct(total['cumple'], total['planificados']),
            'sin_planificar': total['sin_planificar'],
            'correcciones': total['correcciones'],
            'faltas': total['faltas'],
            'otra_obra': total['otra_obra'],
        },
        'semanas': etiquetas,
        'serie': {
            'cumplimiento': cumplimiento,
            'cambio_obra': cambio_obra,
            'borrado': borrado,
            'alta_no_planificada': alta,
            'faltas': faltas,
        },
        'jefes': tabla_jefes,
        'personas': tabla_personas[:12],
    }
