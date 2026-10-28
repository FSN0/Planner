"""Auditoría de fichajes: de «registros» a casos de trabajo y a historial legible.

Contrato de producto:
- Un caso = una cosa que alguien tiene que decidir (una fila, un solo tipo).
  Antes un mismo desvío se contaba hasta tres veces (desviación + espejo en
  ausencias + espejo en sin planificar). Aquí no hay espejos.
- Lo que no pide acción (Odoo corregido, comodín, cumplimientos) no es cola de
  trabajo: va al historial con su origen, para poder consultarlo y medirlo.
- El día en curso no cuenta como ausencia: se muestra como aviso.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import and_, case, false, or_

from app.models import Obra, RegistroFichaje, User
from app.services import desvio_fichaje_service as dfs

logger = logging.getLogger(__name__)

TIPO_NO_FICHO = 'no_ficho'
TIPO_OTRA_OBRA = 'otra_obra'
TIPO_SIN_PLANIFICAR = 'sin_planificar'
TIPO_DISPUTA = 'disputa'

ETIQUETA_TIPO = {
    TIPO_NO_FICHO: 'No fichó',
    TIPO_OTRA_OBRA: 'Fue a otra obra',
    TIPO_SIN_PLANIFICAR: 'Sin planificar',
    # Los dos jefes ya firmaron y no coinciden: solo oficina cierra.
    TIPO_DISPUTA: 'Desacuerdo · oficina',
}

# Mayor = antes en la lista.
_PESO_TIPO = {
    TIPO_DISPUTA: 4,
    TIPO_NO_FICHO: 3,
    TIPO_OTRA_OBRA: 2,
    TIPO_SIN_PLANIFICAR: 1,
}

ESTADOS_PENDIENTES = ('Conflicto', 'Disputa', 'Paracaidista', 'Ausencia')

# --- Historial ---------------------------------------------------------------

ORIGEN_MANUAL = 'manual'
ORIGEN_ODOO = 'odoo'
ORIGEN_AUTO = 'auto'
ORIGEN_COMODIN = 'comodin'
ORIGENES = (ORIGEN_MANUAL, ORIGEN_ODOO, ORIGEN_COMODIN, ORIGEN_AUTO)

ETIQUETA_ORIGEN = {
    ORIGEN_MANUAL: 'Decisión manual',
    ORIGEN_ODOO: 'Corregido en Odoo',
    ORIGEN_COMODIN: 'Obra comodín',
    ORIGEN_AUTO: 'Automático',
}

# Cierres que no pasaron por ninguna decisión humana ni corrección de RRHH.
_ESTADOS_AUTOMATICOS = (
    'Correcto', 'Correcto_Automatico', 'Cambio_Tajo', 'Exento_Ausencia',
    'Cerrado_Multiobra', 'Retraso', 'Pendiente',
)
_ESTADOS_ODOO = ('Sobreescrito_RRHH', 'Aceptado_Odoo')

# Estados de decisión humana que se pueden reabrir.
ESTADOS_REABRIBLES = (
    'Resuelto_Movido', 'Resuelto_Asignado', 'Resuelto_Dividido', 'Resuelto_Ignorado',
    'Resuelto_Falta', 'Resuelto_Ausencia', 'Falta',
)

RESULTADO_POR_ESTADO = {
    'Correcto': 'Cumplió el plan',
    'Correcto_Automatico': 'Aceptado automáticamente (obra habitual)',
    'Cambio_Tajo': 'Cambio de tajo',
    'Retraso': 'Fichó tarde en su obra',
    'Exento_Ausencia': 'Cubierto por una ausencia aprobada',
    'Cerrado_Multiobra': 'Cerrado (varias obras)',
    'Resuelto_Movido': 'Cambio de obra aceptado',
    'Resuelto_Asignado': 'Fichaje sin planificar aceptado',
    'Resuelto_Dividido': 'Jornada dividida entre obras',
    'Resuelto_Ignorado': 'Ignorado',
    'Resuelto_Falta': 'Quitado de la obra (planificación errónea)',
    'Resuelto_Ausencia': 'Ausencia justificada',
    'Falta': 'Falta confirmada',
    'Aceptado_Odoo': 'Sin planificar. Aceptado desde Odoo',
    'Sobreescrito_RRHH': 'Corregido en Odoo',
    'Conflicto': 'Decisión parcial (falta el otro lado)',
    'Disputa': 'En disputa',
}


def _nombre(user) -> str:
    if not user:
        return ''
    return f"{(user.name or '').strip()} {(user.lastname or '').strip()}".strip()


def _hhmm(dt) -> str:
    if not dt:
        return ''
    try:
        from app.utils.timezone_utils import format_time
        return format_time(dt)
    except Exception:
        return dt.strftime('%H:%M')


def _obra_dict(obra) -> dict | None:
    if not obra:
        return None
    return {
        'id': obra.id,
        'codigo': (obra.codigo or '').strip(),
        'nombre': (obra.nombre or '').strip(),
        'jefe_id': obra.jefe_obra_id,
    }


def _jefes_por_id(registros) -> dict:
    ids = set()
    for r in registros:
        for o in (r.obra_planificada, r.obra_real):
            if o is not None and o.jefe_obra_id:
                ids.add(o.jefe_obra_id)
    if not ids:
        return {}
    return {u.id: u for u in User.query.filter(User.id.in_(ids)).all()}


# --- Cola de trabajo ---------------------------------------------------------

def _acciones_desvio(reg, ctx, plan, real, oficina) -> list[dict]:
    """Botones de un desvío según lo que le toca decidir a quien mira."""
    plan_txt = plan['nombre'] if plan else 'la obra planificada'
    real_txt = real['nombre'] if real else 'la obra fichada'

    if dfs.es_desvio_disputa(reg):
        if not oficina:
            return []
        return [
            {
                'accion': dfs.ACCION_CONFIRMAR_DESVIO, 'lado': 'ambos', 'estilo': 'primary',
                'label': 'Aceptar cambio de obra',
                'title': f"Quita el plan en {plan_txt} y acepta el fichaje en {real_txt}",
            },
            {
                'accion': dfs.ACCION_RECHAZAR_DESVIO, 'lado': 'ambos', 'estilo': 'danger',
                'label': 'Falta en la planificada y aceptar fichaje',
                'title': f"Falta en {plan_txt}; el fichaje en {real_txt} queda aceptado",
            },
        ]

    acciones: list[dict] = []
    for b in (ctx or {}).get('botones') or []:
        a = b.get('accion')
        if a == dfs.ACCION_CONFIRMAR_DESVIO:
            acciones.append({
                'accion': a, 'lado': 'ambos', 'estilo': 'primary',
                'label': 'Aceptar cambio de obra',
                'title': f"Quita el plan en {plan_txt} y acepta el fichaje en {real_txt}",
            })
            acciones.append({
                'accion': dfs.ACCION_RECHAZAR_DESVIO, 'lado': 'ambos', 'estilo': 'danger',
                'label': 'Falta en la planificada y aceptar fichaje',
                'title': f"Falta en {plan_txt}; el fichaje en {real_txt} queda aceptado",
            })
        elif a == dfs.ACCION_MANTENER_FALTA:
            acciones.append({
                'accion': a, 'lado': 'plan', 'estilo': 'danger',
                'label': 'Confirmar falta',
                'title': f"No fue a {plan_txt}: falta confirmada",
            })
        elif a == dfs.ACCION_LIBERAR_PLAZA:
            acciones.append({
                'accion': a, 'lado': 'plan', 'estilo': 'ghost',
                'label': 'Quitar de la obra',
                'title': f"La planificación en {plan_txt} estaba mal o ya no aplica",
            })
        elif a == dfs.ACCION_ACEPTAR_ENTRADA:
            acciones.append({
                'accion': a, 'lado': 'real', 'estilo': 'primary',
                'label': 'Aceptar fichaje',
                'title': f"Asigna oficialmente a {real_txt}",
            })
    return acciones


def _acciones_caso(reg, tipo, ctx, plan, real, *, puede_resolver, oficina) -> list[dict]:
    if not puede_resolver:
        return []
    if tipo == TIPO_NO_FICHO:
        return [
            {
                'accion': 'confirmar_ausencia', 'lado': 'plan', 'estilo': 'danger',
                'label': 'Confirmar falta',
                'title': 'No fue a trabajar: falta confirmada (sigue planificado)',
            },
            {
                'accion': 'borrar_planificacion', 'lado': 'plan', 'estilo': 'ghost',
                'label': 'Quitar de la obra',
                'title': 'La planificación estaba mal o ya no aplica',
            },
        ]
    if tipo == TIPO_SIN_PLANIFICAR:
        return [{
            'accion': 'anadir', 'lado': 'real', 'estilo': 'primary',
            'label': 'Aceptar fichaje',
            'title': 'Lo asigna oficialmente a la obra donde fichó',
        }]
    return _acciones_desvio(reg, ctx, plan, real, oficina)


def _resumen_caso(tipo, plan, real, detalle) -> str:
    plan_txt = plan['nombre'] if plan else 'ninguna obra'
    real_txt = real['nombre'] if real else 'ninguna obra'
    if tipo == TIPO_NO_FICHO:
        base = f"Planificado en {plan_txt}. No fichó."
        return f"{base} {detalle}".strip() if detalle else base
    if tipo in (TIPO_OTRA_OBRA, TIPO_DISPUTA):
        return f"Planificado en {plan_txt}. Fichó en {real_txt}."
    return f"Fichó en {real_txt} sin tener planificación ese día."


def _esperando_a(reg, ctx, plan, real, jefes, oficina) -> str:
    """Texto de a quién espera un desvío a medias (si no lo decide quien mira)."""
    if not ctx or oficina:
        return ''
    pendientes_viewer = set(ctx.get('pendientes_viewer') or [])
    partes = []
    if not ctx.get('ack_plan') and 'plan' not in pendientes_viewer and plan:
        j = jefes.get(plan.get('jefe_id'))
        partes.append(f"plan: {_nombre(j) or 'jefe de la obra planificada'}")
    if not ctx.get('ack_real') and 'real' not in pendientes_viewer and real:
        j = jefes.get(real.get('jefe_id'))
        partes.append(f"fichaje: {_nombre(j) or 'jefe de la obra fichada'}")
    return ('Pendiente de ' + ' y '.join(partes)) if partes else ''


def construir_cola(
    pendientes,
    user,
    *,
    hoy: date,
    puede_resolver: bool,
    geo_por_registro: dict | None = None,
    comodin_ids=None,
) -> dict:
    """Agrupa los pendientes en casos únicos.

    `pendientes` ya viene enriquecido con ``desvio_ui`` (visibilidad por jefe).
    Devuelve ``{'casos': [...], 'avisos_hoy': [...], 'comodin': [...]}``.
    """
    ids_comodin = (
        dfs.obras_comodin_ids() if comodin_ids is None
        else dfs.parse_obras_comodin_ids(comodin_ids)
    )
    names_c, codes_c = dfs._comodin_nombre_codigo_sets(ids_comodin)
    oficina = dfs._es_oficina(user)
    geo_por_registro = geo_por_registro or {}

    reales = []
    comodin = []
    for r in pendientes or []:
        if dfs.registro_es_comodin(r, ids_comodin, _names=names_c, _codes=codes_c):
            comodin.append(r)
        else:
            reales.append(r)

    ausencias_puras = [r for r in reales if r.estado == 'Ausencia']
    try:
        dfs.enriquecer_problema_ausencias(ausencias_puras)
    except Exception:
        logger.exception('enriquecer_problema_ausencias falló; sin detalle de plan parcial')

    jefes = _jefes_por_id(reales)

    casos: list[dict] = []
    avisos_hoy: list[dict] = []
    for r in reales:
        estado = r.estado
        ctx = getattr(r, 'desvio_ui', None)
        plan = _obra_dict(r.obra_planificada)
        real = _obra_dict(r.obra_real)
        detalle = ''

        if estado == 'Ausencia':
            tipo = TIPO_NO_FICHO
            ficho_en = getattr(r, 'ausencia_ficho_en', None)
            if ficho_en is not None:
                detalle = f"Sí fichó en {(ficho_en.nombre or '').strip()}; falta esta obra."
            if r.fecha and r.fecha >= hoy:
                # Día en curso: aún puede fichar. Aviso, no incidencia.
                avisos_hoy.append({
                    'id': r.id,
                    'user': {'id': r.user_id, 'nombre': _nombre(r.user)},
                    'plan': plan,
                    'parcial': ficho_en is not None,
                    'detalle': detalle,
                })
                continue
        elif estado == 'Disputa':
            tipo = TIPO_DISPUTA
        elif estado == 'Conflicto':
            tipo = TIPO_OTRA_OBRA
        elif estado == 'Paracaidista':
            tipo = TIPO_SIN_PLANIFICAR
        else:
            continue

        jefe_plan = jefes.get(plan['jefe_id']) if plan and plan['jefe_id'] else None
        jefe_real = jefes.get(real['jefe_id']) if real and real['jefe_id'] else None
        geo = geo_por_registro.get(r.id)
        acciones = _acciones_caso(
            r, tipo, ctx, plan, real, puede_resolver=puede_resolver, oficina=oficina,
        )
        casos.append({
            'id': r.id,
            'tipo': tipo,
            'tipo_label': ETIQUETA_TIPO[tipo],
            'peso': _PESO_TIPO[tipo],
            'user_id': r.user_id,
            'user_nombre': _nombre(r.user),
            'user_categoria': (getattr(r.user, 'categoria_profesional', None) or '') if r.user else '',
            'fecha': r.fecha,
            'fecha_txt': r.fecha.strftime('%d/%m/%Y') if r.fecha else '',
            'plan': plan,
            'real': real,
            'jefe_plan': _nombre(jefe_plan),
            'jefe_plan_id': plan['jefe_id'] if plan else None,
            'jefe_real': _nombre(jefe_real),
            'jefe_real_id': real['jefe_id'] if real else None,
            'responsable': _nombre(jefe_plan) or _nombre(jefe_real),
            'responsable_id': (plan['jefe_id'] if plan and plan.get('jefe_id') else None)
                or (real['jefe_id'] if real and real.get('jefe_id') else None),
            'entrada': _hhmm(r.check_in),
            'salida': _hhmm(r.check_out),
            'nota': (r.nota_odoo or '').strip(),
            'resumen': _resumen_caso(tipo, plan, real, detalle),
            'detalle': detalle,
            'acciones': acciones,
            'ack_plan': bool(ctx and ctx.get('ack_plan')),
            'ack_real': bool(ctx and ctx.get('ack_real')),
            'ack_plan_label': (ctx or {}).get('ack_plan_label'),
            'ack_real_label': (ctx or {}).get('ack_real_label'),
            'ack_plan_por': (ctx or {}).get('ack_plan_por'),
            'ack_real_por': (ctx or {}).get('ack_real_por'),
            'planificado_por': (ctx or {}).get('planificado_por'),
            'esperando': _esperando_a(r, ctx, plan, real, jefes, oficina),
            'geo_dudosa': bool(geo and geo.get('geo_estado') == 'dudosa'),
            'geo_distancia': (geo or {}).get('distancia_metros'),
        })

    casos.sort(key=lambda c: (c['fecha'] or date.min, c['peso']), reverse=True)
    return {'casos': casos, 'avisos_hoy': avisos_hoy, 'comodin': comodin}


def caso_a_json(caso: dict) -> dict:
    """Versión serializable de un caso (el panel de detalle se pinta en el navegador)."""
    out = {k: v for k, v in caso.items() if k not in ('fecha', 'peso')}
    out['fecha_iso'] = caso['fecha'].isoformat() if caso.get('fecha') else ''
    dist = out.get('geo_distancia')
    out['geo_distancia'] = float(dist) if dist is not None else None
    return out


# --- Historial ---------------------------------------------------------------

def condicion_en_historial(comodin_obra_ids):
    """Todo lo que ya no es trabajo pendiente (o nunca lo fue).

    Incluye cumplimientos, decisiones, correcciones de Odoo, desvíos con un lado
    decidido y los pendientes de obra comodín (que nunca entran en la cola).
    """
    est = RegistroFichaje.estado
    fuera = ESTADOS_PENDIENTES + ('Sin_Registro',)
    parcial = and_(
        est.in_(('Conflicto', 'Disputa')),
        or_(
            RegistroFichaje.desvio_ack_plan_at.isnot(None),
            RegistroFichaje.desvio_ack_real_at.isnot(None),
        ),
    )
    clauses = [~est.in_(fuera), parcial]
    if comodin_obra_ids:
        clauses.append(and_(
            est.in_(ESTADOS_PENDIENTES),
            RegistroFichaje.obra_real_id.in_(list(comodin_obra_ids)),
        ))
    return or_(*clauses)


def expr_origen_sql(comodin_obra_ids):
    """Origen de cada fila, calculado en SQL para poder filtrar y paginar."""
    est = RegistroFichaje.estado
    notas = RegistroFichaje.notas_resolucion
    es_comodin = (
        and_(
            est.in_(ESTADOS_PENDIENTES),
            RegistroFichaje.obra_real_id.in_(list(comodin_obra_ids)),
        )
        if comodin_obra_ids else false()
    )
    es_odoo = or_(
        est.in_(_ESTADOS_ODOO),
        and_(est == 'Falta', notas.like(f'{dfs.PREFIJO_FALTA_AUTO}%')),
    )
    return case(
        (es_comodin, ORIGEN_COMODIN),
        (es_odoo, ORIGEN_ODOO),
        (est.in_(_ESTADOS_AUTOMATICOS), ORIGEN_AUTO),
        else_=ORIGEN_MANUAL,
    )


def comodin_obra_ids_expandidos(comodin_ids=None) -> set:
    """IDs de obras comodín incluyendo duplicados por código/nombre."""
    ids = (
        dfs.obras_comodin_ids() if comodin_ids is None
        else dfs.parse_obras_comodin_ids(comodin_ids)
    )
    if not ids:
        return set()
    names, codes = dfs._comodin_nombre_codigo_sets(ids)
    out = set(ids)
    try:
        from sqlalchemy import func
        conds = []
        if names:
            conds.append(func.lower(func.trim(Obra.nombre)).in_(list(names)))
        if codes:
            conds.append(func.lower(func.trim(Obra.codigo)).in_(list(codes)))
        if conds:
            out |= {o.id for o in Obra.query.filter(or_(*conds)).all()}
    except Exception:
        logger.debug('comodin expandido falló', exc_info=True)
    return out


def parsear_correccion_odoo(registro) -> dict:
    """Desglosa `notas_resolucion` de una fila `Sobreescrito_RRHH`.

    Formato: ``id||cod||nombre||nuevo_id||nuevo_cod||nuevo_nombre||accion||estado_ant[||plan_id]``.
    """
    partes = (registro.notas_resolucion or '').split('||')
    partes += [''] * (9 - len(partes))
    accion = (partes[6] or '').strip()
    return {
        'obra_antes_id': partes[0] or None,
        'obra_antes': (f"{partes[1]} - {partes[2]}".strip(' -') if (partes[1] or partes[2]) else ''),
        'obra_despues_id': partes[3] or None,
        'obra_despues': (f"{partes[4]} - {partes[5]}".strip(' -') if (partes[4] or partes[5]) else ''),
        'accion': accion,
        'cambio_obra': accion == 'Modificado de Obra',
        'borrado': accion == 'Borrado en Odoo',
        'estado_anterior': (partes[7] or '').strip(),
        'plan_id': partes[8] or None,
    }


def origen_registro(registro, comodin_obra_ids=()) -> str:
    """Origen de una fila ya cargada (espejo Python de ``expr_origen_sql``)."""
    est = registro.estado or ''
    if est in ESTADOS_PENDIENTES and registro.obra_real_id in (comodin_obra_ids or ()):
        return ORIGEN_COMODIN
    if est in _ESTADOS_ODOO or dfs.es_falta_automatica(registro):
        return ORIGEN_ODOO
    if est in _ESTADOS_AUTOMATICOS:
        return ORIGEN_AUTO
    return ORIGEN_MANUAL


def resultado_registro(registro, comodin_obra_ids=()) -> str:
    """Frase corta de lo que pasó, en lenguaje de obra."""
    est = registro.estado or ''
    if est == 'Sobreescrito_RRHH':
        c = parsear_correccion_odoo(registro)
        if c['cambio_obra']:
            return f"Odoo cambió la obra: {c['obra_antes'] or '—'} → {c['obra_despues'] or '—'}"
        if c['borrado']:
            return f"Fichaje borrado en Odoo ({c['obra_antes'] or 'sin obra'})"
        return RESULTADO_POR_ESTADO[est]
    if dfs.es_falta_automatica(registro):
        return 'Falta automática: RRHH corrigió el día en Odoo'
    if est in ESTADOS_PENDIENTES and registro.obra_real_id in (comodin_obra_ids or ()):
        return 'Obra comodín. No requiere acción'
    return RESULTADO_POR_ESTADO.get(est) or est.replace('_', ' ') or '—'


def quien_y_cuando(registro, origen) -> str:
    """«Quién lo decidió y cuándo», o la fuente si no fue una persona."""
    cuando = ''
    fecha_aud = getattr(registro, 'fecha_auditoria', None)
    if fecha_aud:
        try:
            from app.utils.timezone_utils import utc_to_local
            cuando = utc_to_local(fecha_aud).strftime('%d/%m %H:%M')
        except Exception:
            cuando = fecha_aud.strftime('%d/%m %H:%M')
    if origen == ORIGEN_ODOO:
        base = 'RRHH en Odoo'
    elif origen == ORIGEN_AUTO or origen == ORIGEN_COMODIN:
        base = 'Sistema'
    else:
        base = _nombre(registro.resuelto_por) or '—'
    return f"{base} · {cuando}" if cuando and base != '—' else base
