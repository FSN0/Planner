# app/services/password_reset_service.py
#
# Recuperación de contraseña por correo. El token lleva tenant_id + user_id
# para no cruzar esquemas multi-tenant.

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import generate_password_hash

from app import db
from app.models import User
from app.services.email_service import send_email
from app.services.i18n_service import translate, normalize_locale, get_locale, DEFAULT_LOCALE

TOKEN_MAX_AGE = 3600  # 1 hora
_SALT = 'signaplan-password-reset'


class PasswordResetError(Exception):
    pass


def _serializer():
    from flask import current_app
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        raise PasswordResetError(translate('SECRET_KEY no configurada.'))
    return URLSafeTimedSerializer(secret_key=secret, salt=_SALT)


def generar_token(user, tenant):
    return _serializer().dumps({'uid': user.id, 'tid': tenant.id, 'email': user.email})


def leer_token(token, tenant_esperado):
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired as exc:
        raise PasswordResetError(translate('El enlace ha caducado. Solicita uno nuevo.')) from exc
    except BadSignature as exc:
        raise PasswordResetError(translate('El enlace no es válido.')) from exc

    if int(data.get('tid') or 0) != int(tenant_esperado.id):
        raise PasswordResetError(translate('Este enlace no corresponde a esta empresa.'))
    return data


def solicitar_reset(email, tenant, reset_url_builder):
    """
    Si el correo existe, envía el enlace. Siempre se comporta igual hacia fuera
    (no delata si el email está o no en la base).
    """
    email = (email or '').strip().lower()
    if not email:
        raise PasswordResetError(translate('Indica tu correo.'))

    user = User.query.filter_by(email=email, is_deleted=False).first()
    if not user or not user.active:
        return False

    token = generar_token(user, tenant)
    url = reset_url_builder(token)
    loc = normalize_locale(getattr(user, 'locale', None)) or get_locale() or DEFAULT_LOCALE
    texto = translate(
        'Hola {name},\n\n'
        'Has pedido restablecer la contraseña de SignaPlan ({tenant}).\n'
        'Abre este enlace en la próxima hora:\n\n{url}\n\n'
        'Si no has sido tú, ignora este correo.\n',
        loc,
        name=user.name,
        tenant=tenant.nombre,
        url=url,
    )
    html = translate(
        '<p>Hola {name},</p>'
        '<p>Has pedido restablecer la contraseña de <strong>SignaPlan</strong> '
        '({tenant}).</p>'
        '<p><a href="{url}">Restablecer contraseña</a></p>'
        '<p>El enlace caduca en una hora. Si no has sido tú, ignora este correo.</p>',
        loc,
        name=user.name,
        tenant=tenant.nombre,
        url=url,
    )
    send_ok = send_email(
        translate('Restablecer contraseña — {tenant}', loc, tenant=tenant.nombre),
        [user.email],
        texto,
        html_body=html,
    )
    if not send_ok:
        raise PasswordResetError(
            translate(
                'No se ha podido enviar el correo de recuperación. '
                'Comprueba la configuración de correo del servidor o contacta con soporte.'
            )
        )
    return True


def aplicar_nueva_password(token, tenant, password, password2):
    data = leer_token(token, tenant)
    if not password or len(password) < 8:
        raise PasswordResetError(translate('La contraseña tiene que tener al menos 8 caracteres.'))
    if password != password2:
        raise PasswordResetError(translate('Las contraseñas no coinciden.'))

    user = User.query.filter_by(id=data['uid'], is_deleted=False).first()
    if not user or user.email.lower() != (data.get('email') or '').lower():
        raise PasswordResetError(translate('No se ha podido actualizar la contraseña.'))
    if not user.active:
        raise PasswordResetError(translate('La cuenta no está activa.'))

    user.password_hash = generate_password_hash(password)
    db.session.commit()
    return user
