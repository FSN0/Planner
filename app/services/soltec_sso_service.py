import base64
import hashlib
import hmac
import json
import os
from datetime import timedelta

from app.models import _utc_now
from app.services.config_service import get_tenant_config


SSO_ALG = 'HS256'
SSO_AUD = 'planner'
SSO_TENANT = 'soltec'
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


def verify_soltec_sso_token(token):
    token = (token or '').strip()
    if not soltec_sso_enabled():
        raise SoltecSsoError('SSO Soltec desactivado.')
    secret = _shared_secret()
    if not secret:
        raise SoltecSsoError('Falta la clave compartida SSO.')
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
    if not hmac.compare_digest(_b64url_encode(expected_sig), signature_b64):
        raise SoltecSsoError('Firma SSO inválida.')

    try:
        header = json.loads(_b64url_decode(header_b64).decode('utf-8'))
        payload = json.loads(_b64url_decode(payload_b64).decode('utf-8'))
    except Exception as exc:
        raise SoltecSsoError('Token SSO ilegible.') from exc

    if header.get('alg') != SSO_ALG:
        raise SoltecSsoError('Algoritmo SSO no soportado.')

    now_ts = int(_utc_now().timestamp())
    exp = int(payload.get('exp') or 0)
    if not exp or exp < now_ts:
        raise SoltecSsoError('Token SSO caducado.')

    nbf = int(payload.get('nbf') or 0)
    if nbf and nbf > now_ts + 5:
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
