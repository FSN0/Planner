# app/services/signup_service.py
#
# Alta autoservicio: una empresa se crea su propio tenant desde signaplan.com/alta.
# Reutiliza provision_new_tenant; añade validaciones de producto (reservados,
# contraseña mínima, aceptación legal) y deja la cuenta pendiente de verificar correo.

import re
import unicodedata
from datetime import datetime

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import text

from app import db
from app.models import User
from app.services.tenant_domain_service import _RESERVED_SUBDOMAINS
from app.services.tenant_service import provision_new_tenant

# Versiones publicadas de los textos legales (coinciden con /legal).
LEGAL_PRIVACIDAD_VERSION = '2026-08'
LEGAL_CONDICIONES_VERSION = '2026-08'

# Subdominios que no debe poder registrar un cliente.
_SUBDOMINIOS_BLOQUEADOS = _RESERVED_SUBDOMAINS | frozenset({
    'alta', 'api', 'app', 'billing', 'cdn', 'docs', 'help', 'legal',
    'mail', 'status', 'support', 'www',
})

_SUB_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$')
_ENTRADA_SALT = 'signaplan-signup-auto-login'
_ENTRADA_MAX_AGE = 600  # 10 minutos para completar el salto de host


class SignupError(Exception):
    """Datos del formulario de alta incorrectos."""


def sugerir_subdominio(nombre_empresa):
    """
    Convierte «Construcciones López» → construcciones-lopez.
    Solo una sugerencia de UI; el usuario puede editarla.
    """
    texto = unicodedata.normalize('NFKD', nombre_empresa or '')
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r'[^a-z0-9]+', '-', texto).strip('-')
    texto = re.sub(r'-{2,}', '-', texto)
    if len(texto) > 32:
        texto = texto[:32].rstrip('-')
    return texto


def validar_subdominio(subdominio):
    subdominio = (subdominio or '').lower().strip()
    if not _SUB_RE.match(subdominio):
        raise SignupError(
            'El subdominio solo puede tener letras minúsculas, números y guiones '
            '(3–32 caracteres, sin empezar ni acabar en guion).'
        )
    if subdominio in _SUBDOMINIOS_BLOQUEADOS:
        raise SignupError('Ese subdominio está reservado. Elige otro.')
    if len(subdominio) < 3:
        raise SignupError('El subdominio tiene que tener al menos 3 caracteres.')
    return subdominio


def validar_password(password, password2):
    password = password or ''
    if len(password) < 8:
        raise SignupError('La contraseña tiene que tener al menos 8 caracteres.')
    if password != (password2 or ''):
        raise SignupError('Las contraseñas no coinciden.')
    return password


def _admin_del_tenant(tenant, admin_email):
    """Localiza el admin recién creado en el esquema del tenant."""
    db.session.execute(text(f'SET search_path TO {tenant.schema_name}'))
    try:
        return User.query.filter_by(
            email=(admin_email or '').strip().lower(),
            is_deleted=False,
        ).first()
    finally:
        db.session.execute(text('SET search_path TO public'))


def registrar_empresa(
    *,
    nombre_empresa,
    subdominio,
    admin_email,
    admin_password,
    admin_password2,
    acepta_privacidad,
    acepta_condiciones,
):
    """
    Crea el tenant en plan free, guarda el consentimiento legal y deja al
    admin inactivo hasta verificar el correo.

    Devuelve (tenant, email_enviado).
    """
    nombre_empresa = (nombre_empresa or '').strip()
    admin_email = (admin_email or '').strip().lower()

    if not nombre_empresa or len(nombre_empresa) < 2:
        raise SignupError('Indica el nombre de la empresa.')
    if not admin_email or '@' not in admin_email:
        raise SignupError('Indica un correo válido para el administrador.')
    if not acepta_privacidad or not acepta_condiciones:
        raise SignupError('Debes aceptar la política de privacidad y las condiciones.')

    subdominio = validar_subdominio(subdominio)
    password = validar_password(admin_password, admin_password2)

    try:
        tenant = provision_new_tenant(
            nombre_empresa,
            subdominio,
            admin_email,
            password,
            modulos_activos={
                'fichaje_operario': True,
                'registro_jornada': True,
                'onboarding': True,
            },
            email_verified=False,
            active=False,
        )
    except ValueError as exc:
        raise SignupError(str(exc)) from exc

    # Consentimiento: qué versiones aceptó y cuándo (UTC).
    db.session.execute(text('SET search_path TO public'))
    tenant.legal_aceptado_at = datetime.utcnow()
    tenant.legal_privacidad_version = LEGAL_PRIVACIDAD_VERSION
    tenant.legal_condiciones_version = LEGAL_CONDICIONES_VERSION
    db.session.commit()

    admin = _admin_del_tenant(tenant, admin_email)
    email_enviado = False
    if admin is not None:
        from app.services.email_verification_service import enviar_email_verificacion
        email_enviado = bool(enviar_email_verificacion(tenant, admin))

    return tenant, email_enviado


def url_acceso_tenant(tenant, path='/auth/login'):
    """URL del espacio del cliente (subdominio SignaPlan o *.localhost en dev)."""
    from flask import current_app, has_request_context, request

    from app.services.tenant_domain_service import normalize_host

    if has_request_context() and request.host:
        host = normalize_host(request.host)
        port = ''
        if ':' in request.host:
            port = ':' + request.host.rsplit(':', 1)[1]
        # Dev: soltec.localhost:5000
        if host in ('localhost', '127.0.0.1', 'web') or host.endswith('.localhost'):
            scheme = request.scheme or 'http'
            return f'{scheme}://{tenant.subdominio}.localhost{port}{path}'

    base = (current_app.config.get('SIGNAPLAN_BASE_DOMAIN') or 'signaplan.com').strip()
    return f'https://{tenant.subdominio}.{base}{path}'


def _entrada_serializer():
    from flask import current_app
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        raise SignupError('SECRET_KEY no configurada.')
    return URLSafeTimedSerializer(secret_key=secret, salt=_ENTRADA_SALT)


def crear_token_entrada_post_alta(tenant, admin_email):
    """
    Token de corta vida para entrar en el subdominio del tenant sin
    volver a pedir usuario/contraseña.

    Hace falta porque la cookie de sesión de localhost no sirve en
    paquito.localhost: son hosts distintos.
    """
    return _entrada_serializer().dumps({
        'tid': tenant.id,
        'sub': tenant.subdominio,
        'email': (admin_email or '').strip().lower(),
    })


def leer_token_entrada_post_alta(token, tenant_esperado):
    """Devuelve el email del admin si el token es válido para este tenant."""
    try:
        data = _entrada_serializer().loads(token, max_age=_ENTRADA_MAX_AGE)
    except SignatureExpired as exc:
        raise SignupError(
            'El enlace de acceso ha caducado. Entra con tu correo y contraseña.'
        ) from exc
    except BadSignature as exc:
        raise SignupError('El enlace de acceso no es válido.') from exc

    if int(data.get('tid') or 0) != int(tenant_esperado.id):
        raise SignupError('El enlace no corresponde a este espacio.')
    if (data.get('sub') or '') != tenant_esperado.subdominio:
        raise SignupError('El enlace no corresponde a este espacio.')
    email = (data.get('email') or '').strip().lower()
    if not email:
        raise SignupError('El enlace de acceso no es válido.')
    return email


def url_entrada_automatica(tenant, admin_email):
    """URL completa al subdominio con token de entrada automática."""
    from urllib.parse import quote
    token = crear_token_entrada_post_alta(tenant, admin_email)
    return url_acceso_tenant(
        tenant, path=f'/auth/entrar-alta?t={quote(token, safe="")}'
    )
