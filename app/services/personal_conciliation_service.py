"""Conciliación de personal: vínculos Odoo, duplicados por código de asistencia.

No hace merges automáticos. Acciones explícitas + historial reversible.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections import defaultdict

from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified

from app import db
from app.models import (
    Asignacion,
    AsignacionVehiculo,
    AusenciaConflicto,
    AusenciaPlanificada,
    FichajeEvento,
    InerciaCorte,
    Obra,
    Rating,
    RegistroFichaje,
    RegistroOdometro,
    User,
)
from app.services.config_service import get_tenant_config, set_tenant_config
from app.utils.timezone_utils import utc_now

logger = logging.getLogger(__name__)

_EXT_SUFFIX = re.compile(r'-EXT\d+$', re.I)
_ODOO_SUFFIX = re.compile(r'-ODOO\d+$', re.I)
_DEL_SUFFIX = re.compile(r'(-DEL-\d+|DEL-\d+)$', re.I)

CONFIG_LOG = 'conciliacion_personal_log'


def normalize_dni(dni: str | None) -> str:
    if not dni:
        return ''
    s = str(dni).strip().upper()
    s = _EXT_SUFFIX.sub('', s)
    s = _ODOO_SUFFIX.sub('', s)
    s = _DEL_SUFFIX.sub('', s)
    return s.strip()


def normalize_barcode(code: str | None) -> str:
    if not code:
        return ''
    return str(code).strip()


def odoo_ids_for_user(u: User | None) -> list[str]:
    """IDs Odoo vinculados a una ficha local (principal + aliases)."""
    if not u:
        return []
    ext = u.external_ids or {}
    out: list[str] = []
    primary = str(ext.get('odoo') or '').strip()
    if primary:
        out.append(primary)
    for raw in ext.get('odoo_alias_ids') or []:
        s = str(raw).strip()
        if s and s not in out:
            out.append(s)
    for raw in ext.get('odoo_aliases') or []:
        if isinstance(raw, dict):
            s = str(raw.get('odoo_id') or '').strip()
        else:
            s = str(raw).strip()
        if s and s not in out:
            out.append(s)
    return out


def find_user_by_any_odoo(oid: str | int | None, *, include_deleted: bool = False) -> User | None:
    """Resuelve usuario local por ID Odoo principal o alias."""
    from sqlalchemy import text

    key = str(oid or '').strip()
    if not key:
        return None
    deleted_sql = '' if include_deleted else 'AND NOT COALESCE(is_deleted, false)'
    row = db.session.execute(
        text(
            f"""
            SELECT id FROM users
            WHERE (
                external_ids->>'odoo' = :oid
                OR (external_ids->'odoo_alias_ids') ? :oid
            )
            {deleted_sql}
            ORDER BY id
            LIMIT 1
            """
        ),
        {'oid': key},
    ).first()
    if not row:
        return None
    return User.query.get(int(row[0]))


def _user_barcode(u: User) -> str:
    return normalize_barcode((u.external_ids or {}).get('barcode'))


def _set_user_barcode(u: User, barcode: str | None) -> None:
    ext = dict(u.external_ids or {})
    code = normalize_barcode(barcode)
    if code:
        ext['barcode'] = code
    else:
        ext.pop('barcode', None)
    u.external_ids = ext
    flag_modified(u, 'external_ids')


def _user_card(u: User, *, stats: dict | None = None) -> dict:
    company = u.company_rel
    odoo_id = (u.external_ids or {}).get('odoo')
    st = stats or {}
    return {
        'id': u.id,
        'label': f'{(u.name or "").strip()} {(u.lastname or "").strip()}'.strip() or f'#{u.id}',
        'dni': u.dni or '',
        'dni_base': normalize_dni(u.dni),
        'barcode': _user_barcode(u),
        'email': u.email or '',
        'role': u.role or '',
        'tipo': u.tipo_empleado,
        'company_id': u.company_id,
        'company': company.nombre if company else '—',
        'odoo_id': str(odoo_id) if odoo_id else None,
        'active': bool(u.active) and not bool(u.is_deleted),
        'url': f'/admin/worker_panel/{u.id}',
        'asignaciones_count': int(st.get('asignaciones_count') or 0),
        'dias_asignados': int(st.get('dias_asignados') or 0),
        'primera_asignacion': st.get('primera_asignacion'),
        'ultima_asignacion': st.get('ultima_asignacion'),
    }


def _asignaciones_stats_by_user(user_ids: list[int]) -> dict[int, dict]:
    """Conteos de historial de planificación por persona (para decidir merges)."""
    from sqlalchemy import func

    ids = sorted({int(x) for x in user_ids if x})
    if not ids:
        return {}
    rows = (
        db.session.query(
            Asignacion.user_id,
            func.count(Asignacion.id),
            func.count(func.distinct(Asignacion.fecha)),
            func.min(Asignacion.fecha),
            func.max(Asignacion.fecha),
        )
        .filter(Asignacion.user_id.in_(ids))
        .group_by(Asignacion.user_id)
        .all()
    )
    out: dict[int, dict] = {}
    for uid, n, dias, primera, ultima in rows:
        out[int(uid)] = {
            'asignaciones_count': int(n or 0),
            'dias_asignados': int(dias or 0),
            'primera_asignacion': primera.isoformat() if primera else None,
            'ultima_asignacion': ultima.isoformat() if ultima else None,
        }
    return out


def _name_similarity(a: User, b: User) -> float:
    """Delegado; la lógica estricta está en _pair_name_score / _name_tokens."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta | tb), 1)


# ----- historial / decisiones -----

def _load_log() -> list[dict]:
    raw = get_tenant_config(CONFIG_LOG, default='') or ''
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
        return list(data.get('entries') or [])
    except Exception:
        return []


def _save_log(entries: list[dict]) -> None:
    # Mantener últimas 200
    set_tenant_config(CONFIG_LOG, json.dumps({'entries': entries[-200:]}, default=str))
    db.session.commit()


def _append_log(action: str, summary: str, payload: dict, *, actor) -> dict:
    entries = _load_log()
    entry = {
        'id': str(uuid.uuid4()),
        'at': utc_now().isoformat(),
        'actor_id': getattr(actor, 'id', None),
        'actor_name': (
            f'{getattr(actor, "name", "")} {getattr(actor, "lastname", "")}'.strip()
            or str(getattr(actor, 'id', ''))
        ),
        'action': action,
        'summary': summary,
        'payload': payload,
        'undone': False,
        'undone_at': None,
    }
    entries.append(entry)
    _save_log(entries)
    return entry


def list_log_entries(*, include_undone: bool = True) -> list[dict]:
    entries = _load_log()
    if not include_undone:
        entries = [e for e in entries if not e.get('undone')]
    return list(reversed(entries))


def active_maintain_keys() -> set[str]:
    keys = set()
    for e in _load_log():
        if e.get('undone') or e.get('action') != 'maintain':
            continue
        key = (e.get('payload') or {}).get('group_key')
        if key:
            keys.add(key)
    return keys


def group_key_for_users(user_ids: list[int], barcode: str | None = None) -> str:
    if barcode:
        return f'barcode:{normalize_barcode(barcode)}'
    ids = '-'.join(str(i) for i in sorted(int(x) for x in user_ids))
    return f'users:{ids}'


def list_plantilla_users(limit: int = 2000) -> list[dict]:
    rows = (
        User.query
        .options(joinedload(User.company_rel))
        .filter(User.is_deleted.is_(False), User.active.is_(True))
        .order_by(User.lastname.asc(), User.name.asc())
        .limit(limit)
        .all()
    )
    return [_user_card(u) for u in rows]


def enrich_barcodes_from_odoo(limit: int = 400) -> int:
    """Rellena external_ids.barcode desde Odoo (hr.employee.barcode / partner.barcode)."""
    from app.sync.dispatcher import get_sync_adapter

    adapter = get_sync_adapter()
    enrich_fn = getattr(adapter, 'fetch_barcodes_for_ids', None)
    if not callable(enrich_fn):
        return 0

    users = (
        User.query
        .filter(
            User.is_deleted.is_(False),
            User.external_ids.has_key('odoo'),
        )
        .limit(limit)
        .all()
    )
    emp_ids = []
    partner_ids = []
    by_oid = {}
    for u in users:
        ext = u.external_ids or {}
        oid = str(ext.get('odoo') or '')
        if not oid.isdigit():
            continue
        model = (ext.get('odoo_model') or '').strip()
        tipo = u.tipo_empleado
        if model == 'res.partner' or (not model and tipo == 'EXTERNO'):
            partner_ids.append(int(oid))
            by_oid[('partner', oid)] = u
        else:
            emp_ids.append(int(oid))
            by_oid[('employee', oid)] = u

    updated = 0
    try:
        mapping = enrich_fn(employee_ids=emp_ids, partner_ids=partner_ids) or {}
    except Exception:
        logger.exception('enrich_barcodes_from_odoo falló')
        return 0

    for (kind, oid), code in mapping.items():
        u = by_oid.get((kind, str(oid)))
        if not u:
            continue
        if _user_barcode(u) == normalize_barcode(code):
            continue
        _set_user_barcode(u, code)
        db.session.add(u)
        updated += 1
    if updated:
        db.session.commit()
    return updated


_NAME_STOPWORDS = frozenset({
    'de', 'del', 'la', 'las', 'los', 'y', 'e', 'da', 'do', 'van', 'von', 'el',
})


def _name_tokens(u: User) -> set[str]:
    raw = f'{(u.name or "")} {(u.lastname or "")}'.lower()
    return {
        t for t in re.split(r'\W+', raw)
        if len(t) > 2 and t not in _NAME_STOPWORDS
    }


def _looks_like_person_dni(dni: str | None) -> bool:
    """True si parece DNI/NIE personal (no CIF de empresa ni EXT-…)."""
    s = normalize_dni(dni)
    if not s or s.startswith('EXT'):
        return False
    if re.match(r'^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$', s):
        return False
    if re.match(r'^\d{7,8}[A-Z]$', s):
        return True
    if re.match(r'^[XYZ]\d{7}[A-Z]$', s):
        return True
    return False


def _pair_name_score(a: User, b: User) -> float:
    """Similitud estricta 0..1 (mismos tokens → 1.0; si no, ≥2 en común)."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    inter = ta & tb
    if len(inter) < 2:
        return 0.0
    return len(inter) / max(len(ta | tb), 1)


def list_duplicate_candidates(limit: int = 80, name_threshold: float = 0.66) -> list[dict]:
    """Candidatos a conciliar.

    - Código asistencia / DNI interno → grupos por clave exacta
    - Nombre → un grupo por conjunto de tokens idéntico (Hassan Ali / Ali Hassan / … juntos)
    """
    maintain = active_maintain_keys()
    users = (
        User.query
        .options(joinedload(User.company_rel))
        .filter(User.is_deleted.is_(False), User.active.is_(True))
        .all()
    )
    out: list[dict] = []
    stats_cache: dict[int, dict] = {}

    def _cards_for(group_users: list) -> list[dict]:
        missing = [u.id for u in group_users if u.id not in stats_cache]
        if missing:
            stats_cache.update(_asignaciones_stats_by_user(missing))
        return [_user_card(u, stats=stats_cache.get(u.id)) for u in group_users]

    def _is_maintained(gkey: str, extra_keys=None) -> bool:
        if gkey in maintain:
            return True
        if extra_keys and (set(extra_keys) & maintain):
            return True
        return False

    def _append_group(group_users: list, reasons: set, *, barcode: str = '', dni: str = '') -> None:
        if len(group_users) < 2:
            return
        ids = [u.id for u in group_users]
        gkey = group_key_for_users(ids, barcode=barcode or None)
        extra = []
        if barcode:
            extra.append(group_key_for_users(ids, barcode=barcode))
        maintained = _is_maintained(gkey, extra)
        sims = []
        for i, a in enumerate(group_users):
            for b in group_users[i + 1:]:
                sims.append(_pair_name_score(a, b))
        reason_labels = []
        if 'barcode' in reasons:
            reason_labels.append('código asistencia')
        if 'dni_interno' in reasons:
            reason_labels.append('DNI interno')
        if 'nombre' in reasons:
            reason_labels.append('nombre parecido')
        out.append({
            'kind': 'group' if len(group_users) > 2 else 'pair',
            'barcode': barcode or '',
            'barcodes': [barcode] if barcode else [],
            'dnis': [dni] if dni else [],
            'reasons': sorted(reasons),
            'reason_labels': reason_labels,
            'group_key': gkey,
            'users': _cards_for(group_users),
            'name_similarity': round(
                max(sims) if sims else (
                    1.0 if ('barcode' in reasons or 'dni_interno' in reasons) else 0.0
                ),
                2,
            ),
            'maintained': maintained,
            'status': 'maintained' if maintained else 'pending',
        })

    by_code: dict = defaultdict(list)
    for u in users:
        code = _user_barcode(u)
        if len(code) >= 1:
            by_code[code].append(u)
    for code, group in by_code.items():
        if len(group) >= 2:
            _append_group(group, {'barcode'}, barcode=code)

    by_dni: dict = defaultdict(list)
    for u in users:
        if u.tipo_empleado != 'INTERNO':
            continue
        dni = normalize_dni(u.dni)
        if not _looks_like_person_dni(dni):
            continue
        by_dni[dni].append(u)
    for dni, group in by_dni.items():
        if len(group) >= 2:
            _append_group(group, {'dni_interno'}, dni=dni)

    # Nombre: un solo bloque por conjunto de tokens idéntico (≥2 tokens)
    by_tokens: dict[frozenset[str], list] = defaultdict(list)
    for u in users:
        toks = _name_tokens(u)
        if len(toks) < 2:
            continue
        by_tokens[frozenset(toks)].append(u)

    for _toks, group in by_tokens.items():
        if len(group) < 2:
            continue
        gids = {u.id for u in group}
        already = any(
            gids.issubset({x['id'] for x in item['users']})
            and ('barcode' in item['reasons'] or 'dni_interno' in item['reasons'])
            for item in out
        )
        if already:
            continue
        codes = {_user_barcode(u) for u in group if _user_barcode(u)}
        if len(codes) > 1:
            continue
        _append_group(group, {'nombre'})

    deduped = []
    seen_g = set()
    for item in out:
        if item['group_key'] in seen_g:
            continue
        seen_g.add(item['group_key'])
        deduped.append(item)

    deduped.sort(key=lambda c: (c['maintained'], -c['name_similarity'], -len(c['users']), c['group_key']))
    return deduped[:limit]


def list_barcode_candidates(limit: int = 80) -> list[dict]:
    """Compat: alias del detector inteligente."""
    return list_duplicate_candidates(limit=limit)


def search_users(q: str, limit: int = 25) -> list[dict]:
    q = (q or '').strip()
    if len(q) < 2:
        return []
    like = f'%{q}%'
    rows = (
        User.query
        .options(joinedload(User.company_rel))
        .filter(
            User.is_deleted.is_(False),
            or_(
                User.name.ilike(like),
                User.lastname.ilike(like),
                User.dni.ilike(like),
                User.email.ilike(like),
            ),
        )
        .order_by(User.lastname.asc(), User.name.asc())
        .limit(limit)
        .all()
    )
    return [_user_card(u) for u in rows]


def search_odoo_by_dni(dni: str) -> list[dict]:
    """Compat: busca por DNI/código; también acepta nombre (ver search_odoo_people)."""
    return search_odoo_people(dni)


def search_odoo_people(query: str) -> list[dict]:
    """Busca en Odoo por DNI/NIF, código de asistencia y/o nombre."""
    from app.sync.dispatcher import get_sync_adapter

    adapter = get_sync_adapter()
    search_dni_fn = getattr(adapter, 'search_people_by_dni', None)
    search_name_fn = getattr(adapter, 'search_people_by_name', None)
    if not callable(search_dni_fn) and not callable(search_name_fn):
        raise ValueError('Este conector no permite buscar personas en Odoo')

    raw = (query or '').strip()
    if len(raw) < 3:
        return []

    hits: list[dict] = []
    seen: set[tuple] = set()

    def _add(batch: list) -> None:
        for h in batch or []:
            key = (str(h.get('source') or ''), str(h.get('odoo_id') or ''))
            if not key[1] or key in seen:
                continue
            seen.add(key)
            hits.append(h)

    # 1) DNI / barcode (exacto y variantes)
    if callable(search_dni_fn):
        base = normalize_dni(raw) or raw
        _add(search_dni_fn(base) or [])
        if raw != base:
            _add(search_dni_fn(raw) or [])

    # 2) Nombre (siempre, para listar ocurrencias; si "Juan" hay muchas, OK)
    if callable(search_name_fn):
        # Evita barrer por nombre cuando la query parece un DNI/código puro
        # (muchos dígitos / patrón identificación), salvo que no hubiera hits.
        looks_id = bool(re.match(r'^[0-9A-Za-z.\-/]{5,}$', raw)) and any(c.isdigit() for c in raw)
        if not looks_id or not hits:
            _add(search_name_fn(raw) or [])

    out = []
    for h in hits:
        oid = str(h.get('odoo_id') or '')
        linked = find_user_by_any_odoo(oid)
        if linked:
            linked = (
                User.query
                .options(joinedload(User.company_rel))
                .filter(User.id == linked.id)
                .first()
            )
        item = dict(h)
        item['already_linked'] = _user_card(linked) if linked else None
        out.append(item)
    return out


def link_local_to_odoo(
    local_user_id: int,
    odoo_id: int | str,
    *,
    source: str = 'employee',
    force: bool = False,
    actor=None,
    barcode: str | None = None,
    extra_links: list[dict] | None = None,
) -> dict:
    """Vincula una ficha local a uno o varios registros Odoo.

    El primero (odoo_id/source/barcode) es el vínculo principal.
    extra_links: [{odoo_id, source, barcode}, ...] → aliases de sincronización.
    """
    user = User.query.get(local_user_id)
    if not user or user.is_deleted:
        raise ValueError('Usuario local no encontrado')

    links: list[dict] = [{
        'odoo_id': odoo_id,
        'source': source,
        'barcode': barcode,
    }]
    for raw in extra_links or []:
        if not raw:
            continue
        links.append({
            'odoo_id': raw.get('odoo_id'),
            'source': raw.get('source') or 'employee',
            'barcode': raw.get('barcode'),
        })

    normalized: list[dict] = []
    seen_oids: set[str] = set()
    for link in links:
        oid = str(link.get('odoo_id') or '').strip()
        if not oid.isdigit():
            raise ValueError(f'ID Odoo inválido: {link.get("odoo_id")!r}')
        if oid in seen_oids:
            continue
        seen_oids.add(oid)
        src = (link.get('source') or 'employee').strip().lower()
        if src not in ('employee', 'partner'):
            raise ValueError('Origen Odoo inválido (employee o partner)')
        normalized.append({
            'odoo_id': oid,
            'source': src,
            'barcode': normalize_barcode(link.get('barcode')),
            'odoo_model': 'hr.employee' if src == 'employee' else 'res.partner',
        })

    if not normalized:
        raise ValueError('Indica al menos un registro Odoo')

    # Otros locales ya ligados a alguno de estos IDs
    conflicts = []
    for link in normalized:
        other = find_user_by_any_odoo(link['odoo_id'])
        if other and other.id != user.id:
            conflicts.append(other)
    # unique by id
    uniq_conflicts = []
    seen_c = set()
    for c in conflicts:
        if c.id in seen_c:
            continue
        seen_c.add(c.id)
        uniq_conflicts.append(c)

    if uniq_conflicts and not force:
        labels = ', '.join(
            f'{c.name} {c.lastname} (#{c.id})'.strip() for c in uniq_conflicts
        )
        raise ValueError(
            f'Uno o más registros Odoo ya están vinculados a: {labels}. '
            f'Confirma forzar para unificar esas fichas aquí.'
        )

    merged_ids = []
    for other in uniq_conflicts:
        merge_users(
            user.id,
            other.id,
            actor_id=getattr(actor, 'id', None),
            actor=actor,
        )
        merged_ids.append(other.id)
        # refresh keep after merges
        user = User.query.get(local_user_id)

    prev = (user.external_ids or {}).get('odoo')
    prev_model = (user.external_ids or {}).get('odoo_model')
    prev_aliases = list((user.external_ids or {}).get('odoo_alias_ids') or [])
    prev_alias_detail = list((user.external_ids or {}).get('odoo_aliases') or [])

    primary = normalized[0]
    alias_detail = []
    alias_ids = []
    for link in normalized[1:]:
        alias_ids.append(link['odoo_id'])
        alias_detail.append({
            'odoo_id': link['odoo_id'],
            'odoo_model': link['odoo_model'],
            'barcode': link['barcode'] or None,
        })

    ext = dict(user.external_ids or {})
    ext['odoo'] = primary['odoo_id']
    ext['odoo_model'] = primary['odoo_model']
    if primary['barcode']:
        ext['barcode'] = primary['barcode']
    elif not ext.get('barcode'):
        for link in normalized[1:]:
            if link['barcode']:
                ext['barcode'] = link['barcode']
                break
    if alias_ids:
        ext['odoo_alias_ids'] = alias_ids
        ext['odoo_aliases'] = alias_detail
    else:
        ext.pop('odoo_alias_ids', None)
        ext.pop('odoo_aliases', None)
    user.external_ids = ext
    flag_modified(user, 'external_ids')
    db.session.add(user)
    db.session.commit()

    oids_txt = ', '.join(f"#{x['odoo_id']}" for x in normalized)
    entry = _append_log(
        'link',
        f'Vínculo Odoo {oids_txt} → {_user_card(user)["label"]}',
        {
            'local_user_id': user.id,
            'odoo_id': primary['odoo_id'],
            'odoo_ids': [x['odoo_id'] for x in normalized],
            'source': primary['source'],
            'links': normalized,
            'previous_odoo_id': str(prev) if prev else None,
            'previous_odoo_model': prev_model,
            'previous_odoo_alias_ids': prev_aliases,
            'previous_odoo_aliases': prev_alias_detail,
            'merged_user_ids': merged_ids,
            'barcode': ext.get('barcode'),
        },
        actor=actor,
    )
    return {
        'user': _user_card(user),
        'previous_odoo_id': str(prev) if prev else None,
        'odoo_id': primary['odoo_id'],
        'odoo_ids': [x['odoo_id'] for x in normalized],
        'source': primary['source'],
        'merged_user_ids': merged_ids,
        'log_id': entry['id'],
    }


def maintain_group(user_ids: list[int], *, barcode: str | None = None, group_key: str | None = None, actor=None) -> dict:
    ids = sorted({int(x) for x in user_ids})
    if len(ids) < 2:
        raise ValueError('Se necesitan al menos dos personas para mantener por separado')
    users = User.query.filter(User.id.in_(ids), User.is_deleted.is_(False)).all()
    if len(users) < 2:
        raise ValueError('Usuarios no encontrados')
    code = normalize_barcode(barcode) or _user_barcode(users[0])
    gkey = (group_key or '').strip() or group_key_for_users(ids, barcode=code or None)
    labels = ', '.join(_user_card(u)['label'] for u in users)
    entry = _append_log(
        'maintain',
        f'Mantener separados ({code or "grupo"}): {labels}',
        {
            'group_key': gkey,
            'user_ids': ids,
            'barcode': code or None,
            'labels': [_user_card(u)['label'] for u in users],
        },
        actor=actor,
    )
    return {'group_key': gkey, 'log_id': entry['id'], 'entry': entry}


def _transfer_fichaje_ledger(from_id: int, to_id: int, *, actor_id: int | None = None) -> int:
    """Mueve jornada del libro sin UPDATE/DELETE: anula en origen y reescribe en destino."""
    from app.models import ORIGEN_ADMIN
    from app.services.fichaje_ledger_service import (
        anular_evento,
        proyectar_dia,
        registrar_evento,
        vigentes,
    )

    todos = (
        FichajeEvento.query
        .filter(FichajeEvento.user_id == from_id)
        .order_by(FichajeEvento.secuencia.asc())
        .all()
    )
    if not todos:
        return 0

    activos = vigentes(todos)
    if not activos:
        return 0

    autor = actor_id or to_id
    motivo_base = (
        f'Conciliación personal: unificado usuario #{from_id} → #{to_id}'
    )
    fechas: set = set()
    transferidos = 0

    for ev in activos:
        anular_evento(
            ev.id,
            motivo=motivo_base,
            autor_id=autor,
            origen=ORIGEN_ADMIN,
        )
        ext = dict(ev.external_ids or {})
        ext['conciliacion_desde_evento_id'] = ev.id
        ext['conciliacion_desde_user_id'] = from_id
        registrar_evento(
            user_id=to_id,
            tipo=ev.tipo,
            origen=ORIGEN_ADMIN,
            ocurrido_en=ev.ocurrido_en,
            fecha_laboral=ev.fecha_laboral,
            autor_id=autor,
            obra_id=ev.obra_id,
            latitud=ev.latitud,
            longitud=ev.longitud,
            precision_metros=ev.precision_metros,
            geo_estado=ev.geo_estado,
            distancia_obra_metros=ev.distancia_obra_metros,
            nota_ubicacion=ev.nota_ubicacion,
            dispositivo=ev.dispositivo,
            ip=ev.ip,
            motivo=f'{motivo_base} (secuencia origen #{ev.secuencia})',
            external_ids=ext,
            zona_horaria=ev.zona_horaria,
        )
        fechas.add(ev.fecha_laboral)
        transferidos += 1

    for fecha in sorted(fechas):
        proyectar_dia(from_id, fecha)
        proyectar_dia(to_id, fecha)

    return transferidos


def _reassign_user_fks(from_id: int, to_id: int, *, actor_id: int | None = None) -> dict:
    moved = {
        'asignaciones': 0,
        'asignaciones_omitidas': 0,
        'fichajes': 0,
        'fichajes_omitidos': 0,
        'eventos': 0,
        'vehiculos': 0,
        'vehiculos_omitidos': 0,
        'odometros': 0,
        'ausencias': 0,
        'obras_jefe': 0,
        'obras_encargado': 0,
        'ratings': 0,
        'inercia': 0,
    }

    # Libro inalterable: nunca UPDATE/DELETE en fichajes_eventos
    moved['eventos'] = _transfer_fichaje_ledger(from_id, to_id, actor_id=actor_id)

    for a in Asignacion.query.filter_by(user_id=from_id).all():
        exists = Asignacion.query.filter_by(
            obra_id=a.obra_id, user_id=to_id, fecha=a.fecha
        ).first()
        if exists:
            db.session.delete(a)
            moved['asignaciones_omitidas'] += 1
        else:
            a.user_id = to_id
            moved['asignaciones'] += 1

    for f in RegistroFichaje.query.filter_by(user_id=from_id).all():
        clash = (
            RegistroFichaje.query
            .filter(
                RegistroFichaje.user_id == to_id,
                RegistroFichaje.fecha == f.fecha,
                RegistroFichaje.id != f.id,
            )
            .first()
        )
        if clash:
            db.session.delete(f)
            moved['fichajes_omitidos'] += 1
        else:
            f.user_id = to_id
            moved['fichajes'] += 1

    for av in AsignacionVehiculo.query.filter_by(user_id=from_id).all():
        exists = AsignacionVehiculo.query.filter_by(user_id=to_id, fecha=av.fecha).first()
        if exists:
            db.session.delete(av)
            moved['vehiculos_omitidos'] += 1
        else:
            av.user_id = to_id
            moved['vehiculos'] += 1

    moved['odometros'] = (
        RegistroOdometro.query.filter_by(planned_user_id=from_id)
        .update({RegistroOdometro.planned_user_id: to_id}, synchronize_session=False)
    )
    moved['ausencias'] = (
        AusenciaPlanificada.query.filter_by(user_id=from_id)
        .update({AusenciaPlanificada.user_id: to_id}, synchronize_session=False)
    )
    AusenciaConflicto.query.filter_by(user_id=from_id).update(
        {AusenciaConflicto.user_id: to_id}, synchronize_session=False
    )
    moved['obras_jefe'] = (
        Obra.query.filter_by(jefe_obra_id=from_id)
        .update({Obra.jefe_obra_id: to_id}, synchronize_session=False)
    )
    moved['obras_encargado'] = (
        Obra.query.filter_by(encargado_id=from_id)
        .update({Obra.encargado_id: to_id}, synchronize_session=False)
    )
    moved['ratings'] = (
        Rating.query.filter_by(user_id=from_id)
        .update({Rating.user_id: to_id}, synchronize_session=False)
    )
    for ic in InerciaCorte.query.filter_by(user_id=from_id).all():
        if InerciaCorte.query.filter_by(user_id=to_id, fecha=ic.fecha).first():
            db.session.delete(ic)
        else:
            ic.user_id = to_id
            moved['inercia'] += 1

    return moved


def _merge_odoo_ids(keep: User, absorb: User) -> None:
    """Pasa vínculos Odoo del absorbido al que se conserva.

    Si el keep ya tiene un odoo distinto (p.ej. hr.employee) y el absorbido
    traía otro (p.ej. res.partner de subcontrata), el partner NO se pierde:
    pasa a odoo_alias_ids. Si se pierde, el sync de subcontratas intenta
    recrear al externo y choca con el email sintético del archivado.
    """
    keep_ext = dict(keep.external_ids or {})
    abs_ext = dict(absorb.external_ids or {})

    keep_oids = set(odoo_ids_for_user(keep))
    abs_oids = odoo_ids_for_user(absorb)

    alias_ids = [str(x) for x in (keep_ext.get('odoo_alias_ids') or []) if str(x).strip()]
    alias_detail = list(keep_ext.get('odoo_aliases') or [])
    if not isinstance(alias_detail, list):
        alias_detail = []

    def _add_alias(oid: str, model: str | None = None, barcode: str | None = None):
        oid = str(oid or '').strip()
        if not oid or oid in keep_oids:
            return
        keep_oids.add(oid)
        if oid not in alias_ids:
            alias_ids.append(oid)
        alias_detail.append({
            'odoo_id': oid,
            'odoo_model': model or abs_ext.get('odoo_model') or 'res.partner',
            'barcode': barcode or None,
        })

    abs_primary = str(abs_ext.get('odoo') or '').strip()
    if abs_primary:
        if not keep_ext.get('odoo'):
            keep_ext['odoo'] = abs_primary
            if abs_ext.get('odoo_model'):
                keep_ext['odoo_model'] = abs_ext['odoo_model']
            keep_oids.add(abs_primary)
        elif abs_primary not in keep_oids:
            _add_alias(abs_primary, abs_ext.get('odoo_model'), abs_ext.get('barcode'))

    for raw in abs_ext.get('odoo_alias_ids') or []:
        _add_alias(str(raw))
    for raw in abs_ext.get('odoo_aliases') or []:
        if isinstance(raw, dict):
            _add_alias(raw.get('odoo_id'), raw.get('odoo_model'), raw.get('barcode'))
        else:
            _add_alias(raw)

    if abs_ext.get('barcode') and not keep_ext.get('barcode'):
        keep_ext['barcode'] = abs_ext['barcode']

    if alias_ids:
        keep_ext['odoo_alias_ids'] = alias_ids
        keep_ext['odoo_aliases'] = alias_detail

    abs_base = normalize_dni(absorb.dni)
    keep_base = normalize_dni(keep.dni)
    if abs_base and keep_base == abs_base:
        if keep.dni and ('-EXT' in keep.dni.upper() or '-ODOO' in keep.dni.upper()):
            if absorb.dni and '-EXT' not in absorb.dni.upper() and '-ODOO' not in absorb.dni.upper():
                keep._pending_dni = absorb.dni  # type: ignore[attr-defined]

    keep.external_ids = keep_ext
    flag_modified(keep, 'external_ids')

    # Liberar ids Odoo en la ficha absorbida (ya viven en keep).
    changed_abs = False
    for key in ('odoo', 'odoo_model', 'odoo_alias_ids', 'odoo_aliases', 'barcode'):
        if key in abs_ext:
            abs_ext.pop(key, None)
            changed_abs = True
    if changed_abs:
        absorb.external_ids = abs_ext
        flag_modified(absorb, 'external_ids')


def _mark_merged_archive(absorb: User, keep: User, *, actor_id: int | None = None) -> str:
    """Archiva la ficha absorbida con motivo explícito de unificación."""
    from app.models import SystemLog
    from app.utils.timezone_utils import utc_now

    keep_label = f'{(keep.name or "").strip()} {(keep.lastname or "").strip()}'.strip() or f'#{keep.id}'
    motivo = (
        f'Unificado por conciliación de personal en «{keep_label}» (#{keep.id}). '
        f'Esta ficha se archiva; el contacto vivo queda en ese registro.'
    )
    # Liberar email antes del soft_delete: soft_delete solo libera DNI.
    # Si no, el sync de subcontratas choca con ext_*@subcontrata.local.
    old_email = (absorb.email or '').strip()
    if old_email:
        absorb.email = f"merged_{absorb.id}_{old_email}"
        if len(absorb.email) > 120:
            absorb.email = f"merged_{absorb.id}@subcontrata.local"

    absorb.soft_delete(actor_id=actor_id)
    absorb.deactivation_reason = 'merged'
    ext = dict(absorb.external_ids or {})
    ext['merged_into_user_id'] = keep.id
    ext['merged_into_label'] = keep_label
    ext['merged_reason'] = motivo
    ext['merged_at'] = utc_now().isoformat()
    if old_email:
        ext['merged_from_email'] = old_email
    absorb.external_ids = ext
    flag_modified(absorb, 'external_ids')
    db.session.add(SystemLog(
        user_id=actor_id,
        category='personal',
        action='conciliacion_merge',
        detail=motivo,
        target_user_id=absorb.id,
    ))
    return motivo


def merge_users(keep_id: int, absorb_id: int, *, actor_id: int | None = None, actor=None) -> dict:
    if keep_id == absorb_id:
        raise ValueError('Debes elegir dos personas distintas')
    keep = User.query.get(keep_id)
    absorb = User.query.get(absorb_id)
    if not keep or not absorb:
        raise ValueError('Usuario no encontrado')
    if keep.is_deleted or absorb.is_deleted:
        raise ValueError('Uno de los usuarios ya está archivado')

    absorb_snapshot = _user_card(absorb, stats=_asignaciones_stats_by_user([absorb.id]).get(absorb.id))
    actor_uid = actor_id or getattr(actor, 'id', None)
    moved = _reassign_user_fks(absorb_id, keep_id, actor_id=actor_uid)
    _merge_odoo_ids(keep, absorb)

    pending_dni = getattr(keep, '_pending_dni', None)
    merge_motivo = _mark_merged_archive(absorb, keep, actor_id=actor_uid)
    db.session.flush()
    if pending_dni:
        clash = User.query.filter(User.dni == pending_dni, User.id != keep.id).first()
        if not clash:
            keep.dni = pending_dni

    db.session.add(keep)
    db.session.add(absorb)
    db.session.commit()

    entry = _append_log(
        'merge',
        f'Unificar: conservar {_user_card(keep)["label"]}, archivar {absorb_snapshot["label"]}',
        {
            'keep_id': keep.id,
            'absorb_id': absorb.id,
            'absorb_snapshot': absorb_snapshot,
            'moved': moved,
            'merge_motivo': merge_motivo,
        },
        actor=actor,
    )
    return {
        'keep': _user_card(keep),
        'absorbed_id': absorb_id,
        'moved': moved,
        'log_id': entry['id'],
        'merge_motivo': merge_motivo,
    }


def promote_as_internal(user_id: int, company_id: int | None = None, *, actor=None) -> dict:
    from app.models import Company

    user = User.query.get(user_id)
    if not user or user.is_deleted:
        raise ValueError('Usuario no encontrado')
    prev_company = user.company_id
    if company_id:
        company = Company.query.get(company_id)
    else:
        company = Company.query.filter_by(is_internal=True, active=True).order_by(Company.id).first()
    if not company or not company.is_internal:
        raise ValueError('No hay empresa interna disponible')
    user.company_id = company.id
    db.session.add(user)
    db.session.commit()
    card = _user_card(user)
    entry = _append_log(
        'promote',
        f'Marcar como interno: {card["label"]} → {company.nombre}',
        {
            'user_id': user.id,
            'previous_company_id': prev_company,
            'company_id': company.id,
        },
        actor=actor,
    )
    return {**card, 'log_id': entry['id']}


def undo_log_entry(entry_id: str, *, actor=None) -> dict:
    entries = _load_log()
    entry = next((e for e in entries if e.get('id') == entry_id), None)
    if not entry:
        raise ValueError('Entrada no encontrada')
    if entry.get('undone'):
        raise ValueError('Ya estaba deshecha')

    action = entry.get('action')
    payload = entry.get('payload') or {}

    if action == 'maintain':
        pass  # solo marcar undone → vuelve a salir como pendiente

    elif action == 'link':
        uid = payload.get('local_user_id')
        user = User.query.get(uid) if uid else None
        if user:
            ext = dict(user.external_ids or {})
            prev = payload.get('previous_odoo_id')
            if prev:
                ext['odoo'] = str(prev)
                if payload.get('previous_odoo_model'):
                    ext['odoo_model'] = payload['previous_odoo_model']
            else:
                ext.pop('odoo', None)
                ext.pop('odoo_model', None)
            prev_aliases = payload.get('previous_odoo_alias_ids')
            prev_alias_detail = payload.get('previous_odoo_aliases')
            if prev_aliases:
                ext['odoo_alias_ids'] = list(prev_aliases)
            else:
                ext.pop('odoo_alias_ids', None)
            if prev_alias_detail:
                ext['odoo_aliases'] = list(prev_alias_detail)
            else:
                ext.pop('odoo_aliases', None)
            user.external_ids = ext
            flag_modified(user, 'external_ids')
            db.session.add(user)
        stolen = payload.get('stolen_from') or {}
        if stolen.get('id') and stolen.get('odoo'):
            other = User.query.get(stolen['id'])
            if other and not other.is_deleted:
                oext = dict(other.external_ids or {})
                oext['odoo'] = str(stolen['odoo'])
                if stolen.get('odoo_model'):
                    oext['odoo_model'] = stolen['odoo_model']
                other.external_ids = oext
                flag_modified(other, 'external_ids')
                db.session.add(other)
        db.session.commit()

    elif action == 'promote':
        uid = payload.get('user_id')
        user = User.query.get(uid) if uid else None
        if user and payload.get('previous_company_id') is not None:
            user.company_id = payload['previous_company_id']
            db.session.add(user)
            db.session.commit()

    elif action == 'merge':
        # No deshace el merge completo (calendarios); reactiva la ficha archivada.
        absorb_id = payload.get('absorb_id')
        absorb = User.query.get(absorb_id) if absorb_id else None
        if absorb and absorb.is_deleted:
            snap = payload.get('absorb_snapshot') or {}
            absorb.is_deleted = False
            absorb.active = True
            absorb.deactivation_reason = None
            absorb.deactivated_at = None
            absorb.deactivated_by_id = None
            ext = dict(absorb.external_ids or {})
            for k in (
                'merged_into_user_id',
                'merged_into_label',
                'merged_reason',
                'merged_at',
            ):
                ext.pop(k, None)
            absorb.external_ids = ext
            flag_modified(absorb, 'external_ids')
            if snap.get('dni'):
                clash = User.query.filter(
                    User.dni == snap['dni'], User.id != absorb.id
                ).first()
                if not clash:
                    absorb.dni = snap['dni']
            db.session.add(absorb)
            db.session.commit()

    else:
        raise ValueError(f'Acción no reversible: {action}')

    entry['undone'] = True
    entry['undone_at'] = utc_now().isoformat()
    entry['undone_by'] = getattr(actor, 'id', None)
    _save_log(entries)
    return entry


def list_companies_for_conciliation(limit: int = 500) -> list[dict]:
    from app.models import Company

    rows = (
        Company.query
        .filter(Company.active.is_(True))
        .order_by(Company.is_internal.desc(), Company.nombre.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            'id': c.id,
            'label': c.nombre,
            'is_internal': bool(c.is_internal),
        }
        for c in rows
    ]


def create_stub_user(
    *,
    name: str,
    lastname: str,
    company_id: int,
    dni: str | None = None,
    email: str | None = None,
    role: str | None = None,
    actor=None,
) -> dict:
    """Alta rápida de ficha local para poder vincularla a Odoo en el acto."""
    import secrets
    import time

    from werkzeug.security import generate_password_hash

    from app.models import ROLE_OPERARIO, Company
    from app.services.auth_login_service import default_auth_mode_for_role
    from app.services.plan_service import exigir_alta_empleado

    name = (name or '').strip()
    lastname = (lastname or '').strip()
    if not name or not lastname:
        raise ValueError('Nombre y apellidos son obligatorios')

    company = Company.query.get(int(company_id))
    if not company or not company.active:
        raise ValueError('Empresa no válida')

    role = (role or ROLE_OPERARIO).strip() or ROLE_OPERARIO
    exigir_alta_empleado(role=role, active=True)

    dni_clean = normalize_dni(dni) if dni else ''
    if not dni_clean:
        dni_clean = f'CONC-{int(time.time()) % 10_000_000}'
    if User.query.filter_by(dni=dni_clean).first():
        raise ValueError(f'El DNI {dni_clean} ya pertenece a otro usuario')

    email_clean = (email or '').strip().lower()
    if not email_clean:
        email_clean = f'conc_{dni_clean.lower()}@local.tuappsaas.com'
    if User.query.filter_by(email=email_clean).first():
        email_clean = f'conc_{secrets.token_hex(4)}@local.tuappsaas.com'

    user = User(
        name=name,
        lastname=lastname,
        dni=dni_clean[:20],
        email=email_clean,
        role=role,
        company_id=company.id,
        active=True,
        email_verified=True,
        is_deleted=False,
        auth_mode=default_auth_mode_for_role(role),
        password_hash=generate_password_hash(secrets.token_urlsafe(24)),
        external_ids={},
        categoria_profesional='Sin definir',
    )
    db.session.add(user)
    db.session.flush()

    entry = _append_log(
        'create',
        f'Alta rápida en conciliación: {_user_card(user)["label"]}',
        {
            'local_user_id': user.id,
            'company_id': company.id,
            'dni': user.dni,
        },
        actor=actor,
    )
    db.session.commit()
    return {
        'user': _user_card(user),
        'log_id': entry['id'],
    }


def get_conciliation_summary() -> dict:
    try:
        enrich_barcodes_from_odoo()
    except Exception:
        logger.exception('No se pudieron enriquecer códigos de asistencia')

    candidates = list_barcode_candidates()
    pending = [c for c in candidates if not c.get('maintained')]
    maintained = [c for c in candidates if c.get('maintained')]
    from app.models import Company
    internas = [
        {'id': c.id, 'label': c.nombre}
        for c in Company.query.filter_by(is_internal=True, active=True).order_by(Company.nombre).all()
    ]
    return {
        'candidates': pending,
        'candidates_maintained': maintained,
        'candidates_count': len(pending),
        'internal_companies': internas,
        'companies': list_companies_for_conciliation(),
        'plantilla_users': list_plantilla_users(),
        'log_entries': list_log_entries(),
    }
