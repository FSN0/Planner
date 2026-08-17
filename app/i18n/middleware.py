# WSGI: /en/alta → PATH_INFO /alta + locale en, only on the marketing host.
# Flask routing already happened if we used before_request; this runs before it.

from __future__ import annotations


_MARKETING_HOSTS = frozenset(
    {'signaplan.com', 'www.signaplan.com', 'localhost', '127.0.0.1', 'web'}
)


def _normalize_host(host: str) -> str:
    return (host or '').split(':')[0].lower().strip().rstrip('.')


class MarketingLocaleMiddleware:
    """Strip /{locale} on the public site so Google gets one URL per language."""

    def __init__(self, app, locales, default='es'):
        self.app = app
        self.default = default
        self.prefix_locales = tuple(code for code in locales if code != default)

    def __call__(self, environ, start_response):
        host = _normalize_host(environ.get('HTTP_HOST', ''))
        if host not in _MARKETING_HOSTS and not host.endswith('.localhost'):
            return self.app(environ, start_response)

        path = environ.get('PATH_INFO') or '/'
        default_prefix = '/' + self.default
        if path == default_prefix or path.startswith(default_prefix + '/'):
            rest = path[len(default_prefix):] or '/'
            qs = environ.get('QUERY_STRING')
            loc = rest + (('?' + qs) if qs else '')
            start_response('301 Moved Permanently', [('Location', loc), ('Content-Length', '0')])
            return [b'']

        for code in self.prefix_locales:
            prefix = '/' + code
            if path == prefix or path.startswith(prefix + '/'):
                rest = path[len(prefix):] or '/'
                environ['PATH_INFO'] = rest
                environ['HTTP_X_SIGNAPLAN_LOCALE'] = code
                break
        return self.app(environ, start_response)
