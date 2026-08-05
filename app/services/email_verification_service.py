# app/services/email_verification_service.py
#
# Tras el alta en signaplan.com, el admin confirma el correo con un enlace
# firmado (mismo patrón que la recuperación de contraseña).

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import db
from app.models import User
from app.services.email_service import send_email

TOKEN_MAX_AGE = 48 * 3600  # 48 horas
_SALT = 'signaplan-email-verification'


class EmailVerificationError(Exception):
    """Token inválido, caducado o usuario no encontrado."""


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
            'El enlace de verificación ha caducado. Solicita uno nuevo o contacta con soporte.'
        ) from exc
    except BadSignature as exc:
        raise EmailVerificationError('El enlace de verificación no es válido.') from exc

    if int(data.get('tid') or 0) != int(tenant_esperado.id):
        raise EmailVerificationError('Este enlace no corresponde a esta empresa.')
    return data


def url_verificacion(tenant, token):
    """URL absoluta en el host del tenant."""
    from urllib.parse import quote

    from app.services.signup_service import url_acceso_tenant

    return url_acceso_tenant(
        tenant, path=f'/auth/verificar-email?t={quote(token, safe="")}'
    )


def enviar_email_verificacion(tenant, user):
    """
    Envía el correo con el enlace. Devuelve True si salió.

    Si MAIL_PASSWORD está vacío (dev sin SMTP), no intenta enviar: deja la URL
    en el log para poder probar el flujo a mano.
    """
    from flask import current_app

    token = generar_token(user, tenant)
    url = url_verificacion(tenant, token)

    if not (current_app.config.get('MAIL_PASSWORD') or '').strip():
        current_app.logger.warning(
            'MAIL_PASSWORD vacío: no se envía verificación a %s. '
            'URL de depuración: %s',
            user.email,
            url,
        )
        return False

    texto = (
        f'Hola {user.name},\n\n'
        f'Has creado el espacio {tenant.nombre} en SignaPlan.\n'
        f'Confirma tu correo en las próximas 48 horas abriendo este enlace:\n\n'
        f'{url}\n\n'
        f'Si no has sido tú, ignora este mensaje.\n'
    )
    html = (
        f'<p>Hola {user.name},</p>'
        f'<p>Has creado el espacio <strong>{tenant.nombre}</strong> en SignaPlan.</p>'
        f'<p>Confirma tu correo en las próximas 48 horas:</p>'
        f'<p><a href="{url}">Verificar correo y entrar</a></p>'
        f'<p>Si no has sido tú, ignora este mensaje.</p>'
    )
    ok = send_email(
        f'Verifica tu correo — {tenant.nombre}',
        [user.email],
        texto,
        html_body=html,
    )
    if not ok:
        current_app.logger.warning(
            'Falló el envío de verificación a %s. URL de depuración: %s',
            user.email,
            url,
        )
    return ok


def confirmar_email(token, tenant):
    """
    Marca email_verified y active, y devuelve el User listo para login_user.

    Tras el commit hay que volver a fijar search_path y recargar el usuario:
    el pool de Postgres puede devolver una conexión sin el schema del tenant,
    y Flask-Login al leer is_active dispara un ObjectDeletedError.
    """
    from sqlalchemy import text

    data = leer_token(token, tenant)
    schema = tenant.schema_name
    db.session.execute(text(f'SET search_path TO {schema}, public'))

    user = User.query.filter_by(id=data['uid'], is_deleted=False).first()
    if not user or (user.email or '').lower() != (data.get('email') or '').lower():
        raise EmailVerificationError('No se ha podido verificar la cuenta.')

    user.email_verified = True
    user.active = True
    user_id = user.id
    db.session.commit()

    db.session.execute(text(f'SET search_path TO {schema}, public'))
    user = User.query.get(user_id)
    if user is None:
        raise EmailVerificationError('No se ha podido verificar la cuenta.')
    return user
