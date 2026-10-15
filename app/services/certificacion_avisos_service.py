"""Avisos de certificación por mes (badges en el selector de periodo).

Aviso = hay acción pendiente visible en el hub:
  - recibida: la otra parte te envió una propuesta (aceptar / rechazar / contrapropuesta)
  - requerida: solo en portal subcontrata (Soltec pidió completar/enviar; no es aviso de oficina)

No cuenta fichaje sin abrir, borradores nunca enviados ni «meses sin cerrar».
Se puede silenciar por alcance+mes; un cambio real (enviar/aceptar/requerir/…) lo reactiva.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from app.models import CertificacionPropuesta
from app.services.config_service import get_tenant_config, set_tenant_config

CONFIG_DISMISSED = 'cert.avisos_dismissed'
_MESES_ATRAS = 17
_MESES_ADELANTE = 2

DIR_SUB = 'subcontrata_a_empresa'
DIR_EMP = 'empresa_a_subcontrata'


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
    anio_i, mes_i = inicio.year, inicio.month
    anio_f, mes_f = fin.year, fin.month
    rows = q.all()
    out: dict[tuple[int, int, int, int], list] = defaultdict(list)
    for r in rows:
        if (r.anio, r.mes) < (anio_i, mes_i) or (r.anio, r.mes) > (anio_f, mes_f):
            continue
        out[(r.company_id, r.obra_id, r.anio, r.mes)].append(r)
    return out


def _motivo_accion_pendiente(rows: list, *, vista_subcontrata: bool) -> str | None:
    """Motivo de aviso en el tejado del lado indicado, o None.

    ``requerida`` solo en el tejado de la subcontrata (Soltec le pidió completar).
    La oficina no lo ve como aviso: ella ya sabe que lo pidió; no es acción suya.
    """
    if any((r.estado or '') == 'aceptada' for r in rows):
        return None
    ajena_dir = DIR_EMP if vista_subcontrata else DIR_SUB
    by = {r.direccion: r for r in rows}
    ajena = by.get(ajena_dir)
    if ajena and (ajena.estado or '') == 'enviada':
        return 'recibida'
    # Solo la subcontrata tiene «requerida» pendiente en su tejado.
    if not vista_subcontrata:
        return None
    sub = by.get(DIR_SUB)
    if (
        sub
        and getattr(sub, 'requerida_at', None)
        and (sub.estado or '') == 'borrador'
    ):
        return 'requerida'
    return None


def pares_pendientes_mes(
    *,
    anio: int,
    mes: int,
    company_id: int | None = None,
    obra_id: int | None = None,
    user=None,
    vista_subcontrata: bool = False,
) -> dict[tuple[int, int], str]:
    """{(company_id, obra_id): motivo} con acción pendiente en tu tejado este mes."""
    inicio = date(int(anio), int(mes), 1)
    fa, fm = _shift_ym(anio, mes, 1)
    fin = date(fa, fm, 1)
    obra_ids = None if vista_subcontrata else _obra_ids_permitidas(user)
    props = _pares_con_propuesta(
        company_id=company_id, obra_id=obra_id, inicio=inicio, fin=fin, obra_ids=obra_ids,
    )
    out: dict[tuple[int, int], str] = {}
    for cid, oid, ay, mo in props:
        if (ay, mo) != (int(anio), int(mes)):
            continue
        motivo = _motivo_accion_pendiente(
            props.get((cid, oid, ay, mo), []),
            vista_subcontrata=vista_subcontrata,
        )
        if motivo:
            out[(cid, oid)] = motivo
    return out


def badge_pendientes_subcontrata(company_id: int | None) -> int:
    """Badge de nav de la subcontrata: pares (obra, mes) con acción en su tejado.

    Cuenta tanto «recibida» (oficina envió) como «requerida» (le pidieron
    completar). Antes el badge solo miraba propuestas enviadas de oficina y
    las requeridas no aparecían en la barra.
    """
    if not company_id:
        return 0
    rows = CertificacionPropuesta.query.filter_by(company_id=int(company_id)).all()
    by_pair: dict[tuple[int, int, int], list] = defaultdict(list)
    for r in rows:
        by_pair[(int(r.obra_id), int(r.anio), int(r.mes))].append(r)
    return sum(
        1
        for pair_rows in by_pair.values()
        if _motivo_accion_pendiente(pair_rows, vista_subcontrata=True)
    )


def _pares_pendientes_rango(
    *,
    company_id: int | None = None,
    obra_id: int | None = None,
    user=None,
    vista_subcontrata: bool = False,
    anio_ref: int,
    mes_ref: int,
    meses_atras: int = _MESES_ATRAS,
    meses_adelante: int = _MESES_ADELANTE,
) -> list[tuple[int, int, int, int, str]]:
    """[(company_id, obra_id, anio, mes, motivo), ...] en el rango alrededor del mes."""
    inicio_a, inicio_m = _shift_ym(anio_ref, mes_ref, -meses_atras)
    fin_a, fin_m = _shift_ym(anio_ref, mes_ref, meses_adelante)
    inicio = date(inicio_a, inicio_m, 1)
    fa, fm = _shift_ym(fin_a, fin_m, 1)
    fin = date(fa, fm, 1)
    obra_ids = None if vista_subcontrata else _obra_ids_permitidas(user)

    props = _pares_con_propuesta(
        company_id=company_id, obra_id=obra_id, inicio=inicio, fin=fin, obra_ids=obra_ids,
    )

    out: list[tuple[int, int, int, int, str]] = []
    for (cid, oid, anio, mes), rows in props.items():
        motivo = _motivo_accion_pendiente(rows, vista_subcontrata=vista_subcontrata)
        if motivo:
            out.append((cid, oid, anio, mes, motivo))
    return out


def _meses_desde_pares(
    pares: list[tuple[int, int, int, int, str]],
) -> dict[tuple[int, int], str]:
    """Agrega pares → {(anio, mes): motivo} (recibida manda sobre requerida)."""
    por_mes: dict[tuple[int, int], list[str]] = defaultdict(list)
    for _cid, _oid, anio, mes, motivo in pares:
        por_mes[(anio, mes)].append(motivo)
    out: dict[tuple[int, int], str] = {}
    for ym, tags in por_mes.items():
        out[ym] = 'recibida' if 'recibida' in tags else 'requerida'
    return out


def _meses_pendientes_raw(
    *,
    company_id: int | None = None,
    obra_id: int | None = None,
    user=None,
    vista_subcontrata: bool = False,
    anio_ref: int,
    mes_ref: int,
    meses_atras: int = _MESES_ATRAS,
    meses_adelante: int = _MESES_ADELANTE,
) -> dict[tuple[int, int], str]:
    """{(anio, mes): motivo} meses con acción pendiente en tu tejado."""
    return _meses_desde_pares(
        _pares_pendientes_rango(
            company_id=company_id,
            obra_id=obra_id,
            user=user,
            vista_subcontrata=vista_subcontrata,
            anio_ref=anio_ref,
            mes_ref=mes_ref,
            meses_atras=meses_atras,
            meses_adelante=meses_adelante,
        )
    )


def resumen_avisos(
    scope: str,
    *,
    anio: int,
    mes: int,
    company_id: int | None = None,
    obra_id: int | None = None,
    user=None,
    vista_subcontrata: bool = False,
    meses_atras: int = _MESES_ATRAS,
    meses_adelante: int = _MESES_ADELANTE,
) -> dict:
    """Datos para el selector de periodo.

    ``prev`` / ``next`` cuentan obras (pares empresa+obra) con aviso hacia
    atrás / delante — así una «requerida» suma igual que una «recibida».
    """
    pares = _pares_pendientes_rango(
        company_id=company_id,
        obra_id=obra_id,
        user=user,
        vista_subcontrata=vista_subcontrata,
        anio_ref=anio,
        mes_ref=mes,
        meses_atras=meses_atras,
        meses_adelante=meses_adelante,
    )
    raw = _meses_desde_pares(pares)
    dismissed = _load_dismissed()
    meses_silenciados = {
        ym for ym in raw
        if _dismiss_token(scope, ym[0], ym[1]) in dismissed
    }
    visibles_pares = [
        (cid, oid, ay, mo, motivo)
        for cid, oid, ay, mo, motivo in pares
        if (ay, mo) not in meses_silenciados
    ]
    visibles = _meses_desde_pares(visibles_pares)

    ref = (anio, mes)
    actual = ref in visibles
    n_prev = sum(1 for _c, _o, ay, mo, _m in visibles_pares if (ay, mo) < ref)
    n_next = sum(1 for _c, _o, ay, mo, _m in visibles_pares if (ay, mo) > ref)
    pendientes = [
        {'anio': a, 'mes': m, 'motivo': visibles[(a, m)]}
        for a, m in sorted(visibles.keys(), reverse=True)
    ]
    silenciado = (not actual) and (ref in raw)

    return {
        'scope': scope,
        'actual': actual,
        'prev': n_prev,
        'next': n_next,
        'pendientes': pendientes,
        'puede_quitar': bool(ref in raw),
        'silenciado': silenciado,
        'motivo_actual': visibles.get(ref) or raw.get(ref),
    }
