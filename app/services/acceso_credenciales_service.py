"""Enlace para que la persona elija PIN, contraseña, o las dos."""
from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import generate_password_hash

from app.services.compliance_rules import email_es_real
from app.services.email_service import send_email
from app.services.i18n_service import translate

TOKEN_MAX_AGE = 14 * 24 * 3600
_SALT = 'signaplan-credenciales'


class CredencialesError(Exception):
    pass


def _serializer():
    from flask import current_app
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        raise CredencialesError(translate('SECRET_KEY no configurada.'))
    return URLSafeTimedSerializer(secret_key=secret, salt=_SALT)


def generar_token(user, tenant) -> str:
    return _serializer().dumps({'uid': user.id, 'tid': tenant.id})


def leer_token(token, tenant) -> dict:
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired as exc:
        raise CredencialesError(translate('El enlace ha caducado. Pide otro.')) from exc
    except BadSignature as exc:
        raise CredencialesError(translate('El enlace no es válido.')) from exc
    if not tenant or int(data.get('tid') or 0) != int(tenant.id):
        raise CredencialesError(translate('El enlace no corresponde a este espacio.'))
    return data


def url_credenciales(user, tenant) -> str:
    from flask import url_for
    token = generar_token(user, tenant)
    return url_for('auth.credenciales', token=token, _external=True)


def enviar_enlace(user, tenant) -> str:
    """Devuelve la URL. Si no hay correo real, no envía y lanza CredencialesError."""
    url = url_credenciales(user, tenant)
    if not email_es_real(user.email):
        raise CredencialesError(translate(
            'Esta persona no tiene un correo de acceso. Escríbelo en el planner '
            '(puede ser el de la empresa) y vuelve a pulsar.'
        ))
    ok = send_email(
        translate('Acceso a SignaPlan'),
        [user.email],
        translate(
            'Hola {nombre}. Entra en este enlace para crear tu acceso. '
            'Puedes elegir un PIN, una contraseña, o las dos cosas.\n\n{url}',
            nombre=user.name or '',
            url=url,
        ),
    )
    if not ok:
        raise CredencialesError(translate('No se ha podido enviar el correo. El enlace sigue siendo válido para copiarlo.'))
    return url


def aplicar_credenciales(user, *, password=None, pin=None) -> None:
    from app.services.pin_auth_service import PinAuthError, asignar_pin
    password = (password or '').strip()
    pin = (pin or '').strip()
    if not password and not pin:
        raise CredencialesError(translate('Elige un PIN, una contraseña, o las dos.'))
    if password:
        if len(password) < 8:
            raise CredencialesError(translate('La contraseña debe tener al menos 8 caracteres.'))
        user.password_hash = generate_password_hash(password)
    if pin:
        try:
            asignar_pin(user, pin, must_change=False, notify=False)
        except PinAuthError as exc:
            raise CredencialesError(str(exc)) from exc
    if password and pin:
        user.auth_mode = 'both'
    elif pin:
        user.auth_mode = 'pin'
    else:
        user.auth_mode = 'password'
