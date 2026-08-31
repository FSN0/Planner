# tests/integration/test_pin_auth.py
#
# Acceso a la PWA con DNI y PIN. Lo que importa:
#   - Sin PIN asignado no se entra, aunque el DNI exista.
#   - El PIN repetido (1111) se rechaza.
#   - Un DNI con formato distinto al de la base sigue encontrando al trabajador.
#   - El mensaje de error no delata si el fallo es el DNI o el PIN.

from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app.models import User
from app.services.pin_auth_service import (
    PinAuthError,
    asignar_pin,
    autenticar_por_pin,
    normalizar_dni,
    quitar_pin,
    validar_pin,
)
import pytest


@pytest.fixture
def pin_ctx(session, tenant_soltec, company_internal,
            user_admin, user_jefe, user_operario, obra_activa):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    session.execute(
        text(
            'INSERT INTO configuracion_global (clave, valor) VALUES '
            "('fichaje_operario_activo', 'True') "
            'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
        )
    )
    session.commit()
    yield session


class TestNormalizacion:

    def test_normaliza_guiones_y_espacios(self):
        assert normalizar_dni('12.345.678-A') == '12345678A'
        assert normalizar_dni(' 12345678a ') == '12345678A'


class TestValidacionPin:

    def test_acepta_cuatro_a_seis_digitos(self):
        assert validar_pin('4829') == '4829'
        assert validar_pin('482910') == '482910'

    def test_rechaza_letras_o_longitud_rara(self):
        with pytest.raises(PinAuthError):
            validar_pin('48ab')
        with pytest.raises(PinAuthError):
            validar_pin('12')
        with pytest.raises(PinAuthError):
            validar_pin('1234567')

    def test_rechaza_el_mismo_digito_repetido(self):
        with pytest.raises(PinAuthError):
            validar_pin('1111')


class TestAutenticacion:

    def test_entra_con_dni_y_pin(self, pin_ctx, user_operario):
        asignar_pin(user_operario, '4829')
        pin_ctx.commit()

        user = autenticar_por_pin(user_operario.dni, '4829')
        assert user.id == user_operario.id

    def test_encuentra_el_dni_aunque_llegue_con_guiones(
        self, pin_ctx, user_operario
    ):
        user_operario.dni = '12345678A'
        asignar_pin(user_operario, '4829')
        pin_ctx.commit()

        user = autenticar_por_pin('12345678-A', '4829')
        assert user.id == user_operario.id

    def test_sin_pin_asignado_no_entra(self, pin_ctx, user_operario):
        quitar_pin(user_operario)
        pin_ctx.commit()

        with pytest.raises(PinAuthError) as exc:
            autenticar_por_pin(user_operario.dni, '4829')
        assert 'PIN' in str(exc.value)

    def test_pin_incorrecto_no_delata_si_el_dni_existe(
        self, pin_ctx, user_operario
    ):
        asignar_pin(user_operario, '4829')
        pin_ctx.commit()

        with pytest.raises(PinAuthError) as exc:
            autenticar_por_pin(user_operario.dni, '0000')
        assert str(exc.value) == 'DNI o PIN incorrectos.'

        with pytest.raises(PinAuthError) as exc2:
            autenticar_por_pin('00000000Z', '4829')
        assert str(exc2.value) == 'DNI o PIN incorrectos.'

    def test_cuenta_inactiva_se_rechaza(self, pin_ctx, user_operario):
        asignar_pin(user_operario, '4829')
        user_operario.active = False
        pin_ctx.commit()

        with pytest.raises(PinAuthError) as exc:
            autenticar_por_pin(user_operario.dni, '4829')
        assert 'activa' in str(exc.value).lower()


class TestPantallaEntrar:

    def test_login_page_accessible(self, pin_ctx, tenant_client):
        respuesta = tenant_client.get('/auth/login', follow_redirects=True)
        assert respuesta.status_code == 200
        html = respuesta.get_data(as_text=True)
        assert 'login' in html.lower() or 'DNI' in html or 'correo' in html.lower()

    def test_login_por_pin_lleva_al_area_de_fichaje(
        self, pin_ctx, tenant_client, user_operario
    ):
        asignar_pin(user_operario, '4829')
        pin_ctx.commit()

        respuesta = tenant_client.post('/auth/login', data={
            'login': user_operario.dni,
            'secret': '4829',
        }, follow_redirects=True)

        assert respuesta.status_code == 200
        assert (
            'Jornada' in respuesta.get_data(as_text=True)
            or 'Fuera de jornada' in respuesta.get_data(as_text=True)
            or 'Entrar' in respuesta.get_data(as_text=True)
        )

    def test_sin_sesion_redirige_a_login(self, pin_ctx, tenant_client):
        respuesta = tenant_client.get('/fichaje/fichar', follow_redirects=False)
        assert respuesta.status_code in (302, 303)
        loc = respuesta.location or ''
        assert '/auth/login' in loc or '/login' in loc

    def test_admin_puede_asignar_pin(
        self, pin_ctx, authenticated_client, user_operario
    ):
        respuesta = authenticated_client.post(
            f'/admin/reset_pin/{user_operario.id}',
            data={'nuevo_pin': '4829', 'accion': 'asignar'},
            follow_redirects=True,
        )
        assert respuesta.status_code == 200

        pin_ctx.execute(text('SET search_path TO tenant_soltec'))
        user = User.query.get(user_operario.id)
        assert user.pin_hash is not None
        assert autenticar_por_pin(user.dni, '4829').id == user.id
