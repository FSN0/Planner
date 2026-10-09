"""Protección de rol manual frente a sincronización Odoo."""
from __future__ import annotations

ROLE_MANUAL_KEY = 'role_manual'


def user_role_sync_locked(user) -> bool:
    ext = user.external_ids if isinstance(getattr(user, 'external_ids', None), dict) else {}
    return bool(ext.get(ROLE_MANUAL_KEY))


def lock_user_role_manual(user) -> None:
    """Marca el rol como fijado manualmente (no lo pisa la sync Odoo)."""
    ext = dict(user.external_ids or {})
    ext[ROLE_MANUAL_KEY] = True
    user.external_ids = ext


def clear_user_role_manual(user) -> None:
    ext = dict(user.external_ids or {})
    ext.pop(ROLE_MANUAL_KEY, None)
    user.external_ids = ext


def apply_subcontrata_portal_role(user, odoo_role: str, *, force: bool = False) -> bool:
    """Pasa entre operario y admin de subcontrata según la etiqueta de Odoo.

    No toca otros roles ni una ficha en contratación. Un rol fijado a mano
    no se pisa en sync automática; con force=True (commit manual del preview)
    sí se aplica y se quita el bloqueo.
    """
    from app.models import ROLE_ADMIN_SUBCONTRATA, ROLE_OPERARIO

    if user_role_sync_locked(user) and not force:
        return False
    if getattr(user, 'hiring_state', None):
        return False
    if odoo_role not in (ROLE_OPERARIO, ROLE_ADMIN_SUBCONTRATA):
        return False
    if user.role not in (ROLE_OPERARIO, ROLE_ADMIN_SUBCONTRATA):
        return False
    if user.role == odoo_role:
        return False
    if force and user_role_sync_locked(user):
        clear_user_role_manual(user)
    user.role = odoo_role
    return True


def apply_odoo_role_if_allowed(user, odoo_role: str) -> bool:
    """
    Aplica el rol derivado de Odoo si no hay bloqueo manual.
    Devuelve True si se aplicó.
    """
    if user_role_sync_locked(user):
        return False
    user.role = odoo_role
    return True
