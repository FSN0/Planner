"""Designar admin subcontrata desde Planner (write-back Odoo)."""
from unittest.mock import MagicMock

import pytest
from flask import g
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app.models import ROLE_ADMIN_SUBCONTRATA, ROLE_OPERARIO, Company, User
from app.services.admin_subcontrata_role_service import (
    puede_gestionar_admin_subcontrata,
    set_admin_subcontrata,
)


@pytest.fixture
def role_ctx(tenant_soltec, app, session, company_subcontrata):
    with app.app_context():
        g.current_tenant = tenant_soltec
        if not getattr(g.current_tenant, 'modulos_activos', None):
            g.current_tenant.modulos_activos = {}
        mods = dict(g.current_tenant.modulos_activos or {})
        mods['odoo'] = True
        g.current_tenant.modulos_activos = mods
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        company_subcontrata.is_internal = False
        company_subcontrata.active = True
        company_subcontrata.external_ids = {'odoo': '501'}
        session.add(company_subcontrata)
        session.flush()
        yield {
            'session': session,
            'company': company_subcontrata,
            'app': app,
        }


def _user(session, company, *, role=ROLE_OPERARIO, odoo_id='9001'):
    u = User(
        email=f'admin.sub.{odoo_id}@test.local',
        password_hash=generate_password_hash('x'),
        role=role,
        name='Admin',
        lastname='Sub',
        dni=f'DNI{odoo_id}',
        company_id=company.id,
        active=True,
        email_verified=True,
        is_deleted=False,
        external_ids={'odoo': str(odoo_id), 'odoo_model': 'res.partner'},
    )
    session.add(u)
    session.flush()
    return u


def test_puede_gestionar_requisitos(role_ctx):
    session = role_ctx['session']
    company = role_ctx['company']
    u = _user(session, company)
    assert puede_gestionar_admin_subcontrata(u) is True

    u.external_ids = {'odoo': '9001', 'odoo_model': 'hr.employee'}
    session.add(u)
    session.flush()
    assert puede_gestionar_admin_subcontrata(u) is False


def test_promover_escribe_odoo_antes_de_rol(role_ctx, monkeypatch):
    session = role_ctx['session']
    company = role_ctx['company']
    u = _user(session, company)

    adapter = MagicMock()
    monkeypatch.setattr(
        'app.sync.dispatcher.get_sync_adapter',
        lambda: adapter,
    )

    set_admin_subcontrata(u, make_admin=True)
    adapter.set_admin_subcontrata_category.assert_called_once_with(9001, enabled=True)
    assert u.role == ROLE_ADMIN_SUBCONTRATA


def test_si_odoo_falla_no_cambia_rol(role_ctx, monkeypatch):
    session = role_ctx['session']
    company = role_ctx['company']
    u = _user(session, company)

    adapter = MagicMock()
    adapter.set_admin_subcontrata_category.side_effect = ValueError('sin etiqueta')
    monkeypatch.setattr(
        'app.sync.dispatcher.get_sync_adapter',
        lambda: adapter,
    )

    with pytest.raises(ValueError, match='sin etiqueta'):
        set_admin_subcontrata(u, make_admin=True)
    assert u.role == ROLE_OPERARIO


def test_degradar_quita_etiqueta(role_ctx, monkeypatch):
    session = role_ctx['session']
    company = role_ctx['company']
    u = _user(session, company, role=ROLE_ADMIN_SUBCONTRATA)

    adapter = MagicMock()
    monkeypatch.setattr(
        'app.sync.dispatcher.get_sync_adapter',
        lambda: adapter,
    )

    set_admin_subcontrata(u, make_admin=False)
    adapter.set_admin_subcontrata_category.assert_called_once_with(9001, enabled=False)
    assert u.role == ROLE_OPERARIO


def test_exige_empresa_externa(role_ctx, monkeypatch):
    session = role_ctx['session']
    company = role_ctx['company']
    company.is_internal = True
    session.add(company)
    session.flush()
    u = _user(session, company)

    monkeypatch.setattr(
        'app.sync.dispatcher.get_sync_adapter',
        lambda: MagicMock(),
    )
    with pytest.raises(ValueError, match='subcontrata'):
        set_admin_subcontrata(u, make_admin=True)
