"""Tests del login unificado."""
from app.services.auth_login_service import (
    AUTH_MODE_PIN,
    AUTH_MODE_PASSWORD,
    default_auth_mode_for_role,
    identifier_looks_like_email,
    normalize_auth_mode,
)


def test_identifier_looks_like_email():
    assert identifier_looks_like_email('a@b.com') is True
    assert identifier_looks_like_email('12345678A') is False


def test_default_auth_mode_operario_pin():
    assert default_auth_mode_for_role('operario') == AUTH_MODE_PIN
    assert default_auth_mode_for_role('admin') == AUTH_MODE_PASSWORD


def test_normalize_auth_mode():
    assert normalize_auth_mode('both', role='operario') == 'both'
    assert normalize_auth_mode('invalid', role='operario') == AUTH_MODE_PIN
