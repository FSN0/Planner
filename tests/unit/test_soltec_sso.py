"""Verificación del JWT HS256 de entrada SSO Soltec."""

import json
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.services.soltec_sso_service import (
    CLOCK_SKEW_SECONDS,
    SoltecSsoError,
    _USED_JTIS,
    _b64url_encode,
    verify_soltec_sso_token,
)


SECRET = 'sso-test-secret'


def _mint(claims, secret=SECRET):
    import hashlib
    import hmac

    header = _b64url_encode(json.dumps(
        {'alg': 'HS256', 'typ': 'JWT'},
        separators=(',', ':'),
    ).encode('utf-8'))
    payload = _b64url_encode(json.dumps(claims, separators=(',', ':')).encode('utf-8'))
    sig = hmac.new(
        secret.encode('utf-8'),
        f'{header}.{payload}'.encode('ascii'),
        hashlib.sha256,
    ).digest()
    return f'{header}.{payload}.{_b64url_encode(sig)}'


def _claims(**overrides):
    now = int(datetime.now(timezone.utc).timestamp())
    data = {
        'iss': 'soltec_satellite',
        'aud': 'planner',
        'tenant': 'soltec',
        'email': 'jgarcia@soltecgrupo.es',
        'jti': str(uuid.uuid4()),
        'iat': now,
        'nbf': now,
        'exp': now + 60,
    }
    data.update(overrides)
    return data


@pytest.fixture(autouse=True)
def _sso_config():
    _USED_JTIS.clear()
    with patch(
        'app.services.soltec_sso_service.soltec_sso_enabled',
        return_value=True,
    ), patch(
        'app.services.soltec_sso_service._shared_secret',
        return_value=SECRET,
    ), patch(
        'app.services.soltec_sso_service._expected_issuer',
        return_value='soltec_satellite',
    ):
        yield
    _USED_JTIS.clear()


class TestVerifySoltecSsoToken:
    def test_token_valido(self):
        claims = verify_soltec_sso_token(_mint(_claims()))
        assert claims['email'] == 'jgarcia@soltecgrupo.es'

    def test_falta_parametro_t(self):
        with pytest.raises(SoltecSsoError, match='parámetro t'):
            verify_soltec_sso_token('')

    def test_firma_incorrecta(self):
        with pytest.raises(SoltecSsoError, match='Firma'):
            verify_soltec_sso_token(_mint(_claims(), secret='otra-clave'))

    def test_jti_no_se_reutiliza(self):
        token = _mint(_claims(jti='mismo-jti'))
        verify_soltec_sso_token(token)
        with pytest.raises(SoltecSsoError, match='ya usado'):
            verify_soltec_sso_token(token)

    def test_nbf_dentro_del_margen(self):
        now = int(time.time())
        token = _mint(_claims(
            nbf=now + CLOCK_SKEW_SECONDS - 5,
            iat=now,
            exp=now + 60,
        ))
        assert verify_soltec_sso_token(token)['email'] == 'jgarcia@soltecgrupo.es'
