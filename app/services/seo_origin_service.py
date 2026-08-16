# Origen público único para canónicas, sitemap y Open Graph.
#
# Search Console estaba partiendo el sitio entre signaplan.com y www.
# En producción las URLs indexables deben ser siempre https://signaplan.com/...
# En local seguimos el host de la petición para no romper previews.

from flask import current_app, has_app_context, has_request_context, request

from app.services.tenant_domain_service import normalize_host

_DEFAULT_PUBLIC_ORIGIN = 'https://signaplan.com'
_DEV_HOSTS = frozenset({'localhost', '127.0.0.1', 'web'})


def marketing_origin():
    """Origen absoluto sin barra final (https://signaplan.com)."""
    configured = ''
    if has_app_context():
        configured = (
            current_app.config.get('SIGNAPLAN_PUBLIC_ORIGIN') or ''
        ).strip().rstrip('/')

    if has_request_context():
        host = normalize_host(request.host)
        if host in _DEV_HOSTS or host.endswith('.localhost'):
            return (request.url_root or '').rstrip('/')

    return configured or _DEFAULT_PUBLIC_ORIGIN


def marketing_url(path='/'):
    """URL absoluta en el origen canónico."""
    if path and (path.startswith('http://') or path.startswith('https://')):
        return path
    raw = path or '/'
    if not raw.startswith('/'):
        raw = '/' + raw
    return marketing_origin() + raw
