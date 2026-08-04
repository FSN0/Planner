# app/services/pin_auth_service.py
#
# Acceso del trabajador a la PWA con DNI y PIN numérico.
#
# En obra el correo y la contraseña fallan: el teclado pone mayúsculas, nadie
# recuerda un email corporativo y las cuentas importadas del ERP suelen tener
# una contraseña genérica. Un PIN de cuatro a seis cifras, puesto por
# administración, es lo que realmente se usa.

import re

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


def asignar_pin(user, pin):
    """Guarda el hash del PIN. No hace commit."""
    if user.role not in ROLES_CON_PIN:
        raise PinAuthError('Este perfil no usa PIN de fichaje.')
    pin = validar_pin(pin)
    user.pin_hash = generate_password_hash(pin)
    return user


def quitar_pin(user):
    """Deja al trabajador sin acceso por PIN hasta que le pongan otro."""
    user.pin_hash = None
    return user


def tiene_pin(user):
    return bool(user and user.pin_hash)


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
