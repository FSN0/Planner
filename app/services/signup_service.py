# app/services/signup_service.py
#
# Alta autoservicio desde signaplan.com/alta.
# 1) Reserva subdominio + datos (sin schema).
# 2) Correo con enlace en el host de marketing.
# 3) Al pulsar confirmar (POST) se crea el tenant ya verificado.

import re
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import current_app, has_request_context, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app import db, is_safe_schema_name
from app.models import SignupReservation, Tenant, User
from app.services.i18n_service import get_locale, marketing_path, normalize_locale, translate
from app.services.tenant_domain_service import _RESERVED_SUBDOMAINS
from app.services.tenant_service import provision_new_tenant

LEGAL_PRIVACIDAD_VERSION = '2026-08'
LEGAL_CONDICIONES_VERSION = '2026-08'

RESERVATION_TTL = timedelta(days=7)
CONFIRM_MAX_AGE = 86400 * 3
TICKET_MAX_AGE = 60 * 30
STALE_PROVISIONING = timedelta(minutes=3)

COOKIE_NAME = 'sp_signup_wait'
_SALT_CONFIRM = 'signaplan-signup-confirm'
_SALT_WAIT = 'signaplan-signup-wait'
_SALT_TICKET = 'signaplan-signup-ticket'

_SUBDOMINIOS_BLOQUEADOS = _RESERVED_SUBDOMAINS | frozenset({
    'alta', 'api', 'app', 'billing', 'cdn', 'docs', 'help', 'legal',
    'mail', 'status', 'support', 'www',
})

_SUB_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$')
_MOBILE_UA_RE = re.compile(
    r'mobile|iphone|ipod|android.*mobile|webos|blackberry|opera mini|opera mobi|iemobile',
    re.I,
)
_TABLET_UA_RE = re.compile(r'ipad|tablet|playbook|silk', re.I)

_LIVE_STATUSES = (
    SignupReservation.STATUS_PENDING,
    SignupReservation.STATUS_PROVISIONING,
    SignupReservation.STATUS_READY,
)


class SignupError(Exception):
    """Datos del formulario de alta incorrectos o enlace inválido."""


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
            translate(
                'El subdominio solo puede tener letras minúsculas, números y guiones '
                '(3–32 caracteres, sin empezar ni acabar en guion).'
            )
        )
    if subdominio in _SUBDOMINIOS_BLOQUEADOS:
        raise SignupError(translate('Ese subdominio está reservado. Elige otro.'))
    if len(subdominio) < 3:
        raise SignupError(translate('El subdominio tiene que tener al menos 3 caracteres.'))
    return subdominio


def validar_password(password, password2):
    password = password or ''
    if len(password) < 8:
        raise SignupError(translate('La contraseña tiene que tener al menos 8 caracteres.'))
    if password != (password2 or ''):
        raise SignupError(translate('Las contraseñas no coinciden.'))
    return password


def _serializer(salt):
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        raise SignupError(translate('SECRET_KEY no configurada.'))
    return URLSafeTimedSerializer(secret_key=secret, salt=salt)


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


def _expirar_reservas_caducadas(subdominio=None):
    ahora = datetime.utcnow()
    q = SignupReservation.query.filter(
        SignupReservation.status.in_((
            SignupReservation.STATUS_PENDING,
            SignupReservation.STATUS_PROVISIONING,
            SignupReservation.STATUS_FAILED,
        )),
        SignupReservation.expires_at < ahora,
    )
    if subdominio:
        q = q.filter_by(subdominio=subdominio)
    changed = False
    for reserva in q.all():
        reserva.status = SignupReservation.STATUS_EXPIRED
        reserva.updated_at = ahora
        changed = True
    if changed:
        db.session.commit()


def _subdominio_ocupado(subdominio):
    if Tenant.query.filter_by(subdominio=subdominio).first():
        return True
    _expirar_reservas_caducadas(subdominio)
    live = SignupReservation.query.filter(
        SignupReservation.subdominio == subdominio,
        SignupReservation.status.in_(_LIVE_STATUSES),
    ).first()
    return live is not None


def _url_confirmacion(token, locale=None):
    from app.services.seo_origin_service import marketing_url

    loc = normalize_locale(locale) or get_locale()
    path = marketing_path(f'/alta/confirmar?t={quote(token, safe="")}', loc)
    return marketing_url(path)


def generar_token_reserva(reserva):
    return _serializer(_SALT_CONFIRM).dumps({'rid': int(reserva.id)})


def leer_token_reserva(token):
    try:
        data = _serializer(_SALT_CONFIRM).loads(token, max_age=CONFIRM_MAX_AGE)
    except SignatureExpired as exc:
        raise SignupError(
            translate('El enlace de confirmación ha caducado. Solicita uno nuevo.')
        ) from exc
    except BadSignature as exc:
        raise SignupError(translate('El enlace de confirmación no es válido.')) from exc

    rid = int(data.get('rid') or 0)
    reserva = SignupReservation.query.get(rid) if rid else None
    if reserva is None:
        raise SignupError(translate('El enlace de confirmación no es válido.'))
    return reserva


def firmar_cookie_espera(reserva):
    return _serializer(_SALT_WAIT).dumps({'rid': int(reserva.id)})


def reserva_desde_cookie(value):
    if not value:
        return None
    try:
        data = _serializer(_SALT_WAIT).loads(value, max_age=int(RESERVATION_TTL.total_seconds()))
    except (BadSignature, SignatureExpired):
        return None
    rid = int(data.get('rid') or 0)
    return SignupReservation.query.get(rid) if rid else None


def es_cliente_movil(user_agent=None, ch_ua_mobile=None):
    """True si el enlace se abrió en un teléfono (no tablet ni escritorio)."""
    if has_request_context():
        if user_agent is None:
            user_agent = request.headers.get('User-Agent')
        if ch_ua_mobile is None:
            ch_ua_mobile = request.headers.get('Sec-CH-UA-Mobile')
    ch = (ch_ua_mobile or '').strip()
    if ch == '?1':
        return True
    if ch == '?0':
        return False
    ua = user_agent or ''
    if _TABLET_UA_RE.search(ua):
        return False
    return bool(_MOBILE_UA_RE.search(ua))


def attach_wait_cookie(response, reserva):
    secure = bool(current_app.config.get('SESSION_COOKIE_SECURE'))
    response.set_cookie(
        COOKIE_NAME,
        firmar_cookie_espera(reserva),
        max_age=int(RESERVATION_TTL.total_seconds()),
        httponly=True,
        samesite='Lax',
        secure=secure,
        path='/',
    )
    return response


def generar_ticket_acceso(reserva, tenant):
    admin = _admin_del_tenant(tenant, reserva.admin_email)
    if admin is None:
        raise SignupError(translate('No se ha podido abrir la sesión. Entra con tu correo y contraseña.'))
    return _serializer(_SALT_TICKET).dumps({
        'rid': int(reserva.id),
        'tid': int(tenant.id),
        'uid': int(admin.id),
    })


def leer_ticket_acceso(token, tenant):
    try:
        data = _serializer(_SALT_TICKET).loads(token, max_age=TICKET_MAX_AGE)
    except SignatureExpired as exc:
        raise SignupError(
            translate('El enlace de acceso ha caducado. Entra con tu correo y contraseña.')
        ) from exc
    except BadSignature as exc:
        raise SignupError(translate('El enlace de acceso no es válido.')) from exc

    if int(data.get('tid') or 0) != int(tenant.id):
        raise SignupError(translate('Este enlace no corresponde a esta empresa.'))
    reserva = SignupReservation.query.get(int(data.get('rid') or 0))
    if reserva is None or reserva.status != SignupReservation.STATUS_READY:
        raise SignupError(translate('El enlace de acceso no es válido.'))
    return int(data['uid'])


def url_ticket_tenant(reserva, tenant):
    token = generar_ticket_acceso(reserva, tenant)
    return url_acceso_tenant(tenant, path=f'/auth/ticket?t={quote(token, safe="")}')


def enviar_email_confirmacion(reserva):
    token = generar_token_reserva(reserva)
    url = _url_confirmacion(token, reserva.locale)
    loc = normalize_locale(reserva.locale) or get_locale()
    nombre = reserva.nombre_empresa
    sub = reserva.subdominio
    texto = translate(
        'Hola,\n\n'
        'Confirma tu correo para crear el espacio SignaPlan de {tenant} '
        '({subdominio}):\n\n{url}\n\n'
        'Hasta que confirmes, el espacio no se crea. El enlace caduca en 3 días. '
        'Si no has pedido esta cuenta, ignora este mensaje.\n',
        loc,
        tenant=nombre,
        subdominio=sub,
        url=url,
    )
    html = translate(
        '<p>Hola,</p>'
        '<p>Confirma tu correo para crear el espacio <strong>SignaPlan</strong> '
        'de {tenant} ({subdominio}).</p>'
        '<p><a href="{url}">Confirmar y crear mi espacio</a></p>'
        '<p>Hasta que confirmes, el espacio no se crea. El enlace caduca en 3 días. '
        'Si no has pedido esta cuenta, ignora este mensaje.</p>',
        loc,
        tenant=nombre,
        subdominio=sub,
        url=url,
    )
    from app.services.email_service import send_email
    from app.services.notification_dispatch_service import event_allows_send
    if not event_allows_send('signup_confirm'):
        return False
    return bool(send_email(
        translate('Confirma tu correo — {tenant}', loc, tenant=nombre),
        [reserva.admin_email],
        texto,
        html_body=html,
    ))


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
    Reserva el subdominio y envía el correo de confirmación.
    No crea el tenant hasta que el usuario pulsa confirmar.

    Devuelve (reserva, email_enviado).
    """
    nombre_empresa = (nombre_empresa or '').strip()
    admin_email = (admin_email or '').strip().lower()

    if not nombre_empresa or len(nombre_empresa) < 2:
        raise SignupError(translate('Indica el nombre de la empresa.'))
    if not admin_email or '@' not in admin_email:
        raise SignupError(translate('Indica un correo válido para el administrador.'))
    if not acepta_privacidad or not acepta_condiciones:
        raise SignupError(translate('Debes aceptar la política de privacidad y las condiciones.'))

    subdominio = validar_subdominio(subdominio)
    password = validar_password(admin_password, admin_password2)

    db.session.execute(text('SET search_path TO public'))
    if _subdominio_ocupado(subdominio):
        raise SignupError(
            translate("El subdominio '{subdominio}' ya está en uso.", subdominio=subdominio)
        )

    ahora = datetime.utcnow()
    reserva = SignupReservation(
        subdominio=subdominio,
        nombre_empresa=nombre_empresa,
        admin_email=admin_email,
        password_hash=generate_password_hash(password),
        locale=normalize_locale(get_locale()),
        legal_privacidad_version=LEGAL_PRIVACIDAD_VERSION,
        legal_condiciones_version=LEGAL_CONDICIONES_VERSION,
        status=SignupReservation.STATUS_PENDING,
        created_at=ahora,
        updated_at=ahora,
        expires_at=ahora + RESERVATION_TTL,
    )
    db.session.add(reserva)
    db.session.commit()

    email_enviado = bool(enviar_email_confirmacion(reserva))
    return reserva, email_enviado


def reenviar_confirmacion(email, subdominio):
    """Reenvía el correo de una reserva pendiente. No delata si no existe."""
    email = (email or '').strip().lower()
    subdominio = (subdominio or '').strip().lower()
    if not email or not subdominio:
        return False
    db.session.execute(text('SET search_path TO public'))
    _expirar_reservas_caducadas(subdominio)
    reserva = (
        SignupReservation.query
        .filter_by(admin_email=email, subdominio=subdominio)
        .order_by(SignupReservation.id.desc())
        .first()
    )
    if reserva is None:
        return False
    if reserva.status not in (
        SignupReservation.STATUS_PENDING,
        SignupReservation.STATUS_FAILED,
    ):
        return False
    if reserva.expires_at and reserva.expires_at < datetime.utcnow():
        reserva.status = SignupReservation.STATUS_EXPIRED
        db.session.commit()
        return False
    return bool(enviar_email_confirmacion(reserva))


def reenviar_reservas_por_email(email):
    """Reenvía confirmaciones pendientes de ese correo (flujo /entrar)."""
    email = (email or '').strip().lower()
    if not email:
        return False
    db.session.execute(text('SET search_path TO public'))
    _expirar_reservas_caducadas()
    reservas = SignupReservation.query.filter(
        SignupReservation.admin_email == email,
        SignupReservation.status.in_((
            SignupReservation.STATUS_PENDING,
            SignupReservation.STATUS_FAILED,
        )),
    ).all()
    enviado = False
    for reserva in reservas:
        if reserva.expires_at and reserva.expires_at < datetime.utcnow():
            continue
        if enviar_email_confirmacion(reserva):
            enviado = True
    return enviado


def _rollback_tenant_half(subdominio):
    schema_name = f"tenant_{subdominio.replace('-', '_')}"
    try:
        db.session.rollback()
    except Exception:
        pass
    try:
        db.session.execute(text('SET search_path TO public'))
        tenant = Tenant.query.filter_by(subdominio=subdominio).first()
        if tenant is not None:
            db.session.delete(tenant)
            db.session.commit()
        if is_safe_schema_name(schema_name):
            db.session.execute(text(f'DROP SCHEMA IF EXISTS {schema_name} CASCADE'))
            db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _tenant_de_reserva(reserva):
    if not reserva.tenant_id:
        return Tenant.query.filter_by(subdominio=reserva.subdominio).first()
    return Tenant.query.get(reserva.tenant_id)


def estado_reserva(reserva):
    """Estado para el poll de la pestaña de espera."""
    if reserva is None:
        return {'status': 'unknown'}
    _expirar_reservas_caducadas(reserva.subdominio)
    db.session.refresh(reserva)
    if reserva.status == SignupReservation.STATUS_EXPIRED:
        return {'status': 'expired'}
    if reserva.status == SignupReservation.STATUS_FAILED:
        return {'status': 'failed'}
    if reserva.status == SignupReservation.STATUS_READY:
        tenant = _tenant_de_reserva(reserva)
        if tenant is None:
            return {'status': 'failed'}
        return {
            'status': 'ready',
            'ticket_url': url_ticket_tenant(reserva, tenant),
            'subdomain': tenant.subdominio,
        }
    if reserva.status == SignupReservation.STATUS_PROVISIONING:
        return {'status': 'creating'}
    return {'status': 'pending'}


def inspeccionar_reserva(token):
    """GET del enlace: no provisiona (Outlook Safe Links)."""
    reserva = leer_token_reserva(token)
    _expirar_reservas_caducadas(reserva.subdominio)
    db.session.refresh(reserva)
    if reserva.expires_at and reserva.expires_at < datetime.utcnow():
        reserva.status = SignupReservation.STATUS_EXPIRED
        db.session.commit()
        raise SignupError(
            translate('El enlace de confirmación ha caducado. Solicita uno nuevo.')
        )
    return reserva


def confirmar_reserva(token):
    """
    POST del botón de confirmar: crea el tenant (idempotente).
    Devuelve (reserva, tenant). tenant es None si aún está provisionando.
    """
    reserva = leer_token_reserva(token)
    db.session.execute(text('SET search_path TO public'))
    reserva = (
        SignupReservation.query
        .filter_by(id=reserva.id)
        .with_for_update()
        .first()
    )
    if reserva is None:
        raise SignupError(translate('El enlace de confirmación no es válido.'))

    ahora = datetime.utcnow()
    if reserva.expires_at and reserva.expires_at < ahora:
        reserva.status = SignupReservation.STATUS_EXPIRED
        reserva.updated_at = ahora
        db.session.commit()
        raise SignupError(
            translate('El enlace de confirmación ha caducado. Solicita uno nuevo.')
        )

    if reserva.status == SignupReservation.STATUS_READY:
        tenant = _tenant_de_reserva(reserva)
        if tenant is not None:
            db.session.commit()
            return reserva, tenant
        reserva.status = SignupReservation.STATUS_PENDING

    if reserva.status == SignupReservation.STATUS_PROVISIONING:
        updated = reserva.updated_at or reserva.created_at or ahora
        if ahora - updated < STALE_PROVISIONING:
            db.session.commit()
            return reserva, None
        reserva.status = SignupReservation.STATUS_PENDING

    reserva.status = SignupReservation.STATUS_PROVISIONING
    reserva.updated_at = ahora
    reserva.error_message = None
    reserva_id = reserva.id
    subdominio = reserva.subdominio
    nombre_empresa = reserva.nombre_empresa
    admin_email = reserva.admin_email
    password_hash = reserva.password_hash
    locale = reserva.locale
    legal_priv = reserva.legal_privacidad_version
    legal_cond = reserva.legal_condiciones_version
    db.session.commit()

    try:
        tenant = provision_new_tenant(
            nombre_empresa,
            subdominio,
            admin_email,
            None,
            modulos_activos={
                'fichaje_operario': True,
                'registro_jornada': True,
                'onboarding': True,
                'notas': False,
                'auditoria_vehiculos': False,
            },
            email_verified=True,
            active=True,
            password_hash=password_hash,
            locale=locale,
        )
        db.session.execute(text('SET search_path TO public'))
        reserva = SignupReservation.query.get(reserva_id)
        tenant = db.session.query(Tenant).get(tenant.id)
        tenant.legal_aceptado_at = datetime.utcnow()
        tenant.legal_privacidad_version = legal_priv
        tenant.legal_condiciones_version = legal_cond
        reserva.status = SignupReservation.STATUS_READY
        reserva.tenant_id = tenant.id
        reserva.updated_at = datetime.utcnow()
        db.session.commit()
        return reserva, tenant
    except SignupError:
        raise
    except Exception as exc:
        try:
            db.session.execute(text('SET search_path TO public'))
        except Exception:
            pass
        existing = Tenant.query.filter_by(subdominio=subdominio).first()
        if existing is not None:
            admin = _admin_del_tenant(existing, admin_email)
            if admin is not None:
                reserva = SignupReservation.query.get(reserva_id)
                if reserva is not None:
                    reserva.status = SignupReservation.STATUS_READY
                    reserva.tenant_id = existing.id
                    reserva.updated_at = datetime.utcnow()
                    reserva.error_message = None
                    db.session.commit()
                return reserva, existing
        _rollback_tenant_half(subdominio)
        try:
            db.session.execute(text('SET search_path TO public'))
            reserva = SignupReservation.query.get(reserva_id)
            if reserva is not None:
                reserva.status = SignupReservation.STATUS_FAILED
                reserva.error_message = (str(exc) or '')[:250]
                reserva.updated_at = datetime.utcnow()
                db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        raise SignupError(
            translate(
                'No se ha podido crear el espacio. Prueba de nuevo o contacta con soporte.'
            )
        ) from exc


def url_acceso_tenant(tenant, path='/auth/login'):
    """URL del espacio del cliente (subdominio SignaPlan o *.localhost en dev)."""
    from app.services.tenant_domain_service import normalize_host

    if has_request_context() and request.host:
        host = normalize_host(request.host)
        port = ''
        if ':' in request.host:
            port = ':' + request.host.rsplit(':', 1)[1]
        if host in ('localhost', '127.0.0.1', 'web') or host.endswith('.localhost'):
            scheme = request.scheme or 'http'
            return f'{scheme}://{tenant.subdominio}.localhost{port}{path}'

    base = (current_app.config.get('SIGNAPLAN_BASE_DOMAIN') or 'signaplan.com').strip()
    return f'https://{tenant.subdominio}.{base}{path}'
