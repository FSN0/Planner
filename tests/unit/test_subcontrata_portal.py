"""Portal subcontrata: preferencias, panel KPIs y alcance de equipo."""
from datetime import date

from sqlalchemy import text
from werkzeug.security import generate_password_hash


def _make_sub_admin(session, tenant, company, email='sub.admin@portal.test', dni='SUBADM01'):
    from app.models import ROLE_ADMIN_SUBCONTRATA, User

    session.execute(text(f'SET search_path TO {tenant.schema_name}'))
    u = User(
        email=email,
        password_hash=generate_password_hash('x'),
        role=ROLE_ADMIN_SUBCONTRATA,
        name='Sub',
        lastname='Admin',
        dni=dni,
        company_id=company.id,
        active=True,
        email_verified=True,
        is_deleted=False,
    )
    session.add(u)
    session.commit()
    return u


def _make_op(session, tenant, company, email, dni, name='Op'):
    from app.models import User

    session.execute(text(f'SET search_path TO {tenant.schema_name}'))
    u = User(
        email=email,
        password_hash=generate_password_hash('x'),
        role='operario',
        name=name,
        lastname='Portal',
        dni=dni,
        company_id=company.id,
        active=True,
        email_verified=True,
        is_deleted=False,
    )
    session.add(u)
    session.commit()
    return u


def test_panel_includes_action_kpis(session, tenant_soltec, company_subcontrata, app):
    from app.services.subcontrata_portal_service import panel

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    _make_op(session, tenant_soltec, company_subcontrata, 'op.kpi@portal.test', 'OPKPI01')
    with app.app_context():
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        datos = panel(company_subcontrata)
    assert 'equipo_activo' in datos
    assert datos['equipo_activo'] >= 1
    assert 'cert_pendientes' in datos
    assert 'docs_pendientes' in datos
    assert 'cta_principal' in datos
    assert isinstance(datos['hoy'], date)


def test_listado_personal_solo_su_company(
    session, tenant_soltec, company_subcontrata, company_internal, app,
):
    from app.services.subcontrata_portal_service import listado_personal, usuario_de_company

    schema = tenant_soltec.schema_name
    session.execute(text(f'SET search_path TO {schema}'))
    own = _make_op(session, tenant_soltec, company_subcontrata, 'own@portal.test', 'OWN001', 'Own')
    other = _make_op(session, tenant_soltec, company_internal, 'other@portal.test', 'OTH001', 'Other')

    with app.app_context():
        session.execute(text(f'SET search_path TO {schema}'))
        filas = listado_personal(company_subcontrata)
        ids = {f['user'].id for f in filas}
        assert own.id in ids
        assert other.id not in ids
        assert usuario_de_company(company_subcontrata, own.id) is not None
        assert usuario_de_company(company_subcontrata, other.id) is None


def test_can_view_worker_calendar_same_company(
    session, tenant_soltec, company_subcontrata, company_internal, app,
):
    from app.services.permission_service import can_view_worker_calendar

    schema = tenant_soltec.schema_name
    session.execute(text(f'SET search_path TO {schema}'))
    admin = _make_sub_admin(session, tenant_soltec, company_subcontrata)
    own = _make_op(session, tenant_soltec, company_subcontrata, 'cal.own@portal.test', 'CALOWN1')
    other = _make_op(session, tenant_soltec, company_internal, 'cal.oth@portal.test', 'CALOTH1')

    with app.app_context():
        session.execute(text(f'SET search_path TO {schema}'))
        assert can_view_worker_calendar(admin, own.id) is True
        assert can_view_worker_calendar(admin, other.id) is False


def test_subcontrata_config_get_allowed(session, tenant_soltec, company_subcontrata, app, client):
    """GET /admin/configuracion no debe expulsar al portal con flash de bloqueo."""
    from flask_login import login_user

    schema = tenant_soltec.schema_name
    session.execute(text(f'SET search_path TO {schema}'))
    admin = _make_sub_admin(
        session, tenant_soltec, company_subcontrata,
        email='cfg.sub@portal.test', dni='CFGSUB01',
    )

    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['_fresh'] = True

    # Forzar search_path vía app context + login en request
    with app.test_request_context('/admin/configuracion'):
        session.execute(text(f'SET search_path TO {schema}'))
        login_user(admin)
        from app.admin.routes import _bloquear_operario_en_admin
        # Simular path exacto
        from flask import request
        assert (request.path or '').rstrip('/') == '/admin/configuracion'
        result = _bloquear_operario_en_admin()
        assert result is None


def test_subcontrata_other_admin_routes_still_blocked(
    session, tenant_soltec, company_subcontrata, app,
):
    from flask_login import login_user

    schema = tenant_soltec.schema_name
    session.execute(text(f'SET search_path TO {schema}'))
    admin = _make_sub_admin(
        session, tenant_soltec, company_subcontrata,
        email='blk.sub@portal.test', dni='BLKSUB01',
    )

    with app.test_request_context('/admin/personal'):
        session.execute(text(f'SET search_path TO {schema}'))
        login_user(admin)
        from app.admin.routes import _bloquear_operario_en_admin
        result = _bloquear_operario_en_admin()
        assert result is not None
        assert result.status_code in (302, 301)


def test_documentacion_persona_solo_su_company(
    session, tenant_soltec, company_subcontrata, company_internal, app,
):
    from app.services.subcontrata_portal_service import usuario_de_company

    schema = tenant_soltec.schema_name
    session.execute(text(f'SET search_path TO {schema}'))
    own = _make_op(session, tenant_soltec, company_subcontrata, 'doc.own@portal.test', 'DOCOWN1')
    other = _make_op(session, tenant_soltec, company_internal, 'doc.oth@portal.test', 'DOCOTH1')
    assert usuario_de_company(company_subcontrata, own.id) is not None
    assert usuario_de_company(company_subcontrata, other.id) is None


def test_ficha_trabajador_kpis(session, tenant_soltec, company_subcontrata, app):
    from app.models import Asignacion, Obra
    from app.services.subcontrata_portal_service import ficha_trabajador
    from app.utils.timezone_utils import today_local

    schema = tenant_soltec.schema_name
    session.execute(text(f'SET search_path TO {schema}'))
    op = _make_op(session, tenant_soltec, company_subcontrata, 'ficha@portal.test', 'FICHA01', 'Ficha')
    obra = Obra(nombre='Obra ficha', codigo='OF-01', estado='En Curso', is_deleted=False)
    session.add(obra)
    session.flush()
    hoy = today_local()
    session.add(Asignacion(user_id=op.id, obra_id=obra.id, fecha=hoy))
    session.commit()

    with app.app_context():
        session.execute(text(f'SET search_path TO {schema}'))
        ficha = ficha_trabajador(company_subcontrata, op)
    assert ficha['dias_mes'] >= 1
    assert ficha['obras_mes'] >= 1
    assert ficha['asignado_hoy'] is True
    assert 'docs_errores' in ficha
    assert any(r['obra_id'] == obra.id for r in ficha['por_obra'])
