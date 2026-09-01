# app/services/pin_auth_service.py
#
# Acceso del trabajador con DNI y PIN numérico.
#
# Política de producto:
# - Si el admin/import pone un PIN explícito → ese es el definitivo (salvo que
#   el trabajador lo redefina con el enlace).
# - Si se genera aleatorio → pin_must_change=True hasta el primer cambio en la app.
# - Nunca se envía el PIN en claro por correo: se manda un enlace para definirlo.

import re
import secrets
from urllib.parse import quote

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.models import (
    ROLE_ADMIN,
    ROLE_JEFE,
    ROLE_LABORAL,
    ROLE_OPERARIO,
    ROLE_RRHH,
    User,
)
from app.services.i18n_service import translate, normalize_locale, get_locale, DEFAULT_LOCALE

ROLES_CON_PIN = (ROLE_OPERARIO, ROLE_JEFE, ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH)

PIN_MIN = 4
PIN_MAX = 6
_PIN_RE = re.compile(rf'^\d{{{PIN_MIN},{PIN_MAX}}}$')

# Tras N fallos, bloqueo corto (obra: no castigar de más).
PIN_MAX_FAILED_ATTEMPTS = 5
PIN_LOCKOUT_SECONDS = 60

# Enlace "definir PIN" (mismo espíritu que verificar email).
PIN_SETUP_TOKEN_MAX_AGE = 86400 * 3  # 3 días
_PIN_SETUP_SALT = 'signaplan-pin-setup'


class PinAuthError(Exception):
    """Error de validación o uso del PIN."""


def normalizar_dni(valor):
    """Quita espacios, guiones y pasa a mayúsculas: 12.345.678-A → 12345678A."""
    return re.sub(r'[^A-Z0-9]', '', (valor or '').upper())


def validar_pin(pin):
    pin = (pin or '').strip()
    if not _PIN_RE.match(pin):
        raise PinAuthError(
            translate(
                'El PIN tiene que tener entre {min} y {max} dígitos.',
                min=PIN_MIN,
                max=PIN_MAX,
            )
        )
    if len(set(pin)) == 1:
        raise PinAuthError(translate('Elige un PIN que no sea el mismo dígito repetido.'))
    return pin


def generar_pin_aleatorio(longitud=4):
    """PIN numérico usable: evita dígitos todos iguales."""
    longitud = max(PIN_MIN, min(PIN_MAX, int(longitud or 4)))
    for _ in range(40):
        pin = ''.join(str(secrets.randbelow(10)) for _ in range(longitud))
        if len(set(pin)) > 1:
            return pin
    return '2580'[:longitud]


def _email_parece_real(email):
    email = (email or '').strip().lower()
    if not email or '@' not in email:
        return False
    # Placeholders internos del alta rápida / demos
    if email.endswith('@local.signaplan') or email.endswith('@demo.signaplan'):
        return False
    return True


def asegurar_rol_con_pin(user):
    """
    Garantiza un rol que admite PIN de fichaje.

    Roles inventados en Excel (oficial, peón…) se corrigen a operario.
    Operario, jefe, admin, laboral y RRHH pueden fichar (obra u oficina).
    """
    role = (user.role or '').strip().lower()
    if role in ROLES_CON_PIN:
        if user.role != role:
            user.role = role
        return user
    # Rol desconocido / legacy de importación → operario
    user.role = ROLE_OPERARIO
    return user


def asignar_pin(user, pin, *, must_change=False, notify=False, actor=None):
    """
    Guarda el hash del PIN. No hace commit.

    must_change: obliga a cambiarlo en el primer acceso a la app.
    notify: si True y el usuario tiene email real, envía enlace para definir PIN
    (nunca el PIN en claro).
    """
    asegurar_rol_con_pin(user)
    pin = validar_pin(pin)
    user.pin_hash = generate_password_hash(pin)
    user.pin_must_change = bool(must_change)
    # No reactivar automáticamente: una baja (manual u Odoo) debe revertirse
    # marcando de nuevo «Usuario activo», no al asignar PIN.
    if notify:
        notificar_definir_pin_por_email(user, actor=actor)
    return user


def asignar_pin_explicito(user, pin, *, notify=True, actor=None):
    """PIN puesto a mano por admin/import: no fuerza cambio."""
    return asignar_pin(
        user, pin, must_change=False, notify=notify, actor=actor
    )


def asignar_pin_generado(user, *, notify=True, actor=None, longitud=4):
    """
    Genera PIN aleatorio y marca must_change.
    Devuelve (user, pin_plano) — el plano solo se usa para mostrar en pantalla
    de admin una vez; el correo lleva enlace, no el PIN.
    """
    pin = generar_pin_aleatorio(longitud)
    asignar_pin(user, pin, must_change=True, notify=notify, actor=actor)
    return user, pin


def quitar_pin(user):
    """Deja al trabajador sin acceso por PIN hasta que le pongan otro."""
    user.pin_hash = None
    user.pin_must_change = False
    return user


def tiene_pin(user):
    return bool(user and user.pin_hash)


def debe_cambiar_pin(user):
    return bool(user and user.pin_hash and getattr(user, 'pin_must_change', False))


def cambiar_pin_propio(user, pin_actual, pin_nuevo, pin_nuevo2):
    """El operario cambia su PIN desde Fichaje → PIN. No hace commit."""
    if not user or not user.pin_hash:
        raise PinAuthError(translate('Todavía no tienes PIN. Pídeselo a administración.'))
    pin_actual = (pin_actual or '').strip()
    if not pin_actual or not check_password_hash(user.pin_hash, pin_actual):
        raise PinAuthError(translate('El PIN actual no es correcto.'))
    if (pin_nuevo or '').strip() != (pin_nuevo2 or '').strip():
        raise PinAuthError(translate('El PIN nuevo no coincide.'))
    asignar_pin(user, pin_nuevo, must_change=False, notify=False)
    return user


def forzar_cambio_pin_primer_acceso(user, pin_nuevo, pin_nuevo2):
    """Primer cambio obligatorio tras PIN generado. No pide el PIN viejo."""
    if not debe_cambiar_pin(user):
        raise PinAuthError(translate('No hace falta cambiar el PIN ahora.'))
    if (pin_nuevo or '').strip() != (pin_nuevo2 or '').strip():
        raise PinAuthError(translate('El PIN nuevo no coincide.'))
    asignar_pin(user, pin_nuevo, must_change=False, notify=False)
    return user


def _serializer_pin_setup():
    from flask import current_app
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        raise PinAuthError(translate('SECRET_KEY no configurada.'))
    return URLSafeTimedSerializer(secret_key=secret, salt=_PIN_SETUP_SALT)


def generar_token_definir_pin(user, tenant):
    return _serializer_pin_setup().dumps({
        'uid': user.id,
        'tid': tenant.id,
        'email': (user.email or '').strip().lower(),
    })


def leer_token_definir_pin(token, tenant_esperado):
    try:
        data = _serializer_pin_setup().loads(token, max_age=PIN_SETUP_TOKEN_MAX_AGE)
    except SignatureExpired as exc:
        raise PinAuthError(
            translate(
                'El enlace para definir el PIN ha caducado. Pide uno nuevo a administración.'
            )
        ) from exc
    except BadSignature as exc:
        raise PinAuthError(translate('El enlace para definir el PIN no es válido.')) from exc

    if int(data.get('tid') or 0) != int(tenant_esperado.id):
        raise PinAuthError(translate('Este enlace no corresponde a esta empresa.'))
    return data


def usuario_desde_token_definir_pin(token, tenant):
    """Devuelve (user, error). user es None si el token no es usable."""
    try:
        data = leer_token_definir_pin(token, tenant)
    except PinAuthError as exc:
        return None, str(exc)
    user = User.query.filter_by(id=data.get('uid'), is_deleted=False).first()
    if not user:
        return None, translate('El enlace para definir el PIN no es válido.')
    token_email = (data.get('email') or '').strip().lower()
    if token_email and (user.email or '').strip().lower() != token_email:
        return None, translate('El enlace para definir el PIN no es válido.')
    return user, None


def _url_definir_pin(tenant, token):
    from app.services.signup_service import url_acceso_tenant
    return url_acceso_tenant(
        tenant, path=f'/fichaje/definir-pin?t={quote(token, safe="")}'
    )


def _url_login_tenant(tenant):
    from app.services.signup_service import url_acceso_tenant
    return url_acceso_tenant(tenant, path='/auth/login')


def _resolver_tenant_para_email():
    from flask import g, has_request_context
    if has_request_context():
        return getattr(g, 'current_tenant', None)
    return None


def notificar_definir_pin_por_email(user, actor=None):
    """
    Envía enlace para que el trabajador defina su PIN.
    Nunca incluye el PIN en claro. Devuelve False si no hay email o falla SMTP.
    """
    if not _email_parece_real(getattr(user, 'email', None)):
        return False
    try:
        from app.services.email_service import send_email

        tenant = _resolver_tenant_para_email()
        if tenant is None:
            return False

        token = generar_token_definir_pin(user, tenant)
        url = _url_definir_pin(tenant, token)
        tenant_nombre = tenant.nombre or ''
        quien = ''
        if actor is not None:
            quien = f"{getattr(actor, 'name', '')} {getattr(actor, 'lastname', '')}".strip()

        loc = normalize_locale(getattr(user, 'locale', None)) or get_locale() or DEFAULT_LOCALE
        tenant_bit = f' ({tenant_nombre})' if tenant_nombre else ''
        quien_txt = (
            translate(' Te lo ha enviado {quien}.', loc, quien=quien) if quien else ''
        )
        asunto = translate(
            'Define tu PIN de fichaje — {tenant}',
            loc,
            tenant=tenant_nombre or 'SignaPlan',
        )
        texto = translate(
            'Hola {name},\n\n'
            'Te han activado el acceso de fichaje en SignaPlan{tenant}.\n\n'
            'DNI: {dni}\n'
            'Define tu PIN (4–6 dígitos) en este enlace:\n{url}\n\n'
            'El enlace caduca en 3 días.{quien}\n'
            'Si no esperabas este correo, ignóralo.\n',
            loc,
            name=user.name,
            tenant=tenant_bit,
            dni=user.dni,
            url=url,
            quien=quien_txt,
        )
        html_tenant = (
            translate(' en <strong>{tenant}</strong>', loc, tenant=tenant_nombre)
            if tenant_nombre else ''
        )
        html = translate(
            '<p>Hola {name},</p>'
            '<p>Te han activado el acceso de fichaje{tenant}.</p>'
            '<p><strong>DNI:</strong> {dni}</p>'
            '<p><a href="{url}">Definir mi PIN</a></p>'
            '<p>El enlace caduca en 3 días. No compartas este enlace.</p>',
            loc,
            name=user.name,
            tenant=html_tenant,
            dni=user.dni,
            url=url,
        )
        return bool(send_email(asunto, [user.email], texto, html_body=html))
    except Exception:
        return False


def notificar_informacion_acceso(user, actor=None):
    """
    Instrucciones completas de acceso: URL de login, DNI y enlace para definir/cambiar PIN.
    Nunca incluye el PIN en claro.
    """
    if not _email_parece_real(getattr(user, 'email', None)):
        return False
    try:
        from app.services.email_service import send_email

        tenant = _resolver_tenant_para_email()
        if tenant is None:
            return False

        token = generar_token_definir_pin(user, tenant)
        url_pin = _url_definir_pin(tenant, token)
        url_login = _url_login_tenant(tenant)
        tenant_nombre = tenant.nombre or ''
        quien = ''
        if actor is not None:
            quien = f"{getattr(actor, 'name', '')} {getattr(actor, 'lastname', '')}".strip()

        loc = normalize_locale(getattr(user, 'locale', None)) or get_locale() or DEFAULT_LOCALE
        tenant_bit = f' ({tenant_nombre})' if tenant_nombre else ''
        quien_txt = (
            translate(' Te lo ha enviado {quien}.', loc, quien=quien) if quien else ''
        )

        if user.pin_hash:
            pin_info = translate(
                'Ya tienes PIN activo. Si no lo recuerdas, pídeselo a quien te dio de alta. '
                'Puedes cambiarlo entrando en la app (Fichaje → PIN) o con el enlace de abajo.',
                loc,
            )
        else:
            pin_info = translate(
                'Todavía no tienes PIN. Defínelo con el enlace de abajo (caduca en 3 días).',
                loc,
            )

        asunto = translate(
            'Tu acceso a SignaPlan — {tenant}',
            loc,
            tenant=tenant_nombre or 'SignaPlan',
        )
        texto = translate(
            'Hola {name},\n\n'
            'Así entras a SignaPlan{tenant} para fichar:\n\n'
            '1. Abre: {login_url}\n'
            '2. Usuario: tu DNI ({dni})\n'
            '3. Contraseña: tu PIN de 4–6 dígitos\n\n'
            '{pin_info}\n\n'
            'Definir o restablecer PIN:\n{pin_url}\n\n'
            'Guarda el enlace de acceso en el móvil.{quien}\n'
            'Si no esperabas este correo, ignóralo.\n',
            loc,
            name=user.name,
            tenant=tenant_bit,
            login_url=url_login,
            dni=user.dni,
            pin_info=pin_info,
            pin_url=url_pin,
            quien=quien_txt,
        )
        html_tenant = (
            translate(' en <strong>{tenant}</strong>', loc, tenant=tenant_nombre)
            if tenant_nombre else ''
        )
        html = translate(
            '<p>Hola {name},</p>'
            '<p>Así entras a SignaPlan{tenant} para fichar:</p>'
            '<ol>'
            '<li>Abre <a href="{login_url}">{login_url}</a></li>'
            '<li><strong>DNI:</strong> {dni}</li>'
            '<li><strong>PIN:</strong> 4–6 dígitos (no va en este correo por seguridad)</li>'
            '</ol>'
            '<p>{pin_info}</p>'
            '<p><a href="{pin_url}">Definir o restablecer mi PIN</a> (caduca en 3 días)</p>'
            '<p>Guarda el enlace de acceso en el móvil.</p>',
            loc,
            name=user.name,
            tenant=html_tenant,
            login_url=url_login,
            dni=user.dni,
            pin_info=pin_info,
            pin_url=url_pin,
        )
        return bool(send_email(asunto, [user.email], texto, html_body=html))
    except Exception:
        return False


# Alias de compatibilidad (el PIN en claro ya no se envía).
def notificar_pin_por_email(user, pin_plano=None, actor=None):
    return notificar_definir_pin_por_email(user, actor=actor)


def definir_pin_desde_token(token, tenant, pin_nuevo, pin_nuevo2):
    """
    Define el PIN con el token del correo. No exige sesión ni PIN anterior.
    No hace commit. Devuelve el User.
    """
    data = leer_token_definir_pin(token, tenant)
    user = User.query.filter_by(id=data['uid'], is_deleted=False).first()
    if not user or user.role not in ROLES_CON_PIN:
        raise PinAuthError(translate('No se ha podido definir el PIN.'))
    if (user.email or '').strip().lower() != (data.get('email') or '').lower():
        raise PinAuthError(translate('No se ha podido definir el PIN.'))
    if not user.active:
        raise PinAuthError(translate('Tu cuenta aún no está activa. Contacta con administración.'))
    if (pin_nuevo or '').strip() != (pin_nuevo2 or '').strip():
        raise PinAuthError(translate('El PIN nuevo no coincide.'))
    asignar_pin(user, pin_nuevo, must_change=False, notify=False)
    user.pin_failed_attempts = 0
    user.pin_locked_until = None
    return user


def enviar_acceso_fichaje(user, pin_plano=None, *, actor=None, regenerar=False):
    """
    Prepara el acceso y envía enlace para definir PIN (nunca el PIN en claro).

    - Si se indica pin_plano: lo asigna (el admin puede entregarlo en mano).
    - Si regenerar o no hay PIN: genera uno provisional (must_change) o deja
      que el enlace lo defina; el correo solo lleva el enlace.

    Devuelve (ok_envio, pin_mostrable_admin_o_None).
    """
    asegurar_rol_con_pin(user)
    pin = (pin_plano or '').strip()
    pin_mostrable = None
    if pin:
        asignar_pin_explicito(user, pin, notify=False, actor=actor)
        pin_mostrable = pin
    elif regenerar or not user.pin_hash:
        _, pin_mostrable = asignar_pin_generado(user, notify=False, actor=actor)
    else:
        raise PinAuthError(
            translate(
                'Indica un PIN nuevo o marca «Generar uno nuevo» para enviar el enlace.'
            )
        )
    ok = notificar_definir_pin_por_email(user, actor=actor)
    return ok, pin_mostrable


def buscar_por_dni(dni):
    """
    Localiza al usuario por DNI ignorando formato.

    Compara la versión normalizada en SQL para no depender de si en la base
    está guardado con guiones o sin ellos.
    """
    clave = normalizar_dni(dni)
    if not clave:
        return None

    return (
        User.query
        .filter(
            func.regexp_replace(func.upper(User.dni), '[^A-Z0-9]', '', 'g') == clave,
            User.is_deleted.is_(False),
        )
        .first()
    )


def autenticar_por_pin(dni, pin):
    """
    Devuelve el usuario si el DNI y el PIN cuadran.

    Los mensajes de error son deliberadamente genéricos hacia fuera: no
    confirmar si el DNI existe o si el fallo es el PIN.
    Tras varios fallos se bloquea un minuto (anti fuerza bruta suave).
    """
    from app.utils.timezone_utils import utc_now

    user = buscar_por_dni(dni)
    if user is None or user.role not in ROLES_CON_PIN:
        raise PinAuthError(translate('DNI o PIN incorrectos.'))
    if not user.active:
        raise PinAuthError(translate('Tu cuenta aún no está activa. Contacta con administración.'))
    if not user.pin_hash:
        raise PinAuthError(
            translate(
                'Todavía no tienes PIN. Revisa el correo con el enlace para definirlo '
                'o pídeselo a administración.'
            )
        )

    locked_until = getattr(user, 'pin_locked_until', None)
    now = utc_now()
    if locked_until and locked_until > now:
        secs = max(1, int((locked_until - now).total_seconds()))
        raise PinAuthError(
            translate(
                'Demasiados intentos. Espera {secs} s e inténtalo de nuevo.',
                secs=secs,
            )
        )

    pin = (pin or '').strip()
    if not pin or not check_password_hash(user.pin_hash, pin):
        fails = int(getattr(user, 'pin_failed_attempts', 0) or 0) + 1
        user.pin_failed_attempts = fails
        if fails >= PIN_MAX_FAILED_ATTEMPTS:
            from datetime import timedelta
            user.pin_locked_until = now + timedelta(seconds=PIN_LOCKOUT_SECONDS)
            user.pin_failed_attempts = 0
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
            raise PinAuthError(
                translate(
                    'Demasiados intentos. Espera {secs} s e inténtalo de nuevo.',
                    secs=PIN_LOCKOUT_SECONDS,
                )
            )
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        raise PinAuthError(translate('DNI o PIN incorrectos.'))

    user.pin_failed_attempts = 0
    user.pin_locked_until = None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return user
