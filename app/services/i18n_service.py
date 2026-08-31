# app/services/i18n_service.py
#
# Un solo motor: catálogos JSON por idioma + lookup explícito (_ / translate / SP_T).
# Añadir un idioma = app/i18n/locales/{code}.json + entrada en registry.json.
# Claves nuevas (SEO, legal, JS) pueden ir en app/i18n/extra/{code}.json; se fusionan al cargar.
# El español de plantilla es el msgid (estilo gettext). Las claves dotted son marketing/SEO.

from __future__ import annotations

import json
import re
from pathlib import Path

from flask import g, has_request_context, request, session

_APP_DIR = Path(__file__).resolve().parents[1]
_I18N_DIR = _APP_DIR / 'i18n'
_LOCALES_DIR = _I18N_DIR / 'locales'
_REGISTRY_PATH = _I18N_DIR / 'registry.json'

_REGISTRY = {}
_CATALOG = {}
SUPPORTED_LOCALES = ('es',)
DEFAULT_LOCALE = 'es'
LOCALE_LABELS = {'es': 'Español'}
_COUNTRY_LOCALE = {}
_LOCALE_META = {}


def _load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise TypeError(f'{path} must be a JSON object')
    return data


def _reload_catalogs() -> None:
    global _REGISTRY, _CATALOG, SUPPORTED_LOCALES, DEFAULT_LOCALE
    global LOCALE_LABELS, _COUNTRY_LOCALE, _LOCALE_META

    _REGISTRY = _load_json(_REGISTRY_PATH)
    DEFAULT_LOCALE = str(_REGISTRY.get('default') or 'es')
    meta = _REGISTRY.get('locales') or {}
    _LOCALE_META = {str(k): dict(v) for k, v in meta.items()}
    _COUNTRY_LOCALE = {
        str(k).upper(): str(v)
        for k, v in (_REGISTRY.get('country_locale') or {}).items()
    }

    files = {
        p.stem: {str(k): str(v) for k, v in _load_json(p).items()}
        for p in sorted(_LOCALES_DIR.glob('*.json'))
        if p.stem
    }
    # es siempre existe como idioma fuente aunque el JSON solo tenga claves dotted.
    codes = [DEFAULT_LOCALE]
    for code in _LOCALE_META:
        if code == DEFAULT_LOCALE:
            continue
        if code in files:
            codes.append(code)
    SUPPORTED_LOCALES = tuple(codes)
    LOCALE_LABELS = {
        code: str((_LOCALE_META.get(code) or {}).get('label') or code)
        for code in SUPPORTED_LOCALES
    }
    _CATALOG.clear()
    for code in SUPPORTED_LOCALES:
        _CATALOG[code] = files.get(code) or {}

    extra_dir = _I18N_DIR / 'extra'
    if extra_dir.is_dir():
        for p in extra_dir.glob('*.json'):
            extra = {str(k): str(v) for k, v in _load_json(p).items()}
            _CATALOG.setdefault(p.stem, {}).update(extra)


_reload_catalogs()


class _SafeMap(dict):
    def __missing__(self, key):
        return '{' + str(key) + '}'


def supported_locales():
    return SUPPORTED_LOCALES


def locale_meta(code=None):
    loc = normalize_locale(code) or get_locale()
    return dict(_LOCALE_META.get(loc) or _LOCALE_META.get(DEFAULT_LOCALE) or {})


def normalize_locale(value):
    if not value:
        return None
    code = str(value).strip().lower().replace('_', '-')
    primary = code.split('-', 1)[0]
    if primary in SUPPORTED_LOCALES:
        return primary
    return None


def locale_from_accept_language(header):
    if not header:
        return None
    for part in header.split(','):
        tag = part.split(';', 1)[0].strip()
        loc = normalize_locale(tag)
        if loc:
            return loc
    return None


def locale_from_country(country_code):
    if not country_code:
        return None
    mapped = _COUNTRY_LOCALE.get(str(country_code).strip().upper())
    return normalize_locale(mapped)


def _marketing_url_locale():
    if not has_request_context():
        return None
    raw = request.environ.get('HTTP_X_SIGNAPLAN_LOCALE')
    return normalize_locale(raw)


def detect_request_locale(user=None):
    """
    Marketing: el idioma lo fija la URL (/en/..., /fr/...). Así Google indexa
    una URL por lengua y no una cookie. Cookie/sesión solo recuerdan la elección
    para el panel (subdominio de cliente).

    Panel: ?lang → cookie → sesión → usuario → país → Accept-Language → es.
    """
    marketing = False
    if has_request_context():
        try:
            from app.services.tenant_domain_service import is_marketing_host, normalize_host
            marketing = is_marketing_host(normalize_host(request.host))
        except Exception:
            marketing = False

        url_loc = _marketing_url_locale()
        if url_loc:
            return url_loc

        q = normalize_locale(request.args.get('lang'))
        if q and not marketing:
            return q

        cookie = normalize_locale(request.cookies.get('signaplan_lang'))
        if cookie and not marketing:
            return cookie
        sess = normalize_locale(session.get('locale'))
        if sess and not marketing:
            return sess

        if marketing:
            # URL sin prefijo = español canónico (x-default). No mutar por
            # Accept-Language: Googlebot pediría EN sobre la URL en ES.
            return DEFAULT_LOCALE

    if user is not None and getattr(user, 'is_authenticated', False):
        pref = normalize_locale(getattr(user, 'locale', None))
        if pref:
            return pref

    if has_request_context():
        country = (
            request.headers.get('CF-IPCountry')
            or request.headers.get('X-Appengine-Country')
            or request.headers.get('CloudFront-Viewer-Country')
        )
        from_country = locale_from_country(country)
        if from_country:
            return from_country
        from_accept = locale_from_accept_language(request.headers.get('Accept-Language'))
        if from_accept:
            return from_accept

    return DEFAULT_LOCALE


def get_locale():
    if has_request_context() and getattr(g, 'locale', None):
        return g.locale
    return DEFAULT_LOCALE


def translate(key, locale=None, **kwargs):
    """Traduce msgid (texto ES o clave dotted). Fallback: el propio msgid."""
    if key is None:
        return ''
    key = str(key)
    loc = normalize_locale(locale) or get_locale()
    bag = _CATALOG.get(loc) or {}
    text = bag.get(key)
    if text is None and loc != DEFAULT_LOCALE:
        text = (_CATALOG.get(DEFAULT_LOCALE) or {}).get(key)
    if text is None:
        text = key
    if kwargs:
        try:
            return text.format_map(_SafeMap(kwargs))
        except Exception:
            return text
    return text


def role_label(role):
    key = f'role.{role}' if role else ''
    labeled = translate(key)
    if labeled != key:
        return labeled
    return (role or '').replace('_', ' ').title()


def _(key, **kwargs):
    return translate(key, **kwargs)


def frontend_catalog(locale=None):
    """Mapa msgid → texto del idioma activo, para window.SP_T."""
    loc = normalize_locale(locale) or get_locale()
    bag = dict(_CATALOG.get(DEFAULT_LOCALE) or {})
    if loc != DEFAULT_LOCALE:
        bag.update(_CATALOG.get(loc) or {})
    return bag


def month_name(month, locale=None):
    try:
        m = int(month)
    except (TypeError, ValueError):
        return ''
    months = (
        '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
    )
    if m < 1 or m > 12:
        return ''
    return translate(months[m], locale)


def weekday_short(dt, locale=None):
    names = ('DOM', 'LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB')
    idx = (dt.weekday() + 1) % 7
    return translate(names[idx], locale)


def date_format(locale=None):
    return locale_meta(locale).get('date') or '%d/%m/%Y'


def datetime_format(locale=None):
    return locale_meta(locale).get('datetime') or '%d/%m/%Y %H:%M'


def marketing_path(path, locale=None):
    """Prefija /en, /pt, /fr a una ruta de marketing. ES no lleva prefijo."""
    loc = normalize_locale(locale) or get_locale()
    raw = path or '/'
    if raw.startswith('http://') or raw.startswith('https://'):
        return raw
    if not raw.startswith('/'):
        raw = '/' + raw
    # Evitar doble prefijo si ya viene localizado.
    for code in SUPPORTED_LOCALES:
        if code == DEFAULT_LOCALE:
            continue
        if raw == f'/{code}' or raw.startswith(f'/{code}/'):
            raw = raw[len(code) + 1:] or '/'
            break
    if loc == DEFAULT_LOCALE:
        return raw
    if raw == '/':
        return f'/{loc}/'
    return f'/{loc}{raw}'


def locale_href(target_locale, path=None):
    """URL de la misma página de marketing en otro idioma."""
    if path is None and has_request_context():
        path = request.path
    return marketing_path(path or '/', target_locale)


def hreflang_links(path=None):
    """Pares (hreflang, path) incluyendo x-default."""
    if path is None and has_request_context():
        path = request.path
    path = path or '/'
    links = []
    for code in SUPPORTED_LOCALES:
        links.append((code, marketing_path(path, code)))
    links.append(('x-default', marketing_path(path, DEFAULT_LOCALE)))
    return links


def _cookie_domain():
    if not has_request_context():
        return None
    try:
        from app.services.tenant_domain_service import normalize_host
        host = normalize_host(request.host)
    except Exception:
        host = (request.host or '').split(':')[0].lower()
    if host == 'signaplan.com' or host.endswith('.signaplan.com'):
        return '.signaplan.com'
    return None


_LOG_ASSIGN_RANGE = re.compile(
    r"^(Asignado|Desasignado) (.+) → '(.+)' "
    r"\((\d{2}/\d{2}/\d{4}) → (\d{2}/\d{2}/\d{4}), (\d+) días\)\.(?: (.+))?$"
)
_LOG_ASSIGN_ONE = re.compile(
    r"^(Asignado|Desasignado) (.+) → '(.+)' \((\d{2}/\d{2}/\d{4})\)\.(?: (.+))?$"
)
_LOG_VEH_RANGE = re.compile(
    r"^Vehículo (.+) → (.+) \((\d{2}/\d{2}/\d{4}) → (\d{2}/\d{2}/\d{4}), (\d+) días\)\. "
    r"(Asignado|Desasignado)\.(?: (.+))?$"
)
_LOG_VEH_ONE = re.compile(
    r"^Vehículo (.+) → (.+) \((\d{2}/\d{2}/\d{4})\)\. "
    r"(Asignado|Desasignado)\.(?: (.+))?$"
)
_LOG_EMAIL_IP = re.compile(r'^Correo verificado tras alta\. IP: (.+)$')
_LOG_OVERWRITE_N = re.compile(r'^Incluye sobreescritura de (\d+) día\(s\)\.$')
_LOG_FICHAJE_ACTION = re.compile(r'^Fichaje físico \[(.+)\]$')
_LOG_RESOLUCION_ACTION = re.compile(r'^Resolución de Fichaje: (.+)$')
_LOG_CAMBIO_MASIVO = re.compile(r'^Cambio masivo a (.+)$')
_LOG_FICHO = re.compile(
    r'^El operario fichó en (.+?)\. Entrada: (.+) / Salida: (.+?)(?: Notas: (.+))?$'
)
_LOG_FICHO_CONFLICTO = re.compile(
    r'^El operario fichó en (.+?) \(tenía planificado en (.+?)\)\. '
    r'Entrada: (.+) / Salida: (.+?)(?: Notas: (.+))?$'
)
_LOG_FICHO_PARACAIDISTA = re.compile(
    r'^El operario fichó en (.+?) sin planificación en esa obra\. '
    r'Entrada: (.+) / Salida: (.+?)(?: Notas: (.+))?$'
)
_LOG_IGNORA_PLAN = re.compile(
    r"^Se ignora el fichaje en '(.+)' \(estaba planificado en '(.+)'\)\.$"
)
_LOG_IGNORA_FICHAJE = re.compile(r"^Se ignora el fichaje en '(.+)'\.$")
_LOG_IGNORA_INC = re.compile(r"^Se ignora la incidencia en '(.+)'\.$")
_LOG_CUADRANTE = re.compile(r"^Cuadrante actualizado: de '(.+)' a '(.+)'\.$")
_LOG_REASIGNADO = re.compile(r"^Reasignado a '(.+)'\.$")
_LOG_ACEPTA_SIN = re.compile(r"^Se acepta el fichaje sin planificar en '(.+)'\.$")
_LOG_ACEPTA_DESV = re.compile(
    r"^Se acepta el fichaje con desviación de plan en '(.+)'\.$"
)
_LOG_ANADIDA_ASIG = re.compile(
    r"^Añadida asignación en '(.+)' \(pluriempleo\)\.$"
)
_LOG_ELIMINA_PLAN = re.compile(
    r"^Se elimina la planificación en '(.+)' \(el operario no fichó en esa obra\)\.$"
)
_LOG_AUSENCIA_CONF = re.compile(r"^Ausencia confirmada: no acudió a '(.+)'\.$")
_FICHAJE_APP_SUFFIX = ' (Fichaje en App)'


def translate_log_action(action, locale=None):
    """Traduce la acción de un SystemLog (etiqueta estable o plantilla)."""
    if not action:
        return ''
    m = _LOG_FICHAJE_ACTION.match(action)
    if m:
        return translate(
            'Fichaje físico [{estado}]', locale, estado=translate(m.group(1), locale)
        )
    m = _LOG_RESOLUCION_ACTION.match(action)
    if m:
        return translate(
            'Resolución de Fichaje: {accion}', locale, accion=translate(m.group(1), locale)
        )
    m = _LOG_CAMBIO_MASIVO.match(action)
    if m:
        return translate(
            'Cambio masivo a {estado}', locale, estado=translate(m.group(1), locale)
        )
    return translate(action, locale)


def translate_log_detail(detail, locale=None):
    """Traduce el detalle de un SystemLog. Los nombres propios se conservan."""
    if not detail:
        return ''
    from app.services.log_coverage import strip_coverage
    detail = strip_coverage(detail)
    if not detail:
        return ''
    exact = translate(detail, locale)
    if exact != detail:
        return exact

    m = _LOG_ASSIGN_RANGE.match(detail)
    if m:
        verbo, name, label, fi, ff, ndias, extra = m.groups()
        text = translate(
            "{verbo} {name} → '{label}' ({fi} → {ff}, {n} días).",
            locale,
            verbo=translate(verbo, locale),
            name=name,
            label=label,
            fi=fi,
            ff=ff,
            n=ndias,
        )
        if extra:
            text = f'{text} {translate_log_detail(extra, locale)}'
        return text

    m = _LOG_ASSIGN_ONE.match(detail)
    if m:
        verbo, name, label, date, extra = m.groups()
        text = translate(
            "{verbo} {name} → '{label}' ({date}).",
            locale,
            verbo=translate(verbo, locale),
            name=name,
            label=label,
            date=date,
        )
        if extra:
            text = f'{text} {translate_log_detail(extra, locale)}'
        return text

    m = _LOG_VEH_RANGE.match(detail)
    if m:
        label, name, fi, ff, ndias, verbo, extra = m.groups()
        text = translate(
            'Vehículo {label} → {name} ({fi} → {ff}, {n} días). {verbo}.',
            locale,
            label=label,
            name=name,
            fi=fi,
            ff=ff,
            n=ndias,
            verbo=translate(verbo, locale),
        )
        if extra:
            text = f'{text} {translate_log_detail(extra, locale)}'
        return text

    m = _LOG_VEH_ONE.match(detail)
    if m:
        label, name, date, verbo, extra = m.groups()
        text = translate(
            'Vehículo {label} → {name} ({date}). {verbo}.',
            locale,
            label=label,
            name=name,
            date=date,
            verbo=translate(verbo, locale),
        )
        if extra:
            text = f'{text} {translate_log_detail(extra, locale)}'
        return text

    m = _LOG_EMAIL_IP.match(detail)
    if m:
        ip = m.group(1)
        ip_disp = translate(ip, locale) if ip == 'Desconocida' else ip
        return translate('Correo verificado tras alta. IP: {ip}', locale, ip=ip_disp)

    m = _LOG_OVERWRITE_N.match(detail)
    if m:
        return translate(
            'Incluye sobreescritura de {n} día(s).', locale, n=m.group(1)
        )

    m = _LOG_FICHO_CONFLICTO.match(detail)
    if m:
        label, plan, entrada, salida, notas = m.groups()
        text = translate(
            'El operario fichó en {label} (tenía planificado en {plan}). '
            'Entrada: {entrada} / Salida: {salida}',
            locale,
            label=label,
            plan=plan,
            entrada=entrada,
            salida=salida,
        )
        if notas:
            text = f"{text} {translate('Notas: {note}', locale, note=notas)}"
        return text

    m = _LOG_FICHO_PARACAIDISTA.match(detail)
    if m:
        label, entrada, salida, notas = m.groups()
        text = translate(
            'El operario fichó en {label} sin planificación en esa obra. '
            'Entrada: {entrada} / Salida: {salida}',
            locale,
            label=label,
            entrada=entrada,
            salida=salida,
        )
        if notas:
            text = f"{text} {translate('Notas: {note}', locale, note=notas)}"
        return text

    m = _LOG_FICHO.match(detail)
    if m:
        label, entrada, salida, notas = m.groups()
        text = translate(
            'El operario fichó en {label}. Entrada: {entrada} / Salida: {salida}',
            locale,
            label=label,
            entrada=entrada,
            salida=salida,
        )
        if notas:
            text = f"{text} {translate('Notas: {note}', locale, note=notas)}"
        return text

    m = _LOG_IGNORA_PLAN.match(detail)
    if m:
        return translate(
            "Se ignora el fichaje en '{real}' (estaba planificado en '{plan}').",
            locale,
            real=m.group(1),
            plan=m.group(2),
        )
    m = _LOG_IGNORA_FICHAJE.match(detail)
    if m:
        return translate(
            "Se ignora el fichaje en '{label}'.", locale, label=m.group(1)
        )
    m = _LOG_IGNORA_INC.match(detail)
    if m:
        return translate(
            "Se ignora la incidencia en '{label}'.", locale, label=m.group(1)
        )
    m = _LOG_CUADRANTE.match(detail)
    if m:
        return translate(
            "Cuadrante actualizado: de '{origen}' a '{destino}'.",
            locale,
            origen=m.group(1),
            destino=m.group(2),
        )
    m = _LOG_REASIGNADO.match(detail)
    if m:
        return translate("Reasignado a '{label}'.", locale, label=m.group(1))
    m = _LOG_ACEPTA_SIN.match(detail)
    if m:
        return translate(
            "Se acepta el fichaje sin planificar en '{label}'.",
            locale,
            label=m.group(1),
        )
    m = _LOG_ACEPTA_DESV.match(detail)
    if m:
        return translate(
            "Se acepta el fichaje con desviación de plan en '{label}'.",
            locale,
            label=m.group(1),
        )
    m = _LOG_ANADIDA_ASIG.match(detail)
    if m:
        return translate(
            "Añadida asignación en '{label}' (pluriempleo).",
            locale,
            label=m.group(1),
        )
    m = _LOG_ELIMINA_PLAN.match(detail)
    if m:
        return translate(
            "Se elimina la planificación en '{label}' (el operario no fichó en esa obra).",
            locale,
            label=m.group(1),
        )
    m = _LOG_AUSENCIA_CONF.match(detail)
    if m:
        return translate(
            "Ausencia confirmada: no acudió a '{label}'.",
            locale,
            label=m.group(1),
        )

    if ' | ' in detail and detail.startswith('Obra:'):
        chunks = []
        for part in detail.split(' | '):
            if ': ' in part:
                key, val = part.split(': ', 1)
                chunks.append(f'{translate(key, locale)}: {val}')
            else:
                chunks.append(part)
        return ' | '.join(chunks)

    return detail


def translate_log_actor(autor, locale=None):
    """Traduce actores de sistema; conserva nombres de persona."""
    if not autor or autor == '-':
        return autor or ''
    if autor.endswith(_FICHAJE_APP_SUFFIX):
        name = autor[: -len(_FICHAJE_APP_SUFFIX)]
        return f"{name} ({translate('Fichaje en App', locale)})"
    return translate(autor, locale)


def set_locale_cookie(response, locale):
    loc = normalize_locale(locale) or DEFAULT_LOCALE
    kwargs = dict(
        max_age=365 * 24 * 3600,
        samesite='Lax',
        secure=has_request_context() and request.is_secure,
        path='/',
    )
    domain = _cookie_domain()
    if domain:
        kwargs['domain'] = domain
    response.set_cookie('signaplan_lang', loc, **kwargs)
    return response


def locale_og(code=None):
    meta = _LOCALE_META.get(normalize_locale(code) or get_locale()) or {}
    return str(meta.get('og') or 'es_ES')


def install_flask_flash_i18n():
    """Traduce flash() sin tocar cada ruta. Si el mensaje ya está traducido, se deja igual."""
    import flask

    if getattr(flask.flash, '_signaplan_i18n', False):
        return
    original = flask.flash

    def flash(message, *args, **kwargs):
        if isinstance(message, str):
            message = translate(message)
        return original(message, *args, **kwargs)

    flash._signaplan_i18n = True
    flask.flash = flash
