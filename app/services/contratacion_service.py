"""Alta en contratación: entra al portal, pero no al cuadrante hasta finalizar."""
from __future__ import annotations

import secrets
from datetime import date

from werkzeug.security import generate_password_hash

from app import db
from app.models import ROLE_OPERARIO, Company, User
from app.services.compliance_rules import email_es_real
from app.services.documentacion_service import fase1_completa, puede_finalizar
from app.utils.timezone_utils import today_local


def _dni_placeholder() -> str:
    return f'PEND-{secrets.token_hex(4).upper()}'


def _email_placeholder() -> str:
    return f'c{secrets.token_hex(6)}@pending.local'


def empresa_interna() -> Company | None:
    return Company.query.filter_by(is_internal=True, active=True).order_by(Company.id.asc()).first()


def asegurar_empresa_interna(user: User) -> bool:
    """Las altas son personal propio: sin empresa → empresa interna."""
    if user.company_id:
        return False
    interna = empresa_interna()
    if not interna:
        return False
    user.company_id = interna.id
    return True


def crear(*, nombre: str, apellido: str = '', email: str = '', role: str = ROLE_OPERARIO, company_id=None) -> User:
    nombre = (nombre or '').strip()
    if not nombre:
        raise ValueError('Hace falta al menos el nombre para encontrarle luego.')
    role = (role or ROLE_OPERARIO).strip() or ROLE_OPERARIO
    email_limpio = (email or '').strip().lower()
    if email_limpio and not email_es_real(email_limpio):
        raise ValueError('Ese correo no sirve como acceso. Escribe uno real.')
    if email_limpio and User.query.filter_by(email=email_limpio).first():
        raise ValueError('Ese correo ya está usado.')
    if not company_id:
        interna = empresa_interna()
        company_id = interna.id if interna else None
    user = User(
        name=nombre,
        lastname=(apellido or '').strip(),
        email=email_limpio or _email_placeholder(),
        dni=_dni_placeholder(),
        role=role,
        company_id=company_id,
        active=True,
        email_verified=True,
        web_access=True,
        auth_mode='password',
        visible_en_cuadrante=False,
        hiring_state='contratacion',
        password_hash=generate_password_hash(secrets.token_urlsafe(24)),
        firma_contrato_estado='pendiente',
    )
    db.session.add(user)
    db.session.flush()
    return user


def actualizar_perfil(user: User, datos: dict) -> None:
    nombre = (datos.get('name') or '').strip()
    if nombre:
        user.name = nombre
    if 'lastname' in datos:
        user.lastname = (datos.get('lastname') or '').strip()
    if 'telefono' in datos:
        user.telefono = (datos.get('telefono') or '').strip() or None
    if 'talla_ropa' in datos:
        user.talla_ropa = (datos.get('talla_ropa') or '').strip() or None
    if 'numero_cuenta' in datos:
        user.numero_cuenta = (datos.get('numero_cuenta') or '').strip() or None
    dni = (datos.get('dni') or '').strip().upper()
    if dni and not dni.startswith('PEND-'):
        company = user.company_rel
        nif_empresa = ''.join(ch for ch in (getattr(company, 'nif', None) or '').upper() if ch.isalnum())
        dni_limpio = ''.join(ch for ch in dni if ch.isalnum())
        if nif_empresa and dni_limpio == nif_empresa:
            raise ValueError('El DNI no puede ser el NIF de la empresa.')
        choque = User.query.filter(User.dni == dni, User.id != user.id).first()
        if choque:
            raise ValueError('Ese DNI ya está en otra ficha.')
        user.dni = dni
    email = (datos.get('email') or '').strip().lower()
    if email:
        if not email_es_real(email):
            raise ValueError('Escribe un correo real.')
        choque = User.query.filter(User.email == email, User.id != user.id).first()
        if choque:
            raise ValueError('Ese correo ya está usado.')
        user.email = email


def refrescar_fase(user: User) -> None:
    if not user.hiring_state:
        return
    if fase1_completa(user):
        if user.hiring_state == 'contratacion':
            user.hiring_state = 'fase2'
    elif user.hiring_state == 'fase2':
        # Si aún faltan validaciones de fase 1, no debe figurar como fase 2.
        user.hiring_state = 'contratacion'


def finalizar(user: User, fecha_inicio: date | None = None) -> None:
    if not user.hiring_state:
        return
    refrescar_fase(user)
    if not puede_finalizar(user):
        raise ValueError(
            'Falta documentación obligatoria de la fase 1 o de la fase 2 (art. 19 / reconocimiento).'
        )
    asegurar_empresa_interna(user)
    user.fecha_inicio = fecha_inicio or user.fecha_inicio or today_local()
    user.hiring_state = None
    user.active = True
    if user.role in ('operario', 'admin_subcontrata'):
        user.visible_en_cuadrante = True
