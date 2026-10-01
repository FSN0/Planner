# app/services/inercia_service.py
#
# Casa e inercia del cuadrante.
#
# Hecho = fila en asignaciones (alguien lo pintó o el fichaje de hoy).
# Inercia = si el último día laborable estuvo en un tajo y hoy no hay
# decisión nueva, sigue ahí (hacia adelante, como mucho un mes: se recalcula).
# Sirve para pintar fantasmas y para aceptar un fichaje en la casa.
# NO genera ausencias: sin hecho ese día, no se espera a nadie.
# No se arrastra una asignación de hace semanas. El pasado es solo hecho.
# No se materializan filas fantasma. Soltar a Libres persiste un corte.

from collections import defaultdict, namedtuple
from datetime import timedelta

from app import db
from app.models import Asignacion, Festivo, InerciaCorte, Obra, User, ROLE_OPERARIO
from app.utils.timezone_utils import today_local, utc_now

LOOKBACK_DAYS = 31
INERCIA_HORIZONTE_DIAS = 31

ESTADO_CORRECTO = 'Correcto'
ESTADO_INERCIA = 'Correcto_Automatico'
ESTADO_CONFLICTO = 'Conflicto'
ESTADO_PARACAIDISTA = 'Paracaidista'
ESTADO_CAMBIO_TAJO = 'Cambio_Tajo'

# Falta confirmada queda en plan (trazabilidad) pero NO ancla fantasma:
# ese día no estuvo en la obra.
_ESTADOS_NO_ANCLA_INERCIA = frozenset({
    'Falta',
    'Resuelto_Falta',
    'Resuelto_Ausencia',
})

_ESTADOS_OBRA_MUERTA = frozenset({
    'pendiente', 'finalizada', 'cerrada', 'cancelada',
})

ClasificacionEntrada = namedtuple(
    'ClasificacionEntrada',
    ('estado', 'obra_planificada_id', 'materializar'),
)


def clasificar_entrada_fichaje(
    *,
    obra_fichada_id,
    planificado_en_obra_fichada,
    otras_obras_planificadas_ids,
    casa_obra_id,
    aceptar_primer_fichaje=True,
):
    """
    Matriz única PWA / Odoo tras una entrada física.

    1. Hecho hoy en la obra fichada → Correcto
    2. Hecho hoy en otra obra → Conflicto (desvió el plan).
       `obra_planificada_id` es la primera; el llamador debe materializar
       un Conflicto por cada id de `otras_obras_planificadas_ids`.
    3. Sin hecho, ficha en su casa → Correcto_Automatico
    4. Sin hecho ni casa → primer fichaje (auto o Paracaidista)
    5. Sin hecho, ficha fuera de casa → Cambio_Tajo (no es alerta)
    """
    otras = [oid for oid in (otras_obras_planificadas_ids or []) if oid]
    if planificado_en_obra_fichada:
        return ClasificacionEntrada(ESTADO_CORRECTO, obra_fichada_id, False)
    if otras:
        return ClasificacionEntrada(ESTADO_CONFLICTO, otras[0], False)
    if casa_obra_id == obra_fichada_id:
        return ClasificacionEntrada(ESTADO_INERCIA, obra_fichada_id, True)
    if casa_obra_id is None:
        if aceptar_primer_fichaje:
            return ClasificacionEntrada(ESTADO_INERCIA, obra_fichada_id, True)
        return ClasificacionEntrada(ESTADO_PARACAIDISTA, None, False)
    return ClasificacionEntrada(ESTADO_CAMBIO_TAJO, casa_obra_id, True)


def aceptar_primer_fichaje():
    from app.models import ConfiguracionGlobal
    conf = ConfiguracionGlobal.query.filter_by(clave='aceptar_primer_fichaje').first()
    if conf is None:
        return True
    return (conf.valor or '').strip() == 'True'


def es_dia_laborable(fecha, festivos=None):
    if fecha.weekday() >= 5:
        return False
    if festivos is not None:
        return fecha not in festivos
    return Festivo.query.filter_by(fecha=fecha).first() is None


def festivos_en(fecha_inicio, fecha_fin):
    if fecha_inicio > fecha_fin:
        return set()
    return {
        row.fecha
        for row in Festivo.query.filter(
            Festivo.fecha >= fecha_inicio,
            Festivo.fecha <= fecha_fin,
        ).all()
    }


def obra_viva_en(obra, fecha):
    if obra is None or getattr(obra, 'is_deleted', False):
        return False
    estado = (obra.estado or '').strip().lower()
    if estado in _ESTADOS_OBRA_MUERTA:
        return False
    if obra.fecha_inicio and obra.fecha_inicio > fecha:
        return False
    if obra.fecha_fin and obra.fecha_fin < fecha:
        return False
    return True


def cortar_casa(user_id, fecha, autor_id=None):
    """Persiste el corte desde `fecha` (inclusive). Idempotente ese día."""
    ya = InerciaCorte.query.filter_by(user_id=user_id, fecha=fecha).first()
    if ya:
        return ya
    corte = InerciaCorte(user_id=user_id, fecha=fecha, autor_id=autor_id)
    db.session.add(corte)
    db.session.flush()
    return corte


def cortar_casa_fechas(user_id, fechas, autor_id=None):
    n = 0
    for fecha in sorted(set(fechas or [])):
        if cortar_casa(user_id, fecha, autor_id) is not None:
            n += 1
    return n


def cortar_casa_si_inercia(user_id, fecha, obra_id=None, autor_id=None):
    """
    Corta si ese día la persona está (o estaría) en inercia en `obra_id`.

    Si obra_id es None, corta cualquier casa vigente.
    """
    casa = casa_en_fecha(user_id, fecha)
    if casa is None:
        return False
    if obra_id is not None and int(casa) != int(obra_id):
        return False
    cortar_casa(user_id, fecha, autor_id)
    return True


def cortar_casa_de_obra(obra_id, fecha, autor_id=None, user_ids=None):
    """Al pausar/finalizar: quien tenía esa casa deja de heredarla."""
    if user_ids is None:
        user_ids = [
            uid for (uid,) in db.session.query(Asignacion.user_id)
            .filter(Asignacion.obra_id == obra_id)
            .distinct()
            .all()
        ]
    cortes = 0
    casas = casas_en_fecha(user_ids, fecha) if user_ids else {}
    for uid, casa in casas.items():
        if casa == obra_id:
            cortar_casa(uid, fecha, autor_id)
            cortes += 1
    return cortes


def _operario_ids(user_ids=None):
    if user_ids is not None:
        return [int(uid) for uid in user_ids if uid]
    return [
        uid for (uid,) in User.query.filter_by(
            role=ROLE_OPERARIO, active=True, is_deleted=False,
        ).with_entities(User.id).all()
    ]


def _cargar_contexto(user_ids, fecha_inicio, fecha_fin):
    if not user_ids:
        return {}, {}, {}, {}, set()
    lookback_start = fecha_inicio - timedelta(days=LOOKBACK_DAYS)

    asigs = (
        db.session.query(Asignacion.user_id, Asignacion.fecha, Asignacion.obra_id)
        .filter(
            Asignacion.user_id.in_(user_ids),
            Asignacion.fecha >= lookback_start,
            Asignacion.fecha <= fecha_fin,
        )
        .all()
    )
    asigs_por_dia = defaultdict(list)
    for uid, fecha, oid in asigs:
        asigs_por_dia[(uid, fecha)].append(oid)

    from app.models import RegistroFichaje

    faltas_ancla = {
        (uid, fecha, oid)
        for uid, fecha, oid in (
            db.session.query(
                RegistroFichaje.user_id,
                RegistroFichaje.fecha,
                RegistroFichaje.obra_planificada_id,
            )
            .filter(
                RegistroFichaje.user_id.in_(user_ids),
                RegistroFichaje.fecha >= lookback_start,
                RegistroFichaje.fecha <= fecha_fin,
                RegistroFichaje.estado.in_(_ESTADOS_NO_ANCLA_INERCIA),
                RegistroFichaje.obra_planificada_id.isnot(None),
            )
            .all()
        )
        if oid
    }

    anclas_desc = defaultdict(list)
    by_user_dates = defaultdict(set)
    for (uid, fecha) in asigs_por_dia:
        by_user_dates[uid].add(fecha)
    for uid, fechas in by_user_dates.items():
        for dia in sorted(fechas, reverse=True):
            oids = [
                oid for oid in dict.fromkeys(asigs_por_dia[(uid, dia)])
                if (uid, dia, oid) not in faltas_ancla
            ]
            if len(oids) == 1:
                anclas_desc[uid].append((dia, oids[0]))

    cortes = (
        db.session.query(InerciaCorte.user_id, InerciaCorte.fecha)
        .filter(
            InerciaCorte.user_id.in_(user_ids),
            InerciaCorte.fecha >= lookback_start,
            InerciaCorte.fecha <= fecha_fin,
        )
        .all()
    )
    cortes_por_user = defaultdict(list)
    for uid, fecha in cortes:
        cortes_por_user[uid].append(fecha)
    for uid in cortes_por_user:
        cortes_por_user[uid].sort()

    obra_ids = {oid for oids in asigs_por_dia.values() for oid in oids}
    obras = {}
    if obra_ids:
        obras = {o.id: o for o in Obra.query.filter(Obra.id.in_(obra_ids)).all()}

    festivos = festivos_en(lookback_start, fecha_fin)
    return asigs_por_dia, anclas_desc, cortes_por_user, obras, festivos


def _ultimo_corte_hasta(cortes, fecha):
    ultimo = None
    for c in cortes:
        if c <= fecha:
            ultimo = c
        else:
            break
    return ultimo


def _dia_laborable_previo(fecha, festivos=None):
    """Último día laborable estrictamente anterior a `fecha`."""
    d = fecha - timedelta(days=1)
    limite = fecha - timedelta(days=LOOKBACK_DAYS)
    while d >= limite:
        if es_dia_laborable(d, festivos):
            return d
        d -= timedelta(days=1)
    return None


def _ancla_hasta(anclas, fecha):
    """Último día ≤ fecha con exactamente una obra (multi-obra no inventa casa)."""
    for dia, oid in anclas:
        if dia <= fecha:
            return dia, oid
    return None, None


def _casa_desde_contexto(user_id, fecha, anclas_desc, cortes_por_user, obras, festivos=None):
    """
    Casa en `fecha`: la última asignación única no puede ser anterior al
    último laborable antes de hoy (o antes de `fecha` si es pasado).

    Ayer (laborable) en un tajo → sigue ahí. Hace dos semanas y luego parado → no.
    """
    ancla_fecha, ancla_obra = _ancla_hasta(anclas_desc.get(user_id, []), fecha)
    if ancla_obra is None:
        return None
    suelo = fecha if fecha < today_local() else today_local()
    previo = _dia_laborable_previo(suelo, festivos)
    if previo is None or ancla_fecha < previo:
        return None
    # Corte desde `fecha` inclusive: anula anclas de ese día y anteriores
    # para cualquier jornada >= corte.
    ultimo_corte = _ultimo_corte_hasta(cortes_por_user.get(user_id, []), fecha)
    if ultimo_corte is not None and ultimo_corte >= ancla_fecha:
        return None
    obra = obras.get(ancla_obra)
    if not obra_viva_en(obra, fecha):
        return None
    return ancla_obra


def _ausencias_aprobadas_por_user(user_ids, fecha_inicio, fecha_fin):
    """Índice user_id → ausencias aprobadas que solapan el rango."""
    from app.services.leave_service import build_leaves_by_user
    return build_leaves_by_user(user_ids, fecha_inicio, fecha_fin, include_pending=False)


def _cubre_ausencia_aprobada(leaves_by_user, user_id, day):
    leaves = (leaves_by_user or {}).get(user_id) or []
    for leave in leaves:
        if leave.covers(day):
            return True
    return False


def user_has_approved_leave_day(user_id, day):
    from app.services.leave_service import user_has_approved_leave
    return user_has_approved_leave(user_id, day)


def casa_en_fecha(user_id, fecha):
    """Obra-casa vigente ese día, o None. No mira si hay hecho hoy."""
    asigs_por_dia, anclas_desc, cortes_por_user, obras, festivos = _cargar_contexto(
        [user_id], fecha, fecha,
    )
    return _casa_desde_contexto(
        user_id, fecha, anclas_desc, cortes_por_user, obras, festivos,
    )


def casas_en_fecha(user_ids, fecha):
    ids = _operario_ids(user_ids)
    if not ids:
        return {}
    asigs_por_dia, anclas_desc, cortes_por_user, obras, festivos = _cargar_contexto(
        ids, fecha, fecha,
    )
    out = {}
    for uid in ids:
        casa = _casa_desde_contexto(
            uid, fecha, anclas_desc, cortes_por_user, obras, festivos,
        )
        if casa is not None:
            out[uid] = casa
    return out


def hechos_en_fecha(user_ids, fecha):
    """user_id → lista de obra_id con asignación firme ese día."""
    ids = _operario_ids(user_ids) if user_ids is not None else None
    q = db.session.query(Asignacion.user_id, Asignacion.obra_id).filter(
        Asignacion.fecha == fecha,
    )
    if ids is not None:
        if not ids:
            return {}
        q = q.filter(Asignacion.user_id.in_(ids))
    out = defaultdict(list)
    for uid, oid in q.all():
        out[uid].append(oid)
    return dict(out)


def horizonte_inercia():
    return today_local() + timedelta(days=INERCIA_HORIZONTE_DIAS)


def rango_pintura_inercia(fecha_inicio, fecha_fin):
    """
    La inercia solo se pinta desde hoy hasta ~un mes vista.

    El pasado es hecho o vacío. Más allá del horizonte se irá recalculando.
    """
    if fecha_inicio is None or fecha_fin is None or fecha_inicio > fecha_fin:
        return None, None
    hoy = today_local()
    if fecha_fin < hoy:
        return None, None
    start = fecha_inicio if fecha_inicio > hoy else hoy
    end = fecha_fin if fecha_fin < horizonte_inercia() else horizonte_inercia()
    if start > end:
        return None, None
    return start, end


def celdas_inercia(user_ids, fecha_inicio, fecha_fin):
    """
    {(user_id, fecha): obra_id} para días laborables sin hecho.
    Nunca incluye fechas anteriores a hoy.
    Tampoco pinta fantasma en días con ausencia/vacaciones aprobadas:
    al volver no se sabe a qué obra regresa.
    """
    fecha_inicio, fecha_fin = rango_pintura_inercia(fecha_inicio, fecha_fin)
    ids = _operario_ids(user_ids)
    if not ids or fecha_inicio is None:
        return {}
    asigs_por_dia, anclas_desc, cortes_por_user, obras, festivos = _cargar_contexto(
        ids, fecha_inicio, fecha_fin,
    )
    leaves_by_user = _ausencias_aprobadas_por_user(ids, fecha_inicio, fecha_fin)
    ids_con_casa = [uid for uid in ids if anclas_desc.get(uid)]
    if not ids_con_casa:
        return {}
    previo = _dia_laborable_previo(fecha_inicio, festivos)
    if previo is not None:
        ids_con_casa = [
            uid for uid in ids_con_casa
            if any(dia >= previo for dia, _oid in anclas_desc.get(uid, []))
        ]
    if not ids_con_casa:
        return {}
    out = {}
    day = fecha_inicio
    while day <= fecha_fin:
        if es_dia_laborable(day, festivos):
            for uid in ids_con_casa:
                if (uid, day) in asigs_por_dia:
                    continue
                if _cubre_ausencia_aprobada(leaves_by_user, uid, day):
                    continue
                casa = _casa_desde_contexto(
                    uid, day, anclas_desc, cortes_por_user, obras, festivos,
                )
                if casa is not None:
                    out[(uid, day)] = casa
        day += timedelta(days=1)
    return out


def presencias_en_fecha(fecha, user_ids=None):
    """
    Lista de {user_id, obra_id, origen} del día: hechos y, si es laborable, inercia.
    """
    ids = _operario_ids(user_ids)
    hechos = hechos_en_fecha(ids, fecha)
    out = []
    vistos = set()
    for uid, oids in hechos.items():
        for oid in oids:
            out.append({'user_id': uid, 'obra_id': oid, 'origen': 'hecho'})
            vistos.add(uid)
    if (
        fecha >= today_local()
        and fecha <= horizonte_inercia()
        and es_dia_laborable(fecha)
    ):
        leaves_by_user = _ausencias_aprobadas_por_user(ids, fecha, fecha)
        for uid, casa in casas_en_fecha(ids, fecha).items():
            if uid in vistos:
                continue
            if _cubre_ausencia_aprobada(leaves_by_user, uid, fecha):
                continue
            out.append({'user_id': uid, 'obra_id': casa, 'origen': 'inercia'})
    return out


def ids_ocupados_en_fecha(fecha, user_ids=None):
    return {p['user_id'] for p in presencias_en_fecha(fecha, user_ids)}


def inercia_en_obra(user_id, obra_id, fecha):
    if fecha < today_local() or fecha > horizonte_inercia():
        return False
    hechos = hechos_en_fecha([user_id], fecha)
    if user_id in hechos:
        return False
    if not es_dia_laborable(fecha):
        return False
    if user_has_approved_leave_day(user_id, fecha):
        return False
    return casa_en_fecha(user_id, fecha) == obra_id


def ocupados_por_dia(fecha_inicio, fecha_fin, user_ids=None):
    """fecha → número de personas distintas (hecho o inercia)."""
    ids = _operario_ids(user_ids)
    if not ids or fecha_inicio > fecha_fin:
        return {}
    asigs_por_dia, anclas_desc, cortes_por_user, obras, festivos = _cargar_contexto(
        ids, fecha_inicio, fecha_fin,
    )
    leaves_by_user = _ausencias_aprobadas_por_user(ids, fecha_inicio, fecha_fin)
    hoy = today_local()
    limite = horizonte_inercia()
    ids_con_casa = [uid for uid in ids if anclas_desc.get(uid)]
    out = {}
    day = fecha_inicio
    while day <= fecha_fin:
        ocupados = {
            uid for (uid, fecha) in asigs_por_dia.keys()
            if fecha == day
        }
        if day >= hoy and day <= limite and es_dia_laborable(day, festivos):
            for uid in ids_con_casa:
                if uid in ocupados:
                    continue
                if _cubre_ausencia_aprobada(leaves_by_user, uid, day):
                    continue
                casa = _casa_desde_contexto(
                    uid, day, anclas_desc, cortes_por_user, obras, festivos,
                )
                if casa is not None:
                    ocupados.add(uid)
        out[day] = len(ocupados)
        day += timedelta(days=1)
    return out


def bloques_inercia_rango(user_ids, fecha_inicio, fecha_fin, obra_ids=None):
    """
    Bloques de inercia: {user_id, obra_id, fecha_inicio, fecha_fin}.

    Puentea sábados, domingos y festivos: el Gantt pinta una barra continua
    (un ítem por persona, no un recorte por semana).
    Solo desde hoy; el pasado no se pinta.
    """
    fecha_inicio, fecha_fin = rango_pintura_inercia(fecha_inicio, fecha_fin)
    if fecha_inicio is None:
        return []
    if user_ids is None and obra_ids:
        lookback_start = fecha_inicio - timedelta(days=LOOKBACK_DAYS)
        user_ids = [
            uid for (uid,) in db.session.query(Asignacion.user_id)
            .filter(
                Asignacion.obra_id.in_(list(obra_ids)),
                Asignacion.fecha >= lookback_start,
                Asignacion.fecha <= fecha_fin,
            )
            .distinct()
            .all()
        ]
        if not user_ids:
            return []
    celdas = celdas_inercia(user_ids, fecha_inicio, fecha_fin)
    allowed = set(obra_ids) if obra_ids is not None else None
    festivos = festivos_en(fecha_inicio, fecha_fin)
    por_par = defaultdict(list)
    for (uid, fecha), oid in celdas.items():
        if allowed is not None and oid not in allowed:
            continue
        por_par[(uid, oid)].append(fecha)

    bloques = []
    for (uid, oid), fechas in por_par.items():
        fechas.sort()
        bloque_inicio = fechas[0]
        bloque_fin = fechas[0]
        for dia in fechas[1:]:
            if (dia - bloque_fin).days == 1 or _hueco_solo_no_laborable(
                bloque_fin, dia, festivos,
            ):
                bloque_fin = dia
            else:
                bloques.append({
                    'user_id': uid,
                    'obra_id': oid,
                    'fecha_inicio': bloque_inicio,
                    'fecha_fin': bloque_fin,
                })
                bloque_inicio = bloque_fin = dia
        bloques.append({
            'user_id': uid,
            'obra_id': oid,
            'fecha_inicio': bloque_inicio,
            'fecha_fin': bloque_fin,
        })
    return bloques


def _hueco_solo_no_laborable(prev, nxt, festivos):
    """True si entre prev y nxt (ambos exclusive) no hay ningún laborable."""
    d = prev + timedelta(days=1)
    if d >= nxt:
        return False
    while d < nxt:
        if es_dia_laborable(d, festivos):
            return False
        d += timedelta(days=1)
    return True


def log_corte_inercia(user_id, fechas, autor_id, obra_id=None):
    """Una entrada de log al soltar a Libres una inercia (sin filas que borrar)."""
    from app.models import SystemLog
    from app.services.core_assignment_service import CoreAssignmentService

    days = sorted({d for d in (fechas or []) if d})
    if not days:
        return
    user = User.query.get(user_id)
    nombre = f"{user.name} {user.lastname}" if user else f"ID {user_id}"
    obra = Obra.query.get(obra_id) if obra_id else None
    obra_label = CoreAssignmentService.format_obra_label(obra) if obra else 'Libres'
    if len(days) == 1:
        detalle = (
            f"Corta inercia de {nombre} en '{obra_label}' "
            f"({days[0].strftime('%d/%m/%Y')})."
        )
    else:
        detalle = (
            f"Corta inercia de {nombre} en '{obra_label}' "
            f"({days[0].strftime('%d/%m/%Y')} → {days[-1].strftime('%d/%m/%Y')}, "
            f"{len(days)} días)."
        )
    db.session.add(SystemLog(
        timestamp=utc_now(),
        user_id=autor_id,
        category='planificacion',
        action='Planificación Manual',
        detail=detalle,
        target_user_id=user_id,
        target_date=days[0],
    ))
