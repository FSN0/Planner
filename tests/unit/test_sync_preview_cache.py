"""Tests para caché de previews Odoo con pendientes."""
from app.services.sync_preview_cache_service import (
    cache_from_diff,
    clear_cache,
    count_pending_actions,
    load_cache,
    pending_counts_all,
    save_cache,
)


def test_count_pending_from_preview_stats():
    preview = {'modulo': 'obras', 'stats': {'incidencias': 3}}
    assert count_pending_actions(preview) == 3


def test_save_and_load_cache(app, monkeypatch):
    stored = {}

    def fake_get(key, default=''):
        return stored.get(key, default)

    def fake_set(key, value):
        stored[key] = value

    monkeypatch.setattr(
        'app.services.sync_preview_cache_service.get_tenant_config',
        fake_get,
    )
    monkeypatch.setattr(
        'app.services.sync_preview_cache_service.set_tenant_config',
        fake_set,
    )

    preview = {'modulo': 'obras', 'stats': {'incidencias': 2}}
    diff = {'nuevas': [], 'actualizadas': [], 'incidencias': [{}, {}]}
    save_cache('obras', preview, diff, source='auto')

    cached = load_cache('obras')
    assert cached is not None
    assert cached['pending_count'] == 2
    assert cached['source'] == 'auto'
    assert cached['preview']['modulo'] == 'obras'

    counts = pending_counts_all()
    assert counts['obras'] == 2

    clear_cache('obras')
    assert load_cache('obras') is None


def test_save_clears_when_no_pending(app, monkeypatch):
    stored = {'sync_preview_cache_obras': '{"preview": {"modulo": "obras"}}'}

    def fake_get(key, default=''):
        return stored.get(key, default)

    def fake_set(key, value):
        if value:
            stored[key] = value
        else:
            stored.pop(key, None)

    monkeypatch.setattr(
        'app.services.sync_preview_cache_service.get_tenant_config',
        fake_get,
    )
    monkeypatch.setattr(
        'app.services.sync_preview_cache_service.set_tenant_config',
        fake_set,
    )

    preview = {'modulo': 'obras', 'stats': {'incidencias': 0}}
    save_cache('obras', preview, {}, source='manual')
    assert 'sync_preview_cache_obras' not in stored


def test_cache_from_diff_uses_analyzer(app, monkeypatch):
    stored = {}

    monkeypatch.setattr(
        'app.services.sync_preview_cache_service.get_tenant_config',
        lambda key, default='': stored.get(key, default),
    )
    monkeypatch.setattr(
        'app.services.sync_preview_cache_service.set_tenant_config',
        lambda key, value: stored.__setitem__(key, value),
    )

    diff = {
        'nuevas': [{'odoo_id': 1, 'codigo': 'X', 'nombre': 'Obra', 'warn_jefe': True, 'jefe_odoo_raw': 'J'}],
        'actualizadas': [],
        'finalizadas': [],
        'sin_cambios': [],
    }
    pending = cache_from_diff('obras', diff, source='auto')
    assert pending >= 1
    assert load_cache('obras') is not None
