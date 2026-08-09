# tests/integration/test_plan_limits.py
#
# Freemium: el plan gratuito admite LIMITE_PLAN_GRATUITO trabajadores de
# plantilla (operario / jefe). El fichaje PWA solo en plan de pago.

from flask import g
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app.models import ROLE_OPERARIO, User
from app.services.plan_service import (
    LIMITE_PLAN_GRATUITO,
    PLAN_FREE,
    PLAN_PAID,
    PlanLimitError,
    asignar_plan,
    contar_empleados,
    exigir_alta_empleado,
    exigir_cupo,
    plan_incluye_geolocalizacion,
)
from app.services.fichaje_operario_service import fichaje_operario_activo, modo_geolocalizacion
import pytest


@pytest.fixture
def plan_ctx(session, tenant_soltec, company_internal, user_admin, user_operario, app):
    # Estos tests ejercitan el freemium; hace falta el interruptor de cobro.
    app.config['BILLING_ENFORCED'] = True
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    session.execute(
        text(
            'INSERT INTO configuracion_global (clave, valor) VALUES '
            "('fichaje_operario_activo', 'True') "
            'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
        )
    )
    asignar_plan(tenant_soltec, PLAN_FREE, limite=LIMITE_PLAN_GRATUITO, billing_exempt=False)
    session.commit()
    yield session, tenant_soltec
    app.config['BILLING_ENFORCED'] = False


def _alta(session, company_id, dni, active=True):
    u = User(
        email=f'{dni.lower()}@test.local',
        password_hash=generate_password_hash('x'),
        role=ROLE_OPERARIO,
        name='Operario',
        lastname=dni,
        dni=dni,
        company_id=company_id,
        active=active,
    )
    session.add(u)
    session.flush()
    return u


class TestCupo:

    def test_cuenta_solo_plantilla_activa(self, plan_ctx, company_internal, user_operario):
        session, _tenant = plan_ctx
        assert contar_empleados() == 1  # user_operario; admin no cuenta
        _alta(session, company_internal.id, 'A00000001', active=False)
        session.commit()
        assert contar_empleados() == 1

    def test_bloquea_al_llenar_el_cupo(self, plan_ctx, user_operario):
        session, tenant = plan_ctx
        asignar_plan(tenant, PLAN_FREE, limite=1, billing_exempt=False)
        session.commit()
        with pytest.raises(PlanLimitError):
            exigir_cupo(1, tenant=tenant)

    def test_permite_alta_inactiva_sin_gastar_plaza(self, plan_ctx, user_operario):
        session, tenant = plan_ctx
        asignar_plan(tenant, PLAN_FREE, limite=1, billing_exempt=False)
        session.commit()
        exigir_alta_empleado(role=ROLE_OPERARIO, active=False, tenant=tenant)

    def test_plan_pago_sin_limite(self, plan_ctx, user_operario):
        session, tenant = plan_ctx
        asignar_plan(tenant, PLAN_PAID, billing_exempt=False)
        session.commit()
        exigir_cupo(100, tenant=tenant)


class TestGeolocalizacionDePago:

    def test_plan_gratis_deja_fichar_pero_sin_geo(self, plan_ctx, app):
        _session, tenant = plan_ctx
        with app.test_request_context():
            g.current_tenant = tenant
            assert not plan_incluye_geolocalizacion()
            assert fichaje_operario_activo() is True
            assert modo_geolocalizacion() == 'desactivada'

    def test_plan_pago_permite_geo_configurada(self, plan_ctx, app):
        session, tenant = plan_ctx
        asignar_plan(tenant, PLAN_PAID, billing_exempt=False)
        session.execute(
            text(
                'INSERT INTO configuracion_global (clave, valor) VALUES '
                "('fichaje_geolocalizacion', 'opcional') "
                'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
            )
        )
        session.commit()
        with app.test_request_context():
            g.current_tenant = tenant
            assert plan_incluye_geolocalizacion()
            assert modo_geolocalizacion() == 'opcional'


class TestAltaPorFormulario:

    def test_create_user_rechaza_si_no_hay_cupo(
        self, plan_ctx, authenticated_client, company_internal, user_operario,
    ):
        session, tenant = plan_ctx
        asignar_plan(tenant, PLAN_FREE, limite=1, billing_exempt=False)
        session.commit()

        resp = authenticated_client.post(
            '/admin/create_user',
            data={
                'role': ROLE_OPERARIO,
                'name': 'Nuevo',
                'lastname': 'Operario',
                'dni': 'Z9999999Z',
                'pin_mode': 'manual',
                'pin': '2580',
                'company_id': str(company_internal.id),
                'active': 'on',
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert User.query.filter_by(dni='Z9999999Z').first() is None
        assert 'límite' in resp.get_data(as_text=True).lower() or 'plan gratuito' in resp.get_data(as_text=True).lower()
