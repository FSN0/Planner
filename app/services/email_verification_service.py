# app/services/email_verification_service.py
#
# Enlaces viejos {subdominio}/auth/verificar-email?t= (alta anterior).
# El alta nueva confirma en signaplan.com/alta/confirmar y crea el tenant después.

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import text

from app import db
from app.models import User
from app.services.i18n_service import translate

TOKEN_MAX_AGE = 86400 * 3  # 3 días
_SALT = 'signaplan-email-verify'


class EmailVerificationError(Exception):
    pass


def _serializer():
    from flask import current_app
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        raise EmailVerificationError(translate('SECRET_KEY no configurada.'))
    return URLSafeTimedSerializer(secret_key=secret, salt=_SALT)


def leer_token(token, tenant_esperado):
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired as exc:
        raise EmailVerificationError(
            translate('El enlace de verificación ha caducado. Solicita uno nuevo.')
        ) from exc
    except BadSignature as exc:
        raise EmailVerificationError(translate('El enlace de verificación no es válido.')) from exc

    if int(data.get('tid') or 0) != int(tenant_esperado.id):
        raise EmailVerificationError(translate('Este enlace no corresponde a esta empresa.'))
    return data


def confirmar_email(token, tenant):
    """
    Marca email_verified=True en un tenant que ya existía.
    Devuelve el User en el esquema del tenant.
    """
    data = leer_token(token, tenant)

    db.session.execute(text(f'SET search_path TO {tenant.schema_name}, public'))
    user = User.query.filter_by(id=data['uid'], is_deleted=False).first()
    if not user or (user.email or '').strip().lower() != (data.get('email') or '').lower():
        raise EmailVerificationError(translate('No se ha podido verificar el correo.'))

    user.email_verified = True
    db.session.commit()
    return user
