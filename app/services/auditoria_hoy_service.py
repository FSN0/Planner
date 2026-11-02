"""Roster del día en curso para la pestaña «Hoy» de auditoría de fichajes.

No es cola de trabajo: es la foto planificado → fichado de hoy (también los OK).
Cada persona: columna Plan (plazas) + columna Fichaje (marcas reales, sin duplicar).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.models import Asignacion, Obra, RegistroFichaje, User
from app.services.auditoria_casos_service import ESTADOS_PENDIENTES
from app.services.fichaje_estado_service import label_estado_fichaje
from app.services.panel_scope_service import (
    PANEL_AUDITORIA_FICHAJES,
    user_custody_jefe_ids,
    user_panel_mode,
)
from app.utils.timezone_utils import today_local

CHIP_OK = 'ok'
CHIP_SIN_FICHAR = 'sin_fichar'
CHIP_FALTA = 'falta'
CHIP_AUDITAR = 'auditar'
CHIP_DESVIO = 'desvio'  # plan no cumplido (fichó en otra)

_OK = frozenset({
    'Correcto', 'Correcto_Automatico', 'Cambio_Tajo', 'Retraso',
    'Exento_Ausencia', 'Cerrado_Multiobra', 'Sobreescrito_RRHH', 'Aceptado_Odoo',
    'Resuelto_Movido', 'Resuelto_Asignado', 'Resuelto_Dividido',
    'Resuelto_Ignorado', 'Resuelto_Falta', 'Resuelto_Ausencia',
})
_AUDITAR = frozenset({'Conflicto', 'Disputa', 'Paracaidista', 'Ausencia', 'Pendiente'})
_PENDIENTES = frozenset(ESTADOS_PENDIENTES)


def _nav(reg) -> tuple[int | None, str | None]:
    """(registro_id, destino) → resolver | historial | None."""
    if reg is None:
        return None, None
    est = (reg.estado or '').strip()
    if est in _PENDIENTES:
        return reg.id, 'resolver'
    if est == 'Sin_Registro':
        return reg.id, None  # aún no hay caso; la fila abre el día
    return reg.id, 'historial'


def _obra_ids_alcance(user) -> list[int] | None:
    """None = oficina (sin filtro). Lista = obras del alcance custody. [] = nada."""
    mode = user_panel_mode(user, PANEL_AUDITORIA_FICHAJES)
    if mode == 'none':
        return []
    if mode == 'office':
        return None
    jefe_ids = user_custody_jefe_ids(user, PANEL_AUDITORIA_FICHAJES)
    if not jefe_ids:
        return []
    return [
        oid for (oid,) in (
            Obra.query.filter(Obra.jefe_obra_id.in_(jefe_ids))
            .with_entities(Obra.id)
            .all()
        )
    ]


def _nombre(u) -> str:
    if not u:
        return ''
    return f"{(u.name or '').strip()} {(u.lastname or '').strip()}".strip()


def _falta_confirmada_en_plan(reg) -> bool:
    """Falta ya decidida en la plaza (estado final o ack parcial de desvío).

    En desvío, «Confirmar falta» deja el registro en Conflicto/Disputa hasta
    aceptar el fichaje real; el calendario ya lo trata como falta y Hoy debe
    pintar lo mismo (no «No fichó aquí»).
    """
    if reg is None:
        return False
    est = (reg.estado or '').strip()
    if est == 'Falta':
        return True
    return (
        bool(getattr(reg, 'desvio_ack_plan_at', None))
        and (getattr(reg, 'desvio_decision_plan', None) or '') == 'mantener_falta'
    )


def _chip_plan(reg, *, hoy: date) -> tuple[str, str]:
    """Estado de la plaza planificada (no describe el fichaje real)."""
    if reg is None:
        return CHIP_SIN_FICHAR, 'Sin fichar'
    est = (reg.estado or '').strip()
    if _falta_confirmada_en_plan(reg):
        return CHIP_FALTA, 'Falta'
    if est in _OK or est.startswith('Resuelto'):
        if est.startswith('Resuelto'):
            return CHIP_OK, label_estado_fichaje(est)
        return CHIP_OK, 'Cumplió'
    if est == 'Sin_Registro':
        return CHIP_SIN_FICHAR, 'Sin fichar'
    if est == 'Ausencia' and reg.fecha and reg.fecha >= hoy:
        return CHIP_SIN_FICHAR, 'Aún sin fichar'
    if est == 'Conflicto':
        return CHIP_DESVIO, 'No fichó aquí'
    if est == 'Disputa':
        return CHIP_AUDITAR, 'Desacuerdo'
    if est in _AUDITAR:
        return CHIP_AUDITAR, label_estado_fichaje(est)
    return CHIP_AUDITAR, label_estado_fichaje(est) or est


def _chip_fichaje(reg, *, en_plan: bool) -> tuple[str, str]:
    """Estado de una marca real (una por obra_real)."""
    est = (reg.estado or '').strip()
    if en_plan and (est in _OK or est.startswith('Resuelto') or est == 'Retraso'):
        return CHIP_OK, 'Según plan'
    if not en_plan:
        if est in ('Paracaidista', 'Conflicto', 'Disputa'):
            return CHIP_DESVIO, 'Fuera de plan'
        if est in _OK or est.startswith('Resuelto') or est == 'Aceptado_Odoo':
            return CHIP_DESVIO, 'Fuera de plan'
        return CHIP_DESVIO, label_estado_fichaje(est) or 'Fuera de plan'
    if est in _AUDITAR:
        return CHIP_AUDITAR, label_estado_fichaje(est)
    return CHIP_OK, label_estado_fichaje(est) or est


def _chip_dict(obra_id, o, chip, label, reg, *, entrada='', en_plan=None) -> dict:
    rid, destino = _nav(reg)
    out = {
        'obra_id': obra_id,
        'obra': (o.nombre or '').strip() if o else f'Obra {obra_id}',
        'codigo': (o.codigo or '').strip() if o else '',
        'chip': chip,
        'label': label,
        'estado': (reg.estado if reg else 'Sin_Registro'),
        'registro_id': rid,
        'destino': destino,
        'caso_id': rid if destino == 'resolver' else None,
        'entrada': entrada,
    }
    if en_plan is not None:
        out['en_plan'] = en_plan
    return out


def count_planificados_sin_marca(user, *, hoy: date | None = None) -> int:
    """Personas con plaza hoy que no han fichado en ninguna obra.

    Distinto de «plazas Sin_Registro»: aquí cuenta personas, y quien fichó
    fuera de plan no entra (sí tiene marca).
    """
    hoy = hoy or today_local()
    obra_ids = _obra_ids_alcance(user)
    if obra_ids is not None and not obra_ids:
        return 0
    q_asig = Asignacion.query.filter(Asignacion.fecha == hoy)
    if obra_ids is not None:
        q_asig = q_asig.filter(Asignacion.obra_id.in_(obra_ids))
    user_ids = {
        uid for (uid,) in q_asig.with_entities(Asignacion.user_id).distinct().all()
        if uid
    }
    if not user_ids:
        return 0
    con_marca = {
        uid for (uid,) in (
            RegistroFichaje.query
            .filter(
                RegistroFichaje.fecha == hoy,
                RegistroFichaje.user_id.in_(user_ids),
                RegistroFichaje.obra_real_id.isnot(None),
            )
            .with_entities(RegistroFichaje.user_id)
            .distinct()
            .all()
        )
        if uid
    }
    return len(user_ids - con_marca)


def roster_hoy(user, *, hoy: date | None = None, q: str = '') -> dict:
    """Personas planificadas hoy: plan (plazas) + fichajes (marcas únicas)."""
    hoy = hoy or today_local()
    obra_ids = _obra_ids_alcance(user)
    vacio = {
        'hoy': hoy.isoformat(),
        'hoy_txt': hoy.strftime('%d/%m/%Y'),
        'personas': [],
        'totales': {
            'personas': 0, 'plazas': 0,
            'ok': 0, 'sin_fichar': 0, 'falta': 0, 'auditar': 0, 'desvio': 0,
        },
    }
    if obra_ids is not None and not obra_ids:
        return vacio

    q_asig = Asignacion.query.filter(Asignacion.fecha == hoy)
    if obra_ids is not None:
        q_asig = q_asig.filter(Asignacion.obra_id.in_(obra_ids))
    asignaciones = q_asig.all()

    obra_map = {}
    if asignaciones:
        ids = {a.obra_id for a in asignaciones if a.obra_id}
        for o in Obra.query.filter(Obra.id.in_(ids)).all():
            obra_map[o.id] = o

    user_ids = {a.user_id for a in asignaciones if a.user_id}
    users = {
        u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    if user_ids:
        registros = (
            RegistroFichaje.query
            .filter(
                RegistroFichaje.fecha == hoy,
                RegistroFichaje.user_id.in_(user_ids),
            )
            .all()
        )
    else:
        registros = []

    reg_por_plan = {}
    # user_id → obra_real_id → mejor reg (una marca física por obra)
    fichaje_por_obra = defaultdict(dict)
    for r in registros:
        if r.obra_planificada_id:
            key = (r.user_id, r.obra_planificada_id)
            prev = reg_por_plan.get(key)
            if prev is None or _prioridad_reg(r) >= _prioridad_reg(prev):
                reg_por_plan[key] = r
        if r.obra_real_id:
            prev_f = fichaje_por_obra[r.user_id].get(r.obra_real_id)
            if prev_f is None or _prioridad_reg(r) >= _prioridad_reg(prev_f):
                fichaje_por_obra[r.user_id][r.obra_real_id] = r
        if r.obra_real_id and r.obra_real_id not in obra_map and r.obra_real:
            obra_map[r.obra_real_id] = r.obra_real
        if r.obra_planificada_id and r.obra_planificada_id not in obra_map and r.obra_planificada:
            obra_map[r.obra_planificada_id] = r.obra_planificada

    plazas_por_user = defaultdict(list)
    for a in asignaciones:
        if not a.user_id or not a.obra_id:
            continue
        plazas_por_user[a.user_id].append(a.obra_id)

    qn = (q or '').strip().lower()
    personas = []
    totales = {
        'personas': 0, 'plazas': 0,
        'ok': 0, 'sin_fichar': 0, 'falta': 0, 'auditar': 0, 'desvio': 0,
    }

    for uid, obra_ids_u in plazas_por_user.items():
        u = users.get(uid)
        nombre = _nombre(u)
        dni = (getattr(u, 'dni', None) or '').strip()
        seen = set()
        obras_u = []
        for oid in obra_ids_u:
            if oid in seen:
                continue
            seen.add(oid)
            obras_u.append(oid)
        plan_set = set(obras_u)

        plan_chips = []
        search_bits = [nombre.lower(), dni.lower()]
        for oid in obras_u:
            o = obra_map.get(oid)
            onombre = (o.nombre or '').strip() if o else f'Obra {oid}'
            ocodigo = (o.codigo or '').strip() if o else ''
            search_bits.extend([onombre.lower(), ocodigo.lower()])
            reg = reg_por_plan.get((uid, oid))
            chip, label = _chip_plan(reg, hoy=hoy)
            plan_chips.append(_chip_dict(oid, o, chip, label, reg))
            totales[chip] = totales.get(chip, 0) + 1
            totales['plazas'] += 1

        fichaje_chips = []
        for real_id, reg in sorted(
            fichaje_por_obra.get(uid, {}).items(),
            key=lambda it: (_hhmm(it[1].check_in) or '99', it[0]),
        ):
            # Custody: ocultar fichaje fuera de alcance salvo que desvíe un plan del viewer.
            if obra_ids is not None and real_id not in obra_ids and real_id not in plan_set:
                ligado = False
                for oid in obras_u:
                    rp = reg_por_plan.get((uid, oid))
                    if rp and rp.obra_real_id == real_id:
                        ligado = True
                        break
                if not ligado:
                    continue
            en_plan = real_id in plan_set
            o = obra_map.get(real_id) or reg.obra_real
            onombre = (o.nombre or '').strip() if o else f'Obra {real_id}'
            search_bits.append(onombre.lower())
            chip, label = _chip_fichaje(reg, en_plan=en_plan)
            fichaje_chips.append(_chip_dict(
                real_id, o, chip, label, reg,
                entrada=_hhmm(reg.check_in), en_plan=en_plan,
            ))

        if qn and qn not in ' '.join(search_bits):
            continue

        resumen = _resumen_persona(plan_chips, fichaje_chips)
        tono = _tono_fila(plan_chips, fichaje_chips)
        personas.append({
            'user_id': uid,
            'nombre': nombre or f'#{uid}',
            'dni': dni,
            'categoria': (getattr(u, 'categoria_profesional', None) or '') if u else '',
            'fecha': hoy.isoformat(),
            'plan': plan_chips,
            'fichajes': fichaje_chips,
            # Compat JS antiguo (por si queda caché): plazas≈plan, extras≈fuera de plan
            'plazas': plan_chips,
            'extras': [f for f in fichaje_chips if not f.get('en_plan')],
            'resumen_chip': resumen,
            'tono_fila': tono,
            # Conflicto / desvío (ámbar). Sin marca total = rojo; parcial = gris.
            'tiene_problema': tono == 'problema',
        })
        totales['personas'] += 1

    _orden_tono = {'problema': 0, 'sin_marca': 1, 'parcial': 2, 'ok': 3, '': 4}
    personas.sort(key=lambda p: (
        _orden_tono.get(p.get('tono_fila') or '', 4),
        p['nombre'].lower(),
    ))

    return {
        'hoy': hoy.isoformat(),
        'hoy_txt': hoy.strftime('%d/%m/%Y'),
        'personas': personas,
        'totales': totales,
    }


def _resumen_persona(plan_chips, fichaje_chips) -> str:
    orden = (CHIP_AUDITAR, CHIP_DESVIO, CHIP_SIN_FICHAR, CHIP_FALTA, CHIP_OK)
    keys = {c['chip'] for c in plan_chips} | {c['chip'] for c in fichaje_chips}
    # «otra» legacy → desvío
    if 'otra' in keys:
        keys.add(CHIP_DESVIO)
    for k in orden:
        if k in keys:
            return k
    return CHIP_OK


def _tono_fila(plan_chips, fichaje_chips) -> str:
    """Fondo de fila: problema (ámbar), sin_marca (rojo), parcial (gris), ok (verde)."""
    keys_p = {c['chip'] for c in plan_chips}
    keys_f = {c['chip'] for c in fichaje_chips}
    if (CHIP_AUDITAR in keys_p or CHIP_DESVIO in keys_p or 'otra' in keys_p
            or CHIP_AUDITAR in keys_f or CHIP_DESVIO in keys_f or 'otra' in keys_f):
        return 'problema'
    plazas_abiertas = any(c['chip'] in (CHIP_SIN_FICHAR, CHIP_FALTA) for c in plan_chips)
    if not fichaje_chips and plazas_abiertas:
        return 'sin_marca'
    if fichaje_chips and any(c['chip'] == CHIP_SIN_FICHAR for c in plan_chips):
        return 'parcial'
    if plan_chips and not plazas_abiertas:
        return 'ok'
    return ''


def _prioridad_reg(reg) -> int:
    est = reg.estado or ''
    if est in _AUDITAR or est == 'Falta':
        return 3
    if est == 'Sin_Registro':
        return 1
    if est in _OK or est.startswith('Resuelto'):
        return 2
    return 0


def _hhmm(dt) -> str:
    if not dt:
        return ''
    try:
        from app.utils.timezone_utils import format_time
        return format_time(dt)
    except Exception:
        return dt.strftime('%H:%M')
