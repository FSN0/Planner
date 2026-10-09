"""Avisos de certificación por mes (badges en el selector de periodo).

Un mes «pide atención» si hay señal (propuesta o fichaje) y aún no está aceptada.
Se puede silenciar por alcance+mes; un cambio real (enviar/aceptar/…) lo reactiva.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from app import db
from app.models import CertificacionPropuesta, RegistroFichaje, User
from app.services.config_service import get_tenant_config, set_tenant_config

CONFIG_DISMISSED = 'cert.avisos_dismissed'
_MESES_ATRAS = 17
_MESES_ADELANTE = 2


def scope_oficina() -> str:
    return 'ofi:all'


def scope_subcontrata() -> str:
    return 'sub:all'


def scope_company(company_id: int, *, vista_subcontrata: bool = False) -> str:
    pref = 'sub' if vista_subcontrata else 'ofi'
    return f'{pref}:c:{int(company_id)}'


def scope_obra(obra_id: int, *, company_id: int | None = None, vista_subcontrata: bool = False) -> str:
    pref = 'sub' if vista_subcontrata else 'ofi'
    if company_id:
        return f'{pref}:c:{int(company_id)}:o:{int(obra_id)}'
    return f'{pref}:o:{int(obra_id)}'


def _shift_ym(anio: int, mes: int, delta: int) -> tuple[int, int]:
    idx = anio * 12 + (mes - 1) + delta
    return idx // 12, idx % 12 + 1


def _ym_key(anio: int, mes: int) -> str:
    return f'{int(anio):04d}-{int(mes):02d}'


def _dismiss_token(scope: str, anio: int, mes: int) -> str:
    return f'{scope}|{_ym_key(anio, mes)}'


def _load_dismissed() -> set[str]:
    raw = get_tenant_config(CONFIG_DISMISSED, default=None)
    if not raw:
        return set()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return set()
    if not isinstance(data, list):
        return set()
    return {str(x) for x in data if x}


def _save_dismissed(tokens: set[str]) -> None:
    set_tenant_config(CONFIG_DISMISSED, json.dumps(sorted(tokens)))


def is_dismissed(scope: str, anio: int, mes: int) -> bool:
    return _dismiss_token(scope, anio, mes) in _load_dismissed()


def dismiss_aviso(scope: str, anio: int, mes: int) -> None:
    tokens = _load_dismissed()
    tokens.add(_dismiss_token(scope, anio, mes))
    _save_dismissed(tokens)


def undismiss_aviso(scope: str, anio: int, mes: int) -> None:
    """Reactiva el aviso de un alcance+mes concreto (quita el silencio)."""
    tokens = _load_dismissed()
    tok = _dismiss_token(scope, anio, mes)
    if tok not in tokens:
        return
    tokens.discard(tok)
    _save_dismissed(tokens)


def reactivar_avisos_mes(
    anio: int,
    mes: int,
    *,
    company_id: int | None = None,
    obra_id: int | None = None,
) -> None:
    """Al cambiar una propuesta, quita silencios de ese mes (todos los alcances relacionados)."""
    tokens = _load_dismissed()
    if not tokens:
        return
    ym = _ym_key(anio, mes)
    keep = set()
    for t in tokens:
        if not t.endswith(f'|{ym}'):
            keep.add(t)
            continue
        scope = t.rsplit('|', 1)[0]
        # Reactiva siempre ofi:all / sub:all de ese mes.
        if scope in ('ofi:all', 'sub:all'):
            continue
        if company_id and f':c:{int(company_id)}' in scope:
            continue
        if obra_id and f':o:{int(obra_id)}' in scope:
            continue
        keep.add(t)
    if keep != tokens:
        _save_dismissed(keep)


def _obra_ids_permitidas(user) -> set[int] | None:
    """None = sin filtro; set vacío = nada; set = solo esas obras."""
    if user is None:
        return None
    try:
        from app.services.panel_scope_service import certificacion_obra_ids
        allowed = certificacion_obra_ids(user)
    except Exception:
        return None
    if allowed is None:
        return None
    return set(allowed)


def _pares_con_propuesta(
    *,
    company_id: int | None,
    obra_id: int | None,
    inicio: date,
    fin: date,
    obra_ids: set[int] | None,
) -> dict[tuple[int, int, int, int], list[CertificacionPropuesta]]:
    """Clave (company_id, obra_id, anio, mes) → propuestas."""
    q = CertificacionPropuesta.query
    if company_id:
        q = q.filter(CertificacionPropuesta.company_id == company_id)
    if obra_id:
        q = q.filter(CertificacionPropuesta.obra_id == obra_id)
    if obra_ids is not None:
        if not obra_ids:
            return {}
        q = q.filter(CertificacionPropuesta.obra_id.in_(obra_ids))
    # Ventana por anio/mes aproximada
    anio_i, mes_i = inicio.year, inicio.month
    anio_f, mes_f = fin.year, fin.month
    rows = q.all()
    out: dict[tuple[int, int, int, int], list] = defaultdict(list)
    for r in rows:
        if (r.anio, r.mes) < (anio_i, mes_i) or (r.anio, r.mes) > (anio_f, mes_f):
            continue
        out[(r.company_id, r.obra_id, r.anio, r.mes)].append(r)
    return out


def _ym_con_fichaje(
    *,
    company_id: int | None,
    obra_id: int | None,
    inicio: date,
    fin: date,
    obra_ids: set[int] | None,
) -> set[tuple[int, int, int, int]]:
    """Pares (company_id, obra_id, anio, mes) con fichaje en ventana."""
    uq = User.query.filter(User.is_deleted.is_(False))
    if company_id:
        uq = uq.filter(User.company_id == company_id)
    usuarios = uq.all()
    if not usuarios:
        return set()
    by_company: dict[int, list[int]] = defaultdict(list)
    for u in usuarios:
        if u.company_id:
            by_company[u.company_id].append(u.id)
    if not by_company:
        return set()

    all_uids = [u.id for u in usuarios]
    fq = db.session.query(
        RegistroFichaje.user_id,
        RegistroFichaje.obra_real_id,
        RegistroFichaje.fecha,
    ).filter(
        RegistroFichaje.user_id.in_(all_uids),
        RegistroFichaje.fecha >= inicio,
        RegistroFichaje.fecha < fin,
        RegistroFichaje.check_in.isnot(None),
        RegistroFichaje.obra_real_id.isnot(None),
    )
    if obra_id:
        fq = fq.filter(RegistroFichaje.obra_real_id == obra_id)
    if obra_ids is not None:
        if not obra_ids:
            return set()
        fq = fq.filter(RegistroFichaje.obra_real_id.in_(obra_ids))

    uid_company = {u.id: u.company_id for u in usuarios}
    out: set[tuple[int, int, int, int]] = set()
    for uid, oid, fecha in fq.all():
        if not fecha or not oid:
            continue
        cid = uid_company.get(uid)
        if not cid:
            continue
        if company_id and cid != company_id:
            continue
        out.add((cid, oid, fecha.year, fecha.month))
    return out


def _meses_pendientes_raw(
    *,
    company_id: int | None = None,
    obra_id: int | None = None,
    user=None,
    anio_ref: int,
    mes_ref: int,
    meses_atras: int = _MESES_ATRAS,
    meses_adelante: int = _MESES_ADELANTE,
) -> dict[tuple[int, int], str]:
    """{(anio, mes): etiqueta} meses con señal y sin aceptar."""
    inicio_a, inicio_m = _shift_ym(anio_ref, mes_ref, -meses_atras)
    fin_a, fin_m = _shift_ym(anio_ref, mes_ref, meses_adelante)
    inicio = date(inicio_a, inicio_m, 1)
    fa, fm = _shift_ym(fin_a, fin_m, 1)
    fin = date(fa, fm, 1)
    obra_ids = _obra_ids_permitidas(user)

    props = _pares_con_propuesta(
        company_id=company_id, obra_id=obra_id, inicio=inicio, fin=fin, obra_ids=obra_ids,
    )
    fichas = _ym_con_fichaje(
        company_id=company_id, obra_id=obra_id, inicio=inicio, fin=fin, obra_ids=obra_ids,
    )

    # Agregar por mes: pendiente si algún par company+obra del alcance no está aceptado
    # y tiene señal.
    señal: set[tuple[int, int, int, int]] = set(props.keys()) | set(fichas)
    por_mes: dict[tuple[int, int], list[str]] = defaultdict(list)
    for cid, oid, anio, mes in señal:
        rows = props.get((cid, oid, anio, mes), [])
        if any(r.estado == 'aceptada' for r in rows):
            continue
        if any(r.estado == 'enviada' for r in rows):
            por_mes[(anio, mes)].append('en_curso')
        elif rows:
            por_mes[(anio, mes)].append('borrador')
        else:
            por_mes[(anio, mes)].append('sin_enviar')

    out: dict[tuple[int, int], str] = {}
    for ym, tags in por_mes.items():
        if 'en_curso' in tags:
            out[ym] = 'en_curso'
        elif 'borrador' in tags:
            out[ym] = 'borrador'
        else:
            out[ym] = 'sin_enviar'
    return out


def resumen_avisos(
    scope: str,
    *,
    anio: int,
    mes: int,
    company_id: int | None = None,
    obra_id: int | None = None,
    user=None,
    meses_atras: int = _MESES_ATRAS,
    meses_adelante: int = _MESES_ADELANTE,
) -> dict:
    """Datos para el selector de periodo."""
    raw = _meses_pendientes_raw(
        company_id=company_id,
        obra_id=obra_id,
        user=user,
        anio_ref=anio,
        mes_ref=mes,
        meses_atras=meses_atras,
        meses_adelante=meses_adelante,
    )
    dismissed = _load_dismissed()
    visibles: dict[tuple[int, int], str] = {}
    for ym, tag in raw.items():
        tok = _dismiss_token(scope, ym[0], ym[1])
        if tok in dismissed:
            continue
        visibles[ym] = tag

    ref = (anio, mes)
    actual = ref in visibles
    n_prev = sum(1 for ym in visibles if ym < ref)
    n_next = sum(1 for ym in visibles if ym > ref)
    pendientes = [
        {'anio': a, 'mes': m, 'motivo': visibles[(a, m)]}
        for a, m in sorted(visibles.keys(), reverse=True)
    ]
    # Botón quitar: si este mes tiene pendiente visible, o si está silenciado pero había raw
    puede_quitar = actual or (ref in raw and _dismiss_token(scope, anio, mes) in dismissed)
    silenciado = (not actual) and (ref in raw)

    return {
        'scope': scope,
        'actual': actual,
        'prev': n_prev,
        'next': n_next,
        'pendientes': pendientes,
        'puede_quitar': bool(ref in raw),  # hay algo que silenciar o ya silenciado
        'silenciado': silenciado,
        'motivo_actual': visibles.get(ref) or raw.get(ref),
    }
