# app/services/email_verification_service.py
#
# Verificación de correo tras el alta autoservicio. El token lleva tenant_id +
# user_id para no cruzar esquemas multi-tenant. Confirmar solo marca
# email_verified; el acceso (active) ya está permitido tras el alta.

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import text
from urllib.parse import quote

from app import db
from app.models import User
from app.services.email_service import send_email

TOKEN_MAX_AGE = 86400 * 3  # 3 días
_SALT = 'signaplan-email-verify'


class EmailVerificationError(Exception):
    pass


def _serializer():
    from flask import current_app
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        raise EmailVerificationError('SECRET_KEY no configurada.')
    return URLSafeTimedSerializer(secret_key=secret, salt=_SALT)


def generar_token(user, tenant):
    return _serializer().dumps({
        'uid': user.id,
        'tid': tenant.id,
        'email': (user.email or '').strip().lower(),
    })


def leer_token(token, tenant_esperado):
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired as exc:
        raise EmailVerificationError(
            'El enlace de verificación ha caducado. Solicita uno nuevo.'
        ) from exc
    except BadSignature as exc:
        raise EmailVerificationError('El enlace de verificación no es válido.') from exc

    if int(data.get('tid') or 0) != int(tenant_esperado.id):
        raise EmailVerificationError('Este enlace no corresponde a esta empresa.')
    return data


def _url_verificacion(tenant, token):
    from app.services.signup_service import url_acceso_tenant
    return url_acceso_tenant(
        tenant, path=f'/auth/verificar-email?t={quote(token, safe="")}'
    )


def enviar_email_verificacion(tenant, user):
    """
    Envía el enlace de verificación. Devuelve True si el correo salió;
    False si falló el envío (la cuenta sigue creada).
    """
    if not user or not user.email:
        return False
    if getattr(user, 'email_verified', False):
        return True

    token = generar_token(user, tenant)
    url = _url_verificacion(tenant, token)
    texto = (
        f'Hola {user.name},\n\n'
        f'Confirma tu correo para SignaPlan ({tenant.nombre}):\n\n{url}\n\n'
        f'El enlace caduca en 3 días. Si no has creado esta cuenta, ignora este mensaje.\n'
    )
    html = (
        f'<p>Hola {user.name},</p>'
        f'<p>Confirma tu correo para <strong>SignaPlan</strong> ({tenant.nombre}).</p>'
        f'<p><a href="{url}">Verificar correo</a></p>'
        f'<p>El enlace caduca en 3 días. Si no has creado esta cuenta, ignora este mensaje.</p>'
    )
    return bool(send_email(
        f'Verifica tu correo — {tenant.nombre}',
        [user.email],
        texto,
        html_body=html,
    ))


def confirmar_email(token, tenant):
    """
    Marca email_verified=True. No toca active (el admin ya puede entrar).
    Devuelve el User en el esquema del tenant.
    """
    data = leer_token(token, tenant)

    db.session.execute(text(f'SET search_path TO {tenant.schema_name}, public'))
    user = User.query.filter_by(id=data['uid'], is_deleted=False).first()
    if not user or (user.email or '').strip().lower() != (data.get('email') or '').lower():
        raise EmailVerificationError('No se ha podido verificar el correo.')

    user.email_verified = True
    db.session.commit()
    return user


def reenviar_verificacion(tenant, email=None, user=None):
    """
    Reenvía el correo de verificación. Si ya está verificado, no hace nada
    (sin delatar el estado hacia fuera cuando se llama solo con email).
    """
    if user is None:
        email = (email or '').strip().lower()
        if not email:
            raise EmailVerificationError('Indica tu correo.')
        user = User.query.filter_by(email=email, is_deleted=False).first()

    if not user:
        return False
    if getattr(user, 'email_verified', False):
        return True
    if not enviar_email_verificacion(tenant, user):
        raise EmailVerificationError(
            'No se ha podido enviar el correo. Prueba más tarde o contacta con soporte.'
        )
    return True
