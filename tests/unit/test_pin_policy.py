"""Política de PIN: generado vs explícito + lockout + enlace definir (sin PIN en claro)."""
import pytest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from werkzeug.security import check_password_hash, generate_password_hash

from app.services.pin_auth_service import (
    PIN_LOCKOUT_SECONDS,
    PIN_MAX_FAILED_ATTEMPTS,
    PinAuthError,
    asignar_pin_explicito,
    asignar_pin_generado,
    autenticar_por_pin,
    debe_cambiar_pin,
    definir_pin_desde_token,
    forzar_cambio_pin_primer_acceso,
    generar_token_definir_pin,
    notificar_definir_pin_por_email,
    validar_pin,
)
from app.models import ROLE_OPERARIO
from app.utils.timezone_utils import utc_now


def test_validar_pin_rechaza_repetidos():
    with pytest.raises(PinAuthError):
        validar_pin('0000')


def test_validar_pin_ok():
    assert validar_pin('2580') == '2580'


def test_pin_generado_marca_must_change():
    user = SimpleNamespace(role=ROLE_OPERARIO, pin_hash=None, pin_must_change=False, email=None)
    _, pin = asignar_pin_generado(user, notify=False)
    assert len(pin) >= 4
    assert user.pin_hash
    assert debe_cambiar_pin(user)
    forzar_cambio_pin_primer_acceso(user, '2580', '2580')
    assert not debe_cambiar_pin(user)


def test_pin_explicito_no_fuerza_cambio():
    user = SimpleNamespace(role=ROLE_OPERARIO, pin_hash=None, pin_must_change=False, email=None)
    asignar_pin_explicito(user, '2580', notify=False)
    assert not debe_cambiar_pin(user)


def test_autenticar_bloquea_tras_fallos():
    user = SimpleNamespace(
        id=1,
        role=ROLE_OPERARIO,
        active=True,
        pin_hash=generate_password_hash('2580'),
        pin_failed_attempts=PIN_MAX_FAILED_ATTEMPTS - 1,
        pin_locked_until=None,
    )
    with patch('app.services.pin_auth_service.buscar_por_dni', return_value=user), \
         patch('app.services.pin_auth_service.db') as mock_db:
        mock_db.session = MagicMock()
        with pytest.raises(PinAuthError) as exc:
            autenticar_por_pin('12345678A', '0000')
        assert 'Espera' in str(exc.value)
        assert user.pin_locked_until is not None
        assert user.pin_failed_attempts == 0


def test_autenticar_respeta_lockout_activo():
    user = SimpleNamespace(
        id=1,
        role=ROLE_OPERARIO,
        active=True,
        pin_hash=generate_password_hash('2580'),
        pin_failed_attempts=0,
        pin_locked_until=utc_now() + timedelta(seconds=PIN_LOCKOUT_SECONDS),
    )
    with patch('app.services.pin_auth_service.buscar_por_dni', return_value=user):
        with pytest.raises(PinAuthError) as exc:
            autenticar_por_pin('12345678A', '2580')
        assert 'Espera' in str(exc.value)


def test_email_definir_pin_no_incluye_pin_en_claro(app):
    user = SimpleNamespace(
        id=7,
        role=ROLE_OPERARIO,
        name='Ana',
        dni='12345678A',
        email='ana@empresa.test',
        pin_hash=None,
        pin_must_change=False,
    )
    tenant = SimpleNamespace(id=3, nombre='Acme', schema_name='t_acme', subdomain='acme')
    captured = {}

    def _fake_send(asunto, destinatarios, texto, html_body=None):
        captured['asunto'] = asunto
        captured['texto'] = texto
        captured['html'] = html_body or ''
        return True

    with app.app_context():
        with patch('app.services.pin_auth_service._resolver_tenant_para_email', return_value=tenant), \
             patch(
                 'app.services.signup_service.url_acceso_tenant',
                 return_value='https://acme.signaplan.com/fichaje/definir-pin?t=TOK',
             ), \
             patch('app.services.email_service.send_email', side_effect=_fake_send):
            assert notificar_definir_pin_por_email(user) is True

    assert 'PIN:' not in captured['texto']
    assert 'PIN:' not in captured['html']
    assert 'Definir mi PIN' in captured['html']
    assert 'definir' in captured['texto'].lower()
    assert 'definir-pin' in captured['texto'] or 'definir-pin' in captured['html']


def test_definir_pin_desde_token(app):
    user = SimpleNamespace(
        id=11,
        role=ROLE_OPERARIO,
        active=True,
        email='op@empresa.test',
        pin_hash=None,
        pin_must_change=True,
        pin_failed_attempts=2,
        pin_locked_until='x',
        is_deleted=False,
    )
    tenant = SimpleNamespace(id=5, nombre='Acme', schema_name='t_acme')

    with app.app_context():
        token = generar_token_definir_pin(user, tenant)
        with patch('app.services.pin_auth_service.User') as MockUser:
            MockUser.query.filter_by.return_value.first.return_value = user
            out = definir_pin_desde_token(token, tenant, '2580', '2580')
        assert out is user
        assert check_password_hash(user.pin_hash, '2580')
        assert user.pin_must_change is False
        assert user.pin_failed_attempts == 0
        assert user.pin_locked_until is None
