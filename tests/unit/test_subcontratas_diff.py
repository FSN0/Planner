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


def test_diff_no_une_externos_por_email_empresa(
    sub_adapter, session, app, tenant_soltec, company_subcontrata,
):
    """Varios contactos con el email de la empresa no deben actualizarse entre sí."""
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        company_subcontrata.external_ids = {'odoo': '50'}
        session.add(company_subcontrata)

        natalia = User(
            name='NATALIA',
            lastname='X',
            dni='EXT-10007',
            email='oficina@subcontrata.test',
            role='operario',
            company_id=company_subcontrata.id,
            active=True,
            is_deleted=False,
            email_verified=True,
            password_hash=generate_password_hash('x'),
            external_ids={'odoo': '10007'},
        )
        session.add(natalia)
        session.commit()

        def execute_kw(*args, **kwargs):
            model, method = args[3], args[4]
            if model == 'res.partner.category' and method == 'search':
                return [9]
            if model == 'res.partner' and method == 'search_read':
                domain = args[5][0]
                if any(
                    isinstance(d, (list, tuple)) and d[0] == 'is_company' and d[2] is True
                    for d in domain
                ):
                    return [{
                        'id': 50,
                        'name': company_subcontrata.nombre,
                        'vat': '',
                        'email': 'oficina@subcontrata.test',
                        'category_id': [9],
                        'is_company': True,
                        'parent_id': False,
                    }]
                return [{
                    'id': 8879,
                    'name': 'ABDELILAH TAZOUTI',
                    'email': 'oficina@subcontrata.test',
                    'vat': False,
                    'function': 'Externo',
                    'parent_id': [50, company_subcontrata.nombre],
                }]
            return []

        sub_adapter.models.execute_kw.side_effect = execute_kw
        diff = sub_adapter.get_diff_subcontratas()

        assert diff['empleados']['actualizados'] == []
        assert len(diff['empleados']['nuevos']) == 1
        row = diff['empleados']['nuevos'][0]
        assert row['odoo_id'] == 8879
        assert row['name'] == 'ABDELILAH'
        assert row['email'] == 'ext_8879@subcontrata.local'


def test_resolve_externo_email_empresa_vs_personal():
    from app.sync.adapters.odoo_soltec import Adapter

    assert Adapter._resolve_externo_email(1, False, 'a@b.com') == 'ext_1@subcontrata.local'
    assert Adapter._resolve_externo_email(2, 'a@b.com', 'a@b.com') == 'ext_2@subcontrata.local'
    assert Adapter._resolve_externo_email(3, 'A@B.COM', 'a@b.com') == 'ext_3@subcontrata.local'
    assert Adapter._resolve_externo_email(4, 'yo@personal.com', 'a@b.com') == 'yo@personal.com'


def test_externo_dni_from_attendance_password_and_weak_vat():
    from app.sync.adapters.odoo_soltec import Adapter

    assert Adapter._externo_dni_from_partner({
        'id': 10,
        'vat': False,
        'attendance_password': '52655354M',
    }) == '52655354M'
    assert Adapter._externo_dni_from_partner({
        'id': 11,
        'vat': 'XXXXXXXXXXXXXXXX',
        'attendance_password': '44896149B',
    }) == '44896149B'
    assert Adapter._externo_dni_from_partner({
        'id': 12,
        'vat': 'XXXXXXXXXXXXXXXX',
        'attendance_password': False,
    }) == 'EXT-12'
    assert Adapter._externo_dni_from_partner({
        'id': 13,
        'vat': 'B12345678',
        'attendance_password': False,
    }) == 'EXT-13'
    assert Adapter._dni_match_weak('XXXXXXXXXXXXXXXX')
    assert Adapter._dni_match_weak('EXT-99')
    assert not Adapter._dni_match_weak('52655354M')


def test_diff_no_une_por_dni_si_otro_odoo_id(
    sub_adapter, session, app, tenant_soltec, company_subcontrata,
):
    """Mismo DNI en otra ficha con Id Odoo distinto → alta nueva, no «cambio Id Odoo»."""
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        company_subcontrata.external_ids = {'odoo': '50'}
        session.add(company_subcontrata)

        viejo = User(
            name='Otra',
            lastname='Persona',
            dni='52655354M',
            email='ext_1@subcontrata.local',
            role='operario',
            company_id=company_subcontrata.id,
            active=True,
            is_deleted=False,
            email_verified=True,
            password_hash=generate_password_hash('x'),
            external_ids={'odoo': '1'},
        )
        session.add(viejo)
        session.commit()

        def execute_kw(*args, **kwargs):
            model, method = args[3], args[4]
            if model == 'res.partner.category' and method == 'search':
                return [9]
            if model == 'res.partner' and method == 'search_read':
                domain = args[5][0]
                if any(
                    isinstance(d, (list, tuple)) and d[0] == 'is_company' and d[2] is True
                    for d in domain
                ):
                    return [{
                        'id': 50,
                        'name': company_subcontrata.nombre,
                        'vat': '',
                        'email': False,
                        'category_id': [9],
                        'is_company': True,
                        'parent_id': False,
                    }]
                return [{
                    'id': 9999,
                    'name': 'ADRIAN MACIAN',
                    'email': False,
                    'vat': False,
                    'attendance_password': '52655354M',
                    'function': 'Externo',
                    'parent_id': [50, company_subcontrata.nombre],
                    'category_id': [],
                }]
            return []

        sub_adapter.models.execute_kw.side_effect = execute_kw
        diff = sub_adapter.get_diff_subcontratas()

        assert diff['empleados']['actualizados'] == []
        assert len(diff['empleados']['nuevos']) == 1
        assert diff['empleados']['nuevos'][0]['odoo_id'] == 9999
        assert diff['empleados']['nuevos'][0]['dni'] == '52655354M'


def test_diff_lee_dni_desde_attendance_password(
    sub_adapter, session, app, tenant_soltec, company_subcontrata,
):
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        company_subcontrata.external_ids = {'odoo': '50'}
        session.add(company_subcontrata)
        session.commit()

        def execute_kw(*args, **kwargs):
            model, method = args[3], args[4]
            if model == 'res.partner.category' and method == 'search':
                return [9]
            if model == 'res.partner' and method == 'search_read':
                domain = args[5][0]
                if any(
                    isinstance(d, (list, tuple)) and d[0] == 'is_company' and d[2] is True
                    for d in domain
                ):
                    return [{
                        'id': 50,
                        'name': company_subcontrata.nombre,
                        'vat': '',
                        'email': False,
                        'category_id': [9],
                        'is_company': True,
                        'parent_id': False,
                    }]
                return [{
                    'id': 777,
                    'name': 'Lorena Grupo',
                    'email': False,
                    'vat': False,
                    'attendance_password': '12345678Z',
                    'function': 'Externo',
                    'parent_id': [50, company_subcontrata.nombre],
                    'category_id': [],
                }]
            return []

        sub_adapter.models.execute_kw.side_effect = execute_kw
        diff = sub_adapter.get_diff_subcontratas()

        assert len(diff['empleados']['nuevos']) == 1
        assert diff['empleados']['nuevos'][0]['dni'] == '12345678Z'


def test_diff_empresa_por_categoria(sub_adapter, session, app, tenant_soltec):
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
