"""Política de PIN: generado vs explícito."""
import pytest
from types import SimpleNamespace

from app.services.pin_auth_service import (
    PinAuthError,
    asignar_pin_explicito,
    asignar_pin_generado,
    debe_cambiar_pin,
    forzar_cambio_pin_primer_acceso,
    validar_pin,
)
from app.models import ROLE_OPERARIO


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
