"""Tests de suplantación de sesión por administrador."""
from types import SimpleNamespace

import pytest

from app.services.impersonation_service import (
    puede_ser_impersonado,
    admin_puede_impersonar,
    SESSION_IMPERSONATOR_KEY,
)


def test_admin_puede_impersonar_si_no_hay_sesion_activa(app):
    admin = SimpleNamespace(is_authenticated=True, role='admin', id=1)
    with app.test_request_context():
        assert admin_puede_impersonar(admin) is True


def test_admin_puede_impersonar_tras_entrada_superadmin(app):
    admin = SimpleNamespace(is_authenticated=True, role='admin', id=1)
    with app.test_request_context() as ctx:
        ctx.session['superadmin_impersonation'] = True
        assert admin_puede_impersonar(admin) is True


def test_no_impersonar_si_ya_hay_suplantacion_activa(app):
    admin = SimpleNamespace(is_authenticated=True, role='admin', id=1)
    with app.test_request_context() as ctx:
        ctx.session[SESSION_IMPERSONATOR_KEY] = admin.id
        ctx.session['impersonated_user_id'] = 99
        assert admin_puede_impersonar(admin) is False


def test_no_impersonar_admin_ni_a_si_mismo():
    actor = SimpleNamespace(is_authenticated=True, role='admin', id=1)
    otro_admin = SimpleNamespace(is_authenticated=True, role='admin', id=2, is_deleted=False, is_active=True)
    assert puede_ser_impersonado(otro_admin, actor) is False
    assert puede_ser_impersonado(actor, actor) is False


def test_jefe_puede_ser_impersonado():
    actor = SimpleNamespace(is_authenticated=True, role='admin', id=1)
    jefe = SimpleNamespace(is_authenticated=True, role='jefe_obra', id=3, is_deleted=False, is_active=True)
    assert puede_ser_impersonado(jefe, actor) is True
