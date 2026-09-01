"""Caché de previews Odoo con pendientes de acción (sin reconsultar Odoo)."""
from __future__ import annotations

import json
from datetime import datetime

from app.services.config_service import get_tenant_config, set_tenant_config
from app.utils.timezone_utils import utc_now

_CACHE_PREFIX = 'sync_preview_cache_'

_ANALYZERS = {
    'obras': ('analyze_obras_preview', 'app.services.sync_preview_service'),
    'empleados': ('analyze_empleados_preview', 'app.services.sync_preview_service'),
    'subcontratas': ('analyze_subcontratas_preview', 'app.services.sync_preview_service'),
}


def _cache_key(modulo: str) -> str:
    return f'{_CACHE_PREFIX}{modulo}'


def count_pending_actions(preview: dict) -> int:
    if not preview:
        return 0
    stats = preview.get('stats') or {}
    mod = preview.get('modulo')
    if mod == 'obras':
        return int(stats.get('incidencias') or 0)
    if mod == 'empleados':
        return int(stats.get('incidencias') or 0)
    if mod == 'subcontratas':
        return int(stats.get('incidencias') or 0)
    return 0


def save_cache(modulo: str, preview: dict, diff: dict, *, source: str = 'manual') -> None:
    pending = count_pending_actions(preview)
    if pending <= 0:
        clear_cache(modulo)
        return
    payload = {
        'saved_at': utc_now().isoformat(),
        'source': source,
        'pending_count': pending,
        'preview': preview,
        'diff': diff,
    }
    set_tenant_config(_cache_key(modulo), json.dumps(payload, default=str))


def clear_cache(modulo: str) -> None:
    set_tenant_config(_cache_key(modulo), '')


def load_cache(modulo: str) -> dict | None:
    raw = get_tenant_config(_cache_key(modulo), default='')
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get('preview'):
        return None
    return data


def cache_from_diff(modulo: str, diff: dict, *, source: str = 'manual') -> int:
    spec = _ANALYZERS.get(modulo)
    if not spec or not diff:
        return 0
    fn_name, module_path = spec
    import importlib
    mod = importlib.import_module(module_path)
    analyzer = getattr(mod, fn_name)
    preview = analyzer(diff)
    pending = count_pending_actions(preview)
    if pending <= 0:
        clear_cache(modulo)
        return 0
    save_cache(modulo, preview, diff, source=source)
    return pending


def pending_counts_all() -> dict[str, int]:
    out = {}
    for modulo in _ANALYZERS:
        cached = load_cache(modulo)
        out[modulo] = int((cached or {}).get('pending_count') or 0)
    return out


def format_saved_at(iso_str: str | None) -> str:
    if not iso_str:
        return '—'
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.strftime('%d/%m/%Y %H:%M')
    except ValueError:
        return iso_str
