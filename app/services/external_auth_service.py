from collections import defaultdict, deque
from datetime import timedelta

from flask import current_app
from werkzeug.security import generate_password_hash

from app import db
from app.models import _utc_now
from app.services.config_service import get_tenant_config
from app.services.external_auth_providers.base import (
    ExternalAuthDecision,
    ExternalAuthResult,
)
from app.services.external_auth_providers.odoo_soltec import OdooSoltecProvider


_BREAKER_FAIL_WINDOW = timedelta(minutes=5)
_BREAKER_OPEN_FOR = timedelta(minutes=3)
_BREAKER_FAILURES = 3
_breaker_state = defaultdict(lambda: {'failures': deque(), 'open_until': None})

_RATE_WINDOW = timedelta(minutes=10)
_RATE_LIMIT = 5
_rate_attempts = defaultdict(deque)


def _provider_name():
    return (get_tenant_config('external_auth_provider', default='') or '').strip().lower()


def external_auth_enabled_for_tenant():
    return _provider_name() == 'odoo_soltec'


def _build_provider():
    provider = _provider_name()
    if provider == 'odoo_soltec':
        return OdooSoltecProvider()
    return None


def can_attempt_external_auth(email, remote_addr, tenant_id):
    email = (email or '').strip().lower()
    ip = (remote_addr or '').strip()
    if not email:
        return False
    now = _utc_now()
    key = f'{tenant_id}:{email}:{ip}'
    bucket = _rate_attempts[key]
    while bucket and (now - bucket[0]) > _RATE_WINDOW:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT:
        return False
    bucket.append(now)
    return True


def _breaker_key(provider_name, tenant_id):
    return f'{tenant_id}:{provider_name}'


def _breaker_is_open(provider_name, tenant_id):
    state = _breaker_state[_breaker_key(provider_name, tenant_id)]
    open_until = state.get('open_until')
    return bool(open_until and open_until > _utc_now())


def _record_provider_result(provider_name, tenant_id, result):
    state = _breaker_state[_breaker_key(provider_name, tenant_id)]
    now = _utc_now()
    failures = state['failures']
    while failures and (now - failures[0]) > _BREAKER_FAIL_WINDOW:
        failures.popleft()
    if result.is_unavailable:
        failures.append(now)
        if len(failures) >= _BREAKER_FAILURES:
            state['open_until'] = now + _BREAKER_OPEN_FOR
    else:
        failures.clear()
        state['open_until'] = None


def verify_external_password(email, password, *, tenant_id):
    provider = _build_provider()
    if not provider:
        return ExternalAuthResult(
            decision=ExternalAuthDecision.SKIPPED,
            reason='provider_disabled',
        )
    if _breaker_is_open(provider.provider_name, tenant_id):
        return ExternalAuthResult(
            decision=ExternalAuthDecision.UNAVAILABLE,
            provider=provider.provider_name,
            reason='circuit_open',
        )
    result = provider.verify(email, password)
    _record_provider_result(provider.provider_name, tenant_id, result)
    return result


def capture_external_password(user, password, *, source='odoo'):
    user.password_hash = generate_password_hash(password)
    user.auth_source_last = source
    if source == 'odoo':
        user.odoo_verified_at = _utc_now()
    db.session.add(user)
    db.session.commit()
    return user


def mark_local_auth_success(user):
    user.auth_source_last = 'local'
    db.session.add(user)
    db.session.commit()
    return user


def external_auth_allowed_for_user(user):
    return bool(
        user
        and not getattr(user, 'is_deleted', False)
        and not getattr(user, 'odoo_fallback_disabled', False)
    )


def log_external_auth_result(user, result, remote_addr):
    try:
        from app.utils import register_log

        user_id = getattr(user, 'id', None)
        label = result.provider or 'external_auth'
        detail = (
            f'Proveedor={label}; estado={result.decision}; motivo={result.reason}; '
            f'IP: {remote_addr or "Desconocida"}'
        )
        register_log(
            user_id=user_id,
            category='accesos',
            action='Fallback autenticación externa',
            detail=detail,
        )
    except Exception:
        current_app.logger.exception('No se pudo registrar el fallback de auth externa')
