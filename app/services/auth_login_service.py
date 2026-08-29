"""Login unificado: correo+contraseña o DNI+PIN."""
from __future__ import annotations

import re

from werkzeug.security import check_password_hash

from app.models import User
from app.services.i18n_service import translate
from app.services.pin_auth_service import PinAuthError, autenticar_por_pin

AUTH_MODE_PIN = 'pin'
AUTH_MODE_PASSWORD = 'password'
AUTH_MODE_BOTH = 'both'

_EMAIL_LIKE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def default_auth_mode_for_role(role: str) -> str:
    if role == 'operario':
        return AUTH_MODE_PIN
    return AUTH_MODE_PASSWORD


def normalize_auth_mode(value, *, role=None) -> str:
    val = (value or '').strip().lower()
    if val in (AUTH_MODE_PIN, AUTH_MODE_PASSWORD, AUTH_MODE_BOTH):
        return val
    if role:
        return default_auth_mode_for_role(role)
    return AUTH_MODE_PASSWORD


def user_allows_pin(user) -> bool:
    mode = normalize_auth_mode(getattr(user, 'auth_mode', None), role=getattr(user, 'role', None))
    return mode in (AUTH_MODE_PIN, AUTH_MODE_BOTH)


def user_allows_password(user) -> bool:
    mode = normalize_auth_mode(getattr(user, 'auth_mode', None), role=getattr(user, 'role', None))
    return mode in (AUTH_MODE_PASSWORD, AUTH_MODE_BOTH)


def identifier_looks_like_email(identifier: str) -> bool:
    return bool(_EMAIL_LIKE.match((identifier or '').strip().lower()))


def login_with_email_password(email: str, password: str):
    """Devuelve User o None. No valida auth_mode ni is_active."""
    email = (email or '').strip().lower()
    if not email or not password:
        return None
    user = User.query.filter_by(email=email, is_deleted=False).first()
    if not user or not user.password_hash:
        return None
    if not check_password_hash(user.password_hash, password):
        return None
    if not user_allows_password(user):
        raise ValueError(
            translate(
                'Esta cuenta entra con DNI y PIN. Usa tu DNI en el primer campo.'
            )
        )
    return user


def login_with_dni_pin(dni: str, pin: str):
    """Devuelve User. Lanza PinAuthError o ValueError si auth_mode no permite PIN."""
    user = autenticar_por_pin(dni, pin)
    if not user_allows_pin(user):
        raise ValueError(
            translate(
                'Esta cuenta entra con correo y contraseña. Usa tu email en el primer campo.'
            )
        )
    return user
