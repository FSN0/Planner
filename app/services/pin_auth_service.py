# app/services/pin_auth_service.py
#
# Acceso del trabajador a la PWA con DNI y PIN numérico.
#
# En obra el correo y la contraseña fallan: el teclado pone mayúsculas, nadie
# recuerda un email corporativo y las cuentas importadas del ERP suelen tener
# una contraseña genérica. Un PIN de cuatro a seis cifras, puesto por
# administración, es lo que realmente se usa.
#
# Política de producto:
# - Si el admin/import pone un PIN explícito → ese es el definitivo.
# - Si se genera aleatorio → pin_must_change=True hasta el primer cambio en /mi.
# - Si el trabajador tiene email real → se le avisa del PIN por correo.

import re
import secrets

from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_OPERARIO, User

ROLES_CON_PIN = (ROLE_OPERARIO, ROLE_JEFE, ROLE_ADMIN)

PIN_MIN = 4
PIN_MAX = 6
_PIN_RE = re.compile(rf'^\d{{{PIN_MIN},{PIN_MAX}}}$')


class PinAuthError(Exception):
    """Error de validación o uso del PIN."""


def normalizar_dni(valor):
    """Quita espacios, guiones y pasa a mayúsculas: 12.345.678-A → 12345678A."""
    return re.sub(r'[^A-Z0-9]', '', (valor or '').upper())


def validar_pin(pin):
    pin = (pin or '').strip()
    if not _PIN_RE.match(pin):
        raise PinAuthError(
            f'El PIN tiene que tener entre {PIN_MIN} y {PIN_MAX} dígitos.'
        )
    if len(set(pin)) == 1:
        raise PinAuthError('Elige un PIN que no sea el mismo dígito repetido.')
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


def asignar_pin(user, pin, *, must_change=False, notify=False, actor=None):
    """
    Guarda el hash del PIN. No hace commit.

    must_change: obliga a cambiarlo en el primer acceso a /mi.
    notify: si True y el usuario tiene email real, intenta avisar por correo.
    """
    if user.role not in ROLES_CON_PIN:
        raise PinAuthError('Este perfil no usa PIN de fichaje.')
    pin = validar_pin(pin)
    user.pin_hash = generate_password_hash(pin)
    user.pin_must_change = bool(must_change)
    if notify:
        notificar_pin_por_email(user, pin, actor=actor)
    return user


def asignar_pin_explicito(user, pin, *, notify=True, actor=None):
    """PIN puesto a mano por admin/import: no fuerza cambio."""
    return asignar_pin(
        user, pin, must_change=False, notify=notify, actor=actor
    )


def asignar_pin_generado(user, *, notify=True, actor=None, longitud=4):
    """
    Genera PIN aleatorio y marca must_change.
    Devuelve (user, pin_plano) — el plano solo se usa para mostrar/CSV una vez.
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
    """El operario cambia su PIN desde /mi. No hace commit."""
    if not user or not user.pin_hash:
        raise PinAuthError('Todavía no tienes PIN. Pídeselo a administración.')
    pin_actual = (pin_actual or '').strip()
    if not pin_actual or not check_password_hash(user.pin_hash, pin_actual):
        raise PinAuthError('El PIN actual no es correcto.')
    if (pin_nuevo or '').strip() != (pin_nuevo2 or '').strip():
        raise PinAuthError('El PIN nuevo no coincide.')
    asignar_pin(user, pin_nuevo, must_change=False, notify=False)
    return user


def forzar_cambio_pin_primer_acceso(user, pin_nuevo, pin_nuevo2):
    """Primer cambio obligatorio tras PIN generado. No pide el PIN viejo."""
    if not debe_cambiar_pin(user):
        raise PinAuthError('No hace falta cambiar el PIN ahora.')
    if (pin_nuevo or '').strip() != (pin_nuevo2 or '').strip():
        raise PinAuthError('El PIN nuevo no coincide.')
    asignar_pin(user, pin_nuevo, must_change=False, notify=False)
    return user


def notificar_pin_por_email(user, pin_plano, actor=None):
    """Avisa del PIN por correo si hay email real. No levanta si falla el SMTP."""
    if not _email_parece_real(getattr(user, 'email', None)):
        return False
    try:
        from flask import g, has_request_context
        from app.services.email_service import send_email

        tenant_nombre = ''
        url_mi = '/mi'
        if has_request_context():
            tenant = getattr(g, 'current_tenant', None)
            if tenant:
                tenant_nombre = tenant.nombre
                try:
                    from app.services.signup_service import url_acceso_tenant
                    url_mi = url_acceso_tenant(tenant, path='/mi')
                except Exception:
                    url_mi = '/mi'
        quien = ''
        if actor is not None:
            quien = f"{getattr(actor, 'name', '')} {getattr(actor, 'lastname', '')}".strip()

        asunto = f'Tu acceso de fichaje — {tenant_nombre or "SignaPlan"}'
        texto = (
            f'Hola {user.name},\n\n'
            f'Te han configurado el acceso de fichaje en SignaPlan'
            f'{f" ({tenant_nombre})" if tenant_nombre else ""}.\n\n'
            f'URL: {url_mi}\n'
            f'DNI: {user.dni}\n'
            f'PIN: {pin_plano}\n\n'
            f'Entra con tu DNI y este PIN.'
            f'{f" Te lo ha asignado {quien}." if quien else ""}\n'
        )
        html = (
            f'<p>Hola {user.name},</p>'
            f'<p>Te han configurado el acceso de fichaje'
            f'{f" en <strong>{tenant_nombre}</strong>" if tenant_nombre else ""}.</p>'
            f'<p><strong>URL:</strong> <a href="{url_mi}">{url_mi}</a><br>'
            f'<strong>DNI:</strong> {user.dni}<br>'
            f'<strong>PIN:</strong> {pin_plano}</p>'
            f'<p>Entra con tu DNI y este PIN.</p>'
        )
        return bool(send_email(asunto, [user.email], texto, html_body=html))
    except Exception:
        return False


def enviar_acceso_fichaje(user, pin_plano=None, *, actor=None, regenerar=False):
    """
    Prepara (o regenera) un PIN y lo envía por correo con la URL de /mi.
    Devuelve (ok_envio, pin_usado).
    """
    if user.role not in ROLES_CON_PIN:
        raise PinAuthError('Este perfil no usa PIN de fichaje.')
    pin = (pin_plano or '').strip()
    if pin:
        asignar_pin_explicito(user, pin, notify=False, actor=actor)
    elif regenerar or not user.pin_hash:
        _, pin = asignar_pin_generado(user, notify=False, actor=actor)
    else:
        raise PinAuthError(
            'No podemos reenviar el PIN actual (está cifrado). '
            'Indica un PIN nuevo o marca «Generar uno nuevo».'
        )
    ok = notificar_pin_por_email(user, pin, actor=actor)
    return ok, pin


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
    """
    user = buscar_por_dni(dni)
    if user is None or user.role not in ROLES_CON_PIN:
        raise PinAuthError('DNI o PIN incorrectos.')
    if not user.active:
        raise PinAuthError('Tu cuenta aún no está activa. Contacta con administración.')
    if not user.pin_hash:
        raise PinAuthError(
            'Todavía no tienes PIN. Pídeselo a administración de tu empresa.'
        )

    pin = (pin or '').strip()
    if not pin or not check_password_hash(user.pin_hash, pin):
        raise PinAuthError('DNI o PIN incorrectos.')

    return user
