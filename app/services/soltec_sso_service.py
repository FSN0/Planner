import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from flask import g, has_request_context

from app.services.config_service import get_tenant_config


SSO_ALG = 'HS256'
SSO_AUD = 'planner'
SSO_TENANT = 'soltec'
PORTAL_ISS = 'planner'
PORTAL_AUD = 'soltec_portal'
PORTAL_DEFAULT_URL = 'https://portal-soltecgrupo.vercel.app'
TOKEN_TTL_SECONDS = 60
CLOCK_SKEW_SECONDS = 60
_USED_JTIS = {}


class SoltecSsoError(Exception):
    pass


def _b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _b64url_decode(raw):
    raw = (raw or '').encode('ascii')
    padding = b'=' * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _cleanup_used_jtis(now_ts):
    expired = [jti for jti, exp in _USED_JTIS.items() if exp < now_ts]
    for jti in expired:
        _USED_JTIS.pop(jti, None)


def soltec_sso_enabled():
    return (get_tenant_config('soltec_sso_enabled', default='false') or '').strip().lower() == 'true'


def _shared_secret():
    secret = get_tenant_config(
        'soltec_sso_shared_secret',
        desencriptar=True,
        default=os.environ.get('SOLTEC_SSO_SHARED_SECRET', ''),
    )
    return (secret or '').strip()


def _expected_issuer():
    issuer = get_tenant_config(
        'soltec_sso_issuer',
        default=os.environ.get('SOLTEC_SSO_ISSUER', 'soltec_satellite'),
    )
    return (issuer or 'soltec_satellite').strip()


def _portal_base_url():
    url = get_tenant_config(
        'soltec_sso_portal_url',
        default=os.environ.get('SOLTEC_SSO_PORTAL_URL', PORTAL_DEFAULT_URL),
    )
    return (url or PORTAL_DEFAULT_URL).strip().rstrip('/')


def is_soltec_tenant():
    """SSO Portal es exclusivo del tenant Soltec."""
    if not has_request_context():
        return False
    tenant = getattr(g, 'current_tenant', None)
    if not tenant:
        return False
    sub = (getattr(tenant, 'subdominio', None) or '').strip().lower()
    return sub == SSO_TENANT


def soltec_portal_sso_available():
    """Botón Portal: solo Soltec + SSO ON + clave + módulo Odoo."""
    if not is_soltec_tenant():
        return False
    if not soltec_sso_enabled():
        return False
    if not _shared_secret():
        return False
    modulos = getattr(getattr(g, 'current_tenant', None), 'modulos_activos', None) or {}
    return bool(modulos.get('odoo'))


def _encode_jwt(payload: dict, secret: str) -> str:
    header = {'alg': SSO_ALG, 'typ': 'JWT'}
    header_b64 = _b64url_encode(
        json.dumps(header, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    )
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    )
    signing_input = f'{header_b64}.{payload_b64}'.encode('ascii')
    signature = hmac.new(
        secret.encode('utf-8'),
        signing_input,
        hashlib.sha256,
    ).digest()
    return f'{header_b64}.{payload_b64}.{_b64url_encode(signature)}'


def mint_portal_sso_token(email: str) -> str:
    """JWT saliente Planner → Portal (mismo secreto que el flujo entrante)."""
    if not soltec_portal_sso_available():
        raise SoltecSsoError('SSO Portal Soltec no disponible.')
    secret = _shared_secret()
    email_norm = (email or '').strip().lower()
    if not email_norm:
        raise SoltecSsoError('Usuario sin email para SSO Portal.')
    now_ts = int(datetime.now(timezone.utc).timestamp())
    payload = {
        'iss': PORTAL_ISS,
        'aud': PORTAL_AUD,
        'tenant': SSO_TENANT,
        'email': email_norm,
        'jti': str(uuid.uuid4()),
        'iat': now_ts,
        'nbf': now_ts,
        'exp': now_ts + TOKEN_TTL_SECONDS,
    }
    return _encode_jwt(payload, secret)


def build_portal_sso_redirect_url(email: str) -> str:
    token = mint_portal_sso_token(email)
    return f'{_portal_base_url()}/auth/sso?t={quote(token, safe="")}'


def verify_soltec_sso_token(token):
    token = (token or '').strip().strip('"').replace(' ', '+')
    if not soltec_sso_enabled():
        raise SoltecSsoError('SSO Soltec desactivado.')
    secret = _shared_secret()
    if not secret:
        raise SoltecSsoError('Falta la clave compartida SSO.')
    if not token:
        raise SoltecSsoError('Falta el token SSO (parámetro t).')
    parts = token.split('.')
    if len(parts) != 3:
        raise SoltecSsoError('Token SSO mal formado.')

    header_b64, payload_b64, signature_b64 = parts
    signing_input = f'{header_b64}.{payload_b64}'.encode('ascii')
    expected_sig = hmac.new(
        secret.encode('utf-8'),
        signing_input,
        hashlib.sha256,
    ).digest()
    got_sig = signature_b64.rstrip('=')
    try:
        sig_ok = hmac.compare_digest(_b64url_encode(expected_sig), got_sig)
    except (TypeError, ValueError):
        sig_ok = False
    if not sig_ok:
        raise SoltecSsoError('Firma SSO inválida.')

    try:
        header = json.loads(_b64url_decode(header_b64).decode('utf-8'))
        payload = json.loads(_b64url_decode(payload_b64).decode('utf-8'))
    except Exception as exc:
        raise SoltecSsoError('Token SSO ilegible.') from exc

    if header.get('alg') != SSO_ALG:
        raise SoltecSsoError('Algoritmo SSO no soportado.')

    now_ts = int(datetime.now(timezone.utc).timestamp())
    exp = int(payload.get('exp') or 0)
    if not exp or exp < now_ts - CLOCK_SKEW_SECONDS:
        raise SoltecSsoError('Token SSO caducado.')

    nbf = int(payload.get('nbf') or 0)
    if nbf and nbf > now_ts + CLOCK_SKEW_SECONDS:
        raise SoltecSsoError('Token SSO aún no válido.')

    if payload.get('aud') != SSO_AUD:
        raise SoltecSsoError('Audience SSO inválida.')
    if payload.get('tenant') != SSO_TENANT:
        raise SoltecSsoError('Tenant SSO inválido.')
    if payload.get('iss') != _expected_issuer():
        raise SoltecSsoError('Issuer SSO inválido.')

    email = (payload.get('email') or '').strip().lower()
    if not email:
        raise SoltecSsoError('Token SSO sin email.')

    jti = (payload.get('jti') or '').strip()
    if not jti:
        raise SoltecSsoError('Token SSO sin jti.')
    _cleanup_used_jtis(now_ts)
    if jti in _USED_JTIS:
        raise SoltecSsoError('Token SSO ya usado.')
    _USED_JTIS[jti] = exp + int(timedelta(minutes=2).total_seconds())

    next_path = payload.get('next') or '/'
    if not isinstance(next_path, str) or not next_path.startswith('/'):
        next_path = '/'

    return {
        'email': email,
        'issuer': payload.get('iss'),
        'next': next_path,
        'jti': jti,
        'exp': exp,
    }
