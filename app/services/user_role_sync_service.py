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


def apply_odoo_role_if_allowed(user, odoo_role: str) -> bool:
    """
    Aplica el rol derivado de Odoo si no hay bloqueo manual.
    Devuelve True si se aplicó.
    """
    if user_role_sync_locked(user):
        return False
    user.role = odoo_role
    return True
