"""Diff/commit de subcontratas: no duplicar email ext_*@subcontrata.local."""
from unittest.mock import Mock

import pytest
from flask import g
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app.models import Company, User


@pytest.fixture
def sub_adapter(tenant_soltec, app, session):
    from app.sync.adapters.odoo_soltec import Adapter

    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        User.query.filter(User.email.like('%@subcontrata.local')).delete(
            synchronize_session=False
        )
        Company.query.filter(Company.is_internal.is_(False)).delete(
            synchronize_session=False
        )
        session.commit()

        adapter = Adapter.__new__(Adapter)
        adapter.tenant_id = tenant_soltec.id
        adapter.db_name = 'db'
        adapter.uid = 2
        adapter.pwd = 'x'
        adapter.models = Mock()
        yield adapter


def test_diff_reactivates_deleted_externo_instead_of_nuevo(
    sub_adapter, session, app, tenant_soltec, company_subcontrata,
):
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        company_subcontrata.external_ids = {'odoo': '50'}
        session.add(company_subcontrata)

        dead = User(
            name='Viejo',
            lastname='Contacto',
            dni='EXT-9875',
            email='ext_9875@subcontrata.local',
            role='operario',
            company_id=company_subcontrata.id,
            active=False,
            is_deleted=True,
            email_verified=True,
            password_hash=generate_password_hash('x'),
            external_ids={'odoo': '9875'},
        )
        session.add(dead)
        session.commit()

        def execute_kw(*args, **kwargs):
            model, method = args[3], args[4]
            if model == 'res.partner.category' and method == 'search':
                return [9]
            if model == 'res.partner' and method == 'search_read':
                domain = args[5][0]
                # empresas
                if any(d[0] == 'is_company' and d[2] is True for d in domain if isinstance(d, (list, tuple))):
                    return [{'id': 50, 'name': company_subcontrata.nombre, 'vat': '', 'category_id': [9]}]
                # contactos
                return [{
                    'id': 9875,
                    'name': 'Nuevo Nombre Ext',
                    'email': False,
                    'vat': False,
                    'function': 'Pintor',
                    'parent_id': [50, company_subcontrata.nombre],
                }]
            return []

        sub_adapter.models.execute_kw.side_effect = execute_kw
        diff = sub_adapter.get_diff_subcontratas()

        assert diff['empleados']['nuevos'] == []
        assert len(diff['empleados']['actualizados']) == 1
        row = diff['empleados']['actualizados'][0]
        assert row['local_id'] == dead.id
        assert row['email'] == 'ext_9875@subcontrata.local'
        assert 'Estado' in row['cambios']


def test_diff_empresas_usa_category_ids(sub_adapter, session, app, tenant_soltec):
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        seen = {}

        def execute_kw(*args, **kwargs):
            model, method = args[3], args[4]
            if model == 'res.partner.category' and method == 'search':
                seen['cats'] = True
                return [3, 7]
            if model == 'res.partner.category' and method == 'read':
                return [
                    {'id': 3, 'name': 'Subcontractor'},
                    {'id': 7, 'name': 'Subcontrata'},
                ]
            if model == 'res.partner' and method == 'search_read':
                domain = args[5][0]
                opts = args[6] if len(args) > 6 else {}
                if any(isinstance(d, (list, tuple)) and d[0] == 'category_id' for d in domain):
                    seen['domain_ok'] = True
                    seen['limit'] = opts.get('limit')
                    return [{
                        'id': 100,
                        'name': 'Nueva Sub SA',
                        'vat': 'B123',
                        'category_id': [3],
                        'is_company': True,
                        'parent_id': False,
                    }]
                return []
            return []

        sub_adapter.models.execute_kw.side_effect = execute_kw
        diff = sub_adapter.get_diff_subcontratas()

        assert seen.get('cats')
        assert seen.get('domain_ok')
        assert seen.get('limit') == 10000
        assert len(diff['empresas']['nuevas']) == 1
        assert diff['empresas']['nuevas'][0]['nombre'] == 'Nueva Sub SA'
