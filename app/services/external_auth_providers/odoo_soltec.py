import json
import socket
from urllib import error, request

from app.services.config_service import get_tenant_config
from app.services.external_auth_providers.base import (
    ExternalAuthDecision,
    ExternalAuthResult,
)


_UNAVAILABLE_HTTP_CODES = {404, 405, 502, 503}


def _normalize_base_url(url):
    return (url or '').strip().rstrip('/')


class OdooSoltecProvider:
    provider_name = 'odoo_soltec'

    def __init__(self):
        base_url = get_tenant_config(
            'external_auth_odoo_url',
            default=get_tenant_config('odoo_url', default=''),
        )
        self.base_url = _normalize_base_url(base_url)
        timeout_raw = get_tenant_config('external_auth_odoo_timeout_seconds', default='12')
        try:
            self.timeout = max(1.0, min(15.0, float(timeout_raw)))
        except Exception:
            self.timeout = 12.0

    def is_configured(self):
        return bool(self.base_url and self.base_url.startswith('http'))

    def verify(self, email, password):
        if not self.is_configured():
            return ExternalAuthResult(
                decision=ExternalAuthDecision.UNAVAILABLE,
                provider=self.provider_name,
                reason='not_configured',
            )

        payload = json.dumps({
            'jsonrpc': '2.0',
            'method': 'call',
            'params': {
                'login': (email or '').strip(),
                'password': password or '',
            },
        }).encode('utf-8')
        req = request.Request(
            f'{self.base_url}/portal/soltec/login',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                status_code = getattr(resp, 'status', None)
                raw = resp.read().decode('utf-8', errors='replace')
        except error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace')
            if exc.code in _UNAVAILABLE_HTTP_CODES:
                return ExternalAuthResult(
                    decision=ExternalAuthDecision.UNAVAILABLE,
                    provider=self.provider_name,
                    reason='http_unavailable',
                    status_code=exc.code,
                    detail=body[:500],
                )
            return self._parse_error_payload(body, status_code=exc.code)
        except (error.URLError, socket.timeout, TimeoutError) as exc:
            return ExternalAuthResult(
                decision=ExternalAuthDecision.UNAVAILABLE,
                provider=self.provider_name,
                reason='network_error',
                detail=str(exc),
            )
        except Exception as exc:
            return ExternalAuthResult(
                decision=ExternalAuthDecision.UNAVAILABLE,
                provider=self.provider_name,
                reason='unexpected_error',
                detail=str(exc),
            )

        return self._parse_success_payload(raw, status_code=status_code)

    def _parse_success_payload(self, raw_body, status_code=None):
        try:
            data = json.loads(raw_body or '{}')
        except Exception:
            return ExternalAuthResult(
                decision=ExternalAuthDecision.UNAVAILABLE,
                provider=self.provider_name,
                reason='invalid_json',
                status_code=status_code,
                detail=(raw_body or '')[:500],
            )

        if 'error' in data:
            return self._result_from_error(data['error'], status_code=status_code)

        result = data.get('result')
        if isinstance(result, dict):
            success = bool(result.get('success'))
        else:
            success = bool(result)
        return ExternalAuthResult(
            decision=ExternalAuthDecision.VALID if success else ExternalAuthDecision.INVALID,
            provider=self.provider_name,
            reason='remote_check',
            status_code=status_code,
        )

    def _parse_error_payload(self, raw_body, status_code=None):
        try:
            data = json.loads(raw_body or '{}')
        except Exception:
            return ExternalAuthResult(
                decision=ExternalAuthDecision.UNAVAILABLE,
                provider=self.provider_name,
                reason='http_error',
                status_code=status_code,
                detail=(raw_body or '')[:500],
            )
        if 'error' in data:
            return self._result_from_error(data['error'], status_code=status_code)
        return ExternalAuthResult(
            decision=ExternalAuthDecision.UNAVAILABLE,
            provider=self.provider_name,
            reason='http_error',
            status_code=status_code,
            detail=(raw_body or '')[:500],
        )

    def _result_from_error(self, payload, status_code=None):
        text = json.dumps(payload, ensure_ascii=False).lower()
        unavailable = 'not found' in text or 'does not exist' in text
        return ExternalAuthResult(
            decision=(
                ExternalAuthDecision.UNAVAILABLE if unavailable
                else ExternalAuthDecision.UNAVAILABLE
            ),
            provider=self.provider_name,
            reason='endpoint_missing' if unavailable else 'remote_error',
            status_code=status_code,
            detail=text[:500],
        )
