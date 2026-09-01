# app/utils/nav_back.py
#
# Vuelta contextual: ?back=/ruta#pestana o Referer de confianza.

from urllib.parse import quote, unquote, urlparse

from flask import redirect, request, url_for

_ALLOWED_PREFIXES = ('/admin/', '/sync/', '/jefe/', '/fichaje/', '/notas/')
_BLOCKED_PREFIXES = ('/auth/logout',)


def _path_only(url: str) -> str:
    return (url or '').split('?')[0].split('#')[0]


def is_safe_back_url(url: str) -> bool:
    if not url or not url.startswith('/') or url.startswith('//'):
        return False
    path = _path_only(url)
    if not path or path == '/':
        return False
    if any(path.startswith(p) for p in _BLOCKED_PREFIXES):
        return False
    return any(path.startswith(p) for p in _ALLOWED_PREFIXES)


def _back_from_referrer() -> str:
    ref = (request.referrer or '').strip()
    if not ref:
        return ''
    parsed = urlparse(ref)
    if parsed.netloc and parsed.netloc != request.host:
        return ''
    back = parsed.path or ''
    if parsed.query:
        back += '?' + parsed.query
    if parsed.fragment:
        back += '#' + parsed.fragment
    return back if is_safe_back_url(back) else ''


def resolve_back_url(fallback_endpoint, **fallback_kwargs) -> str:
    """URL segura para el botón atrás (query back, referer o fallback)."""
    raw = (request.args.get('back') or request.values.get('back') or '').strip()
    if raw:
        decoded = unquote(raw)
        if is_safe_back_url(decoded):
            return decoded
    ref_back = _back_from_referrer()
    if ref_back:
        return ref_back
    if fallback_endpoint:
        return url_for(fallback_endpoint, **fallback_kwargs)
    return url_for('main.dashboard')


def redirect_back_or(fallback_endpoint, **fallback_kwargs):
    return redirect(resolve_back_url(fallback_endpoint, **fallback_kwargs))


def url_with_back(endpoint, back=None, **kwargs) -> str:
    """Enlace a una ficha/formulario conservando el origen en ?back=."""
    url = url_for(endpoint, **kwargs)
    if back is None:
        back = request.full_path or request.path or ''
        if back.endswith('?'):
            back = back[:-1]
    back = (back or '').strip()
    if not back or not is_safe_back_url(back):
        return url
    sep = '&' if '?' in url else '?'
    return f'{url}{sep}back={quote(back, safe="")}'
