"""Suplantación de sesión («Entrar como») para probar la app como otro usuario."""
from __future__ import annotations

from flask import session
from flask_login import current_user, login_user

from app.models import ROLE_ADMIN, User
from app.services.permission_service import user_can

SESSION_IMPERSONATOR_KEY = 'impersonator_user_id'
SESSION_IMPERSONATED_USER_KEY = 'impersonated_user_id'


def impersonacion_activa() -> bool:
    return bool(session.get(SESSION_IMPERSONATOR_KEY))


def impersonador_id() -> int | None:
    raw = session.get(SESSION_IMPERSONATOR_KEY)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def impersonado_id() -> int | None:
    raw = session.get(SESSION_IMPERSONATED_USER_KEY)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def impersonador_label() -> str | None:
    imp_id = impersonador_id()
    if not imp_id:
        return None
    admin = User.query.filter_by(id=imp_id, is_deleted=False).first()
    if not admin:
        return None
    return f'{admin.name} {admin.lastname}'.strip()


def _limpiar_claves_remember():
    session.pop('_remember', None)


def clear_remember_cookie(response):
    """Caduca la cookie remember_token (logout y suplantación).

    Flask-Login 0.5.0 lee el nombre de app.config, no de LoginManager.
    Si el atributo no existe, un getattr() deja la cookie viva y el
    siguiente request vuelve a autenticar al usuario.
    """
    from flask import current_app

    config = current_app.config
    name = config.get('REMEMBER_COOKIE_NAME') or 'remember_token'
    domain = config.get('REMEMBER_COOKIE_DOMAIN')
    path = config.get('REMEMBER_COOKIE_PATH') or '/'
    # Mismos flags con los que se emitió la cookie: si no coinciden,
    # Chrome/Safari en HTTPS no la sustituyen y la sesión «revive».
    response.set_cookie(
        name,
        value='',
        expires=0,
        max_age=0,
        domain=domain,
        path=path,
        secure=bool(config.get('REMEMBER_COOKIE_SECURE')),
        httponly=bool(config.get('REMEMBER_COOKIE_HTTPONLY', True)),
    )
    return response


def admin_puede_impersonar(actor) -> bool:
    """True si el actor tiene el permiso «entrar_como» y no hay otra suplantación."""
    if not user_can(actor, 'entrar_como', 'r'):
        return False
    # No anidar: si ya estás dentro de otra sesión, no abrir una segunda.
    if impersonacion_activa():
        return False
    return True


def puede_ser_impersonado(target, actor) -> bool:
    if not target or target.is_deleted or not target.is_active:
        return False
    if target.id == getattr(actor, 'id', None):
        return False
    if target.role == ROLE_ADMIN:
        return False
    return True


def iniciar_impersonacion(actor, target):
    """Devuelve (ok, mensaje_error)."""
    if not admin_puede_impersonar(actor):
        return False, 'No tienes permiso para entrar como otro usuario.'
    if not puede_ser_impersonado(target, actor):
        return False, 'No se puede entrar como ese usuario.'

    _limpiar_claves_remember()
    session[SESSION_IMPERSONATOR_KEY] = actor.id
    session[SESSION_IMPERSONATED_USER_KEY] = target.id
    login_user(target, remember=False, force=True)
    session.modified = True
    return True, None


def reparar_sesion_impersonacion() -> bool:
    """
    Si la sesión volvió al administrador (p. ej. cookie remember me),
    restaura al usuario suplantado mientras impersonacion_activa.
    """
    if not impersonacion_activa():
        return False
    if not getattr(current_user, 'is_authenticated', False):
        return False

    target_id = impersonado_id()
    imp_id = impersonador_id()
    if not target_id or not imp_id:
        return False
    if current_user.id == target_id:
        return False
    if current_user.id != imp_id:
        return False

    target = User.query.filter_by(id=target_id, is_deleted=False, active=True).first()
    if not target:
        return False

    _limpiar_claves_remember()
    login_user(target, remember=False, force=True)
    session.modified = True
    return True


def detener_impersonacion():
    """Vuelve a la cuenta del administrador. Devuelve User o None."""
    imp_id = impersonador_id()
    if not imp_id:
        return None
    admin = User.query.filter_by(id=imp_id, is_deleted=False, active=True).first()
    session.pop(SESSION_IMPERSONATOR_KEY, None)
    session.pop(SESSION_IMPERSONATED_USER_KEY, None)
    _limpiar_claves_remember()
    if admin:
        login_user(admin, remember=False, force=True)
        session.modified = True
    return admin
