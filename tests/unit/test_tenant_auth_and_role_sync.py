"""Tests de política PIN/contraseña y bloqueo de rol en sync Odoo."""
import pytest

from app.models import User
from app.services.auth_login_service import default_auth_mode_for_role
from app.services.tenant_auth_policy import tenant_usa_acceso_pin
from app.services.user_role_sync_service import (
    apply_odoo_role_if_allowed,
    lock_user_role_manual,
    user_role_sync_locked,
)


def test_default_auth_mode_password_when_pin_disabled(app):
    from unittest.mock import patch
    with app.app_context():
        with patch('app.services.auth_login_service.tenant_usa_acceso_pin', return_value=False):
            assert default_auth_mode_for_role('operario') == 'password'


def test_user_role_sync_locked_flag():
    user = User(role='laboral', external_ids={'odoo': '1'})
    assert not user_role_sync_locked(user)
    lock_user_role_manual(user)
    assert user_role_sync_locked(user)
    assert user.external_ids.get('role_manual') is True


def test_apply_odoo_role_respects_manual_lock():
    user = User(role='laboral', external_ids={'odoo': '1', 'role_manual': True})
    assert apply_odoo_role_if_allowed(user, 'operario') is False
    assert user.role == 'laboral'


def test_apply_odoo_role_updates_when_unlocked():
    user = User(role='operario', external_ids={'odoo': '1'})
    assert apply_odoo_role_if_allowed(user, 'jefe_obra') is True
    assert user.role == 'jefe_obra'


def test_apply_subcontrata_portal_role_force_clears_manual_lock():
    from app.services.user_role_sync_service import apply_subcontrata_portal_role

    user = User(role='operario', external_ids={'odoo': '1', 'role_manual': True})
    assert apply_subcontrata_portal_role(user, 'admin_subcontrata') is False
    assert user.role == 'operario'
    assert apply_subcontrata_portal_role(user, 'admin_subcontrata', force=True) is True
    assert user.role == 'admin_subcontrata'
    assert not user.external_ids.get('role_manual')
