# tests/unit/test_i18n.py
from app.services.i18n_service import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    marketing_path,
    normalize_locale,
    translate,
)


def test_supported_locales_include_core_four():
    assert DEFAULT_LOCALE == 'es'
    assert SUPPORTED_LOCALES[0] == 'es'
    for code in ('es', 'en', 'pt', 'fr'):
        assert code in SUPPORTED_LOCALES


def test_normalize_locale_accepts_bcp47():
    assert normalize_locale('en-GB') == 'en'
    assert normalize_locale('pt_BR') == 'pt'
    assert normalize_locale('de') is None


def test_translate_uses_catalog_not_passthrough():
    assert translate('Guardar', locale='es') == 'Guardar'
    assert translate('Guardar', locale='en') == 'Save'
    assert translate('Cancelar', locale='fr') == 'Annuler'
    assert translate('hero.headline', locale='en') != translate('hero.headline', locale='es')


def test_translate_interpolation():
    out = translate('Se han procesado {count} correctamente.', locale='es', count=3)
    assert '3' in out


def test_marketing_path_prefixes_non_default():
    assert marketing_path('/alta', 'es') == '/alta'
    assert marketing_path('/alta', 'en') == '/en/alta'
    assert marketing_path('/', 'en') == '/en/'
    assert marketing_path('/en/alta', 'fr') == '/fr/alta'


def test_no_html_rewriter_api():
    import app.services.i18n_service as mod
    assert not hasattr(mod, 'translate_html_document')


def test_english_marketing_url_has_hreflang(client):
    resp = client.get('/en/', headers={'Host': 'signaplan.com'})
    assert resp.status_code == 200
    assert resp.headers.get('Content-Language') == 'en'
    html = resp.get_data(as_text=True)
    assert 'hreflang="en"' in html
    assert 'hreflang="es"' in html
    assert 'hreflang="x-default"' in html
    assert 'lang="en"' in html
    assert 'seo.landing.title' not in html
    assert translate('seo.landing.title', locale='en') in html


def test_spanish_marketing_url_stays_unprefixed(client):
    resp = client.get('/', headers={'Host': 'signaplan.com'})
    assert resp.status_code == 200
    assert resp.headers.get('Content-Language') == 'es'
    html = resp.get_data(as_text=True)
    assert 'lang="es"' in html
    assert translate('seo.landing.title', locale='es') in html


def test_default_locale_prefix_redirects(client):
    resp = client.get('/es/alta', headers={'Host': 'signaplan.com'})
    assert resp.status_code == 301
    assert resp.headers['Location'].endswith('/alta')


def test_english_solutions_index_is_not_spanish(client):
    resp = client.get('/en/soluciones/', headers={'Host': 'signaplan.com'})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert translate('seo.soluciones.h1', locale='en') in html
    assert 'Organiza obra sin montar un ERP' not in html
    assert 'hreflang="en"' in html
    assert html.count('rel="canonical"') >= 1


def test_english_guides_index_uses_localized_title(client):
    resp = client.get('/en/recursos/', headers={'Host': 'signaplan.com'})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert translate('seo.recursos.title', locale='en') in html
    assert 'Guías SignaPlan — cuadrante' not in html


def test_legal_english_is_translated(client):
    resp = client.get('/en/legal/aviso-legal', headers={'Host': 'signaplan.com'})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert translate('legal.aviso.h1', locale='en') in html
    assert translate('legal.translation_notice', locale='en') in html
    assert '1. Titular del sitio' not in html


def test_extra_catalog_keys_override_msgid():
    assert translate('seo.soluciones.h1', locale='en') != 'seo.soluciones.h1'
    assert translate('Seleccionar Fecha de Baja', locale='en') == 'Choose end date'


def test_activity_logs_are_translated():
    from app.services.i18n_service import translate_log_action, translate_log_detail

    assert translate_log_action('Planificación Manual', 'en') == 'Manual planning'
    assert translate_log_action('Verificación de correo', 'en') == 'Email verification'

    assigned = translate_log_detail(
        "Asignado Pacodfsdfsdf Navarro hernandez → 'OFICINA — Oficina' (16/08/2026).",
        'en',
    )
    assert assigned.startswith('Assigned Pacodfsdfsdf Navarro hernandez')
    assert 'OFICINA — Oficina' in assigned
    assert 'Asignado' not in assigned

    email = translate_log_detail('Correo verificado tras alta. IP: 172.25.0.7', 'en')
    assert 'Email verified after signup' in email
    assert '172.25.0.7' in email
    assert 'Correo verificado' not in email

    clocked = translate_log_detail(
        'El operario fichó en OFICINA. Entrada: 08:00 / Salida: 17:00',
        'en',
    )
    assert 'clocked in' in clocked.lower()
    assert 'OFICINA' in clocked
    assert 'El operario' not in clocked


def test_sitemap_lists_hreflang_alternates(client):
    resp = client.get('/sitemap.xml', headers={'Host': 'signaplan.com'})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'xmlns:xhtml' in body
    assert 'hreflang="en"' in body
    assert 'https://signaplan.com/en/' in body
    assert 'https://signaplan.com/en/alta' in body
