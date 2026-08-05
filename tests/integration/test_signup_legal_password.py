# tests/integration/test_signup_legal_password.py
#
# Alta pública, textos legales, recuperación de contraseña y exención de cobro.

from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import Tenant
from app.services.billing_service import debe_pasar_por_pasarela, esta_exento_de_cobro
from app.services.password_reset_service import (
    aplicar_nueva_password,
    solicitar_reset,
)
from app.services.plan_service import PLAN_FREE, asignar_plan, es_plan_pago
from app.services.signup_service import SignupError, validar_subdominio
import pytest


class TestSignupValidacion:

    def test_subdominio_reservado(self):
        with pytest.raises(SignupError):
            validar_subdominio('www')
        with pytest.raises(SignupError):
            validar_subdominio('alta')

    def test_alta_formulario_en_marketing(self, client):
        resp = client.get('/alta', headers={'Host': 'signaplan.com'})
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Crear cuenta' in html
        assert 'privacidad' in html.lower()

    def test_alta_tambien_en_localhost(self, client):
        resp = client.get('/alta', headers={'Host': 'localhost'})
        assert resp.status_code == 200
        assert 'Crear cuenta' in resp.get_data(as_text=True)

    def test_alta_no_existe_en_tenant(self, tenant_client):
        resp = tenant_client.get('/alta')
        assert resp.status_code == 404

    def test_sugerir_subdominio_desde_nombre(self):
        from app.services.signup_service import sugerir_subdominio
        assert sugerir_subdominio('Paquito') == 'paquito'
        assert sugerir_subdominio('Construcciones López') == 'construcciones-lopez'

    def test_alta_crea_tenant(self, client, session, app):
        session.execute(text("DELETE FROM public.tenants WHERE subdominio = 'demofirma'"))
        session.commit()

        resp = client.post(
            '/alta',
            headers={'Host': 'signaplan.com'},
            data={
                'nombre_empresa': 'Demo Firma SL',
                'subdominio': 'demofirma',
                'admin_email': 'admin@demofirma.test',
                'admin_password': 'Segura123!',
                'admin_password2': 'Segura123!',
                'acepta_privacidad': '1',
                'acepta_condiciones': '1',
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Revisa tu correo' in html
        assert 'admin@demofirma.test' in html
        assert 'demofirma' in html

        tenant = Tenant.query.filter_by(subdominio='demofirma').first()
        assert tenant is not None
        assert tenant.plan == 'free'
        assert tenant.billing_exempt is False
        assert tenant.legal_aceptado_at is not None
        assert tenant.legal_privacidad_version == '2026-08'
        assert tenant.legal_condiciones_version == '2026-08'
        assert (tenant.modulos_activos or {}).get('fichaje_operario') is True
        assert (tenant.modulos_activos or {}).get('onboarding') is True
        assert (tenant.modulos_activos or {}).get('registro_jornada') is True

        session.execute(text(f'SET search_path TO {tenant.schema_name}'))
        from app.models import User
        admin = User.query.filter_by(email='admin@demofirma.test').first()
        assert admin is not None
        assert admin.active is False
        assert admin.email_verified is False
        session.execute(text('SET search_path TO public'))

        # Limpieza del esquema creado por el alta
        session.execute(text('DROP SCHEMA IF EXISTS tenant_demofirma CASCADE'))
        session.execute(text("DELETE FROM public.tenants WHERE subdominio = 'demofirma'"))
        session.commit()


class TestLegal:

    def test_privacidad_y_cookies(self, client):
        for slug in ('privacidad', 'cookies', 'aviso-legal', 'encargado', 'condiciones'):
            resp = client.get(f'/legal/{slug}', headers={'Host': 'signaplan.com'})
            assert resp.status_code == 200, slug


class TestPasswordReset:

    def test_flujo_completo(self, session, tenant_soltec, user_admin, app, tenant_client):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        user_admin.password_hash = generate_password_hash('Antigua123!')
        session.commit()

        with app.test_request_context():
            called = {}

            def builder(token):
                called['token'] = token
                return f'https://soltec.signaplan.com/auth/recuperar/{token}'

            solicitar_reset(user_admin.email, tenant_soltec, builder)
            assert 'token' in called

            aplicar_nueva_password(
                called['token'], tenant_soltec, 'NuevaSegura1', 'NuevaSegura1'
            )

        session.refresh(user_admin)
        assert check_password_hash(user_admin.password_hash, 'NuevaSegura1')

    def test_pantalla_recuperar(self, tenant_client, tenant_soltec, session):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        resp = tenant_client.get('/auth/recuperar')
        assert resp.status_code == 200
        assert 'correo' in resp.get_data(as_text=True).lower()


class TestBillingExempt:

    def test_exento_cuenta_como_pago(self, session, tenant_soltec):
        asignar_plan(tenant_soltec, PLAN_FREE, billing_exempt=True)
        session.commit()
        assert esta_exento_de_cobro(tenant_soltec)
        assert es_plan_pago(tenant_soltec)
        assert not debe_pasar_por_pasarela(tenant_soltec)

    def test_pago_sin_exento_deberia_cobrarse(self, session, tenant_soltec):
        asignar_plan(tenant_soltec, 'paid', billing_exempt=False)
        session.commit()
        assert not esta_exento_de_cobro(tenant_soltec)
        assert debe_pasar_por_pasarela(tenant_soltec)
