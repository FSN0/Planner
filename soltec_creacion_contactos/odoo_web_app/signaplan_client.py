"""Cliente de autenticación contra SignaPlan (mismo email/contraseña)."""
import json
import os
import urllib.error
import urllib.request


def authenticate_signaplan(email, password):
    auth_url = (os.getenv('SIGNAPLAN_AUTH_URL') or '').strip()
    tenant = (os.getenv('SIGNAPLAN_TENANT') or os.getenv('SIGNAPLAN_TENANT_SLUG') or 'soltec').strip()
    shared_key = os.getenv('SSO_SECRET_KEY', '')
    tenant_host = (os.getenv('SIGNAPLAN_TENANT_HOST') or f'{tenant}.localhost').strip()

    if not auth_url:
        raise ValueError('SIGNAPLAN_AUTH_URL no configurada en el .env de la app de altas.')
    if not shared_key:
        raise ValueError('SSO_SECRET_KEY no configurada.')

    payload = json.dumps({
        'email': email.strip().lower(),
        'password': password,
        'tenant': tenant,
    }).encode('utf-8')

    headers = {
        'Content-Type': 'application/json',
        'X-Odoo-Alta-Key': shared_key,
    }
    # Ayuda si la petición pasa por Caddy (resolución de tenant por subdominio)
    if tenant_host:
        headers['Host'] = tenant_host

    req = urllib.request.Request(
        auth_url,
        data=payload,
        headers=headers,
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode('utf-8'))
            msg = body.get('error') or body.get('description') or body.get('message')
            if msg:
                return False, msg
        except Exception:
            pass
        if exc.code == 404:
            return False, (
                'SignaPlan no encontró el endpoint de login (404). '
                'Reinicia el contenedor web de SignaPlan y revisa SIGNAPLAN_AUTH_URL.'
            )
        return False, f'Error de SignaPlan ({exc.code})'
    except urllib.error.URLError as exc:
        return False, f'No se pudo conectar con SignaPlan: {exc.reason}'

    if not body.get('success'):
        return False, body.get('error') or 'Acceso denegado'

    return True, body.get('user') or {}
