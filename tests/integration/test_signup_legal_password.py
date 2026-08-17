# tests/integration/test_signup_legal_password.py
#
# Alta pública, textos legales, recuperación de contraseña y exención de cobro.

from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import SignupReservation, Tenant
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
        assert 'Hasta que lo confirmes, el espacio no se crea' in html

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

    def test_alta_reserva_no_crea_tenant(self, client, session, app):
        session.execute(text('DROP SCHEMA IF EXISTS tenant_demofirma CASCADE'))
        session.execute(text("DELETE FROM public.signup_reservations WHERE subdominio = 'demofirma'"))
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
        assert 'admin@demofirma.test' in html
        assert 'demofirma' in html
        assert ('Revisa tu correo' in html) or ('No hemos podido enviar el correo' in html)
        assert 'Ir al acceso de tu empresa' not in html

        assert Tenant.query.filter_by(subdominio='demofirma').first() is None
        reserva = SignupReservation.query.filter_by(subdominio='demofirma').first()
        assert reserva is not None
        assert reserva.status == SignupReservation.STATUS_PENDING
        assert reserva.admin_email == 'admin@demofirma.test'

        from app.services.signup_service import generar_token_reserva
        token = generar_token_reserva(reserva)

        peek = client.get(
            '/alta/confirmar',
            headers={'Host': 'signaplan.com'},
            query_string={'t': token},
        )
        assert peek.status_code == 200
        assert Tenant.query.filter_by(subdominio='demofirma').first() is None
        assert 'Confirmar y crear mi espacio' in peek.get_data(as_text=True)

        confirm = client.post(
            '/alta/confirmar',
            headers={'Host': 'signaplan.com'},
            data={'t': token},
            follow_redirects=False,
        )
        assert confirm.status_code in (302, 303)
        location = confirm.headers.get('Location') or ''
        assert 'demofirma' in location
        assert '/auth/ticket' in location
        assert 'Tu espacio está listo' not in (confirm.get_data(as_text=True) or '')

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
        assert (tenant.modulos_activos or {}).get('notas') is False
        assert (tenant.modulos_activos or {}).get('auditoria_vehiculos') is False

        session.execute(text(f'SET search_path TO {tenant.schema_name}'))
        from app.models import ConfiguracionGlobal, Obra, User
        admin = User.query.filter_by(email='admin@demofirma.test').first()
        assert admin is not None
        assert admin.active is True
        assert admin.email_verified is True

        def _cfg(clave):
            row = ConfiguracionGlobal.query.filter_by(clave=clave).first()
            return row.valor if row else None

        assert _cfg('fichaje_operario_activo') == 'True'
        assert _cfg('onboarding_fichaje_asked') == 'True'
        assert _cfg('obra_oficina_activa') == 'True'
        oficina = Obra.query.filter_by(codigo='OFICINA').first()
        assert oficina is not None
        assert oficina.is_deleted is False
        session.execute(text('SET search_path TO public'))

        poll = client.get('/alta/estado', headers={'Host': 'signaplan.com'})
        assert poll.status_code == 200
        body = poll.get_json()
        assert body['status'] == 'ready'
        assert 'ticket_url' in body
        assert 'demofirma' in body['ticket_url']

        iphone = (
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
            'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
        )
        mobile = client.get(
            '/alta/confirmar',
            headers={'Host': 'signaplan.com', 'User-Agent': iphone},
            query_string={'t': token},
        )
        assert mobile.status_code == 200
        html_m = mobile.get_data(as_text=True)
        assert 'Tu espacio está listo' in html_m
        assert 'pestaña que dejaste abierta' in html_m

        desktop = client.get(
            '/alta/confirmar',
            headers={
                'Host': 'signaplan.com',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
            },
            query_string={'t': token},
            follow_redirects=False,
        )
        assert desktop.status_code in (302, 303)
        assert 'demofirma' in (desktop.headers.get('Location') or '')
        assert '/auth/ticket' in (desktop.headers.get('Location') or '')

        session.execute(text(f'DROP SCHEMA IF EXISTS {tenant.schema_name} CASCADE'))
        session.execute(text("DELETE FROM public.signup_reservations WHERE subdominio = 'demofirma'"))
        session.execute(text("DELETE FROM public.tenants WHERE subdominio = 'demofirma'"))
        session.commit()


class TestClienteMovil:

    def test_iphone_es_movil(self):
        from app.services.signup_service import es_cliente_movil
        ua = (
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
            'AppleWebKit/605.1.15 Mobile/15E148'
        )
        assert es_cliente_movil(ua) is True

    def test_chrome_escritorio_no_es_movil(self):
        from app.services.signup_service import es_cliente_movil
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
        assert es_cliente_movil(ua) is False

    def test_ipad_cuenta_como_escritorio(self):
        from app.services.signup_service import es_cliente_movil
        ua = 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15'
        assert es_cliente_movil(ua) is False

    def test_client_hint_mobile(self):
        from app.services.signup_service import es_cliente_movil
        assert es_cliente_movil('Mozilla/5.0', '?1') is True
        assert es_cliente_movil('Mozilla/5.0 (iPhone) Mobile', '?0') is False


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
