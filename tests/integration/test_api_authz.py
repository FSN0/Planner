"""
Autorización de API y panel: operario no enumera plantilla ni calendarios ajenos;
admin/jefe sí, con el ámbito que les corresponde.
"""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app.models import Asignacion, User


def _activar_fichaje_operario(session, tenant):
    """El login de operario solo abre si el módulo y la config están activos."""
    mods = dict(tenant.modulos_activos or {})
    mods['fichaje_operario'] = True
    tenant.modulos_activos = mods
    session.add(tenant)
    session.execute(
        text(
            'INSERT INTO configuracion_global (clave, valor) VALUES (:c, :v) '
            'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
        ),
        {'c': 'fichaje_operario_activo', 'v': 'True'},
    )
    session.commit()


def _login(client, email, password):
    return client.post('/auth/login', data={'email': email, 'password': password})


@pytest.fixture
def operario_client(
    session, tenant_soltec, company_internal,
    user_admin, user_jefe, user_operario, obra_activa, tenant_client,
):
    """Cliente autenticado como operario (módulo de fichaje encendido)."""
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    _activar_fichaje_operario(session, tenant_soltec)
    respuesta = _login(tenant_client, 'operario@test.com', 'operario123')
    assert respuesta.status_code in (200, 302)
    return tenant_client


@pytest.fixture
def jefe_client(
    session, tenant_soltec, company_internal,
    user_admin, user_jefe, user_operario, obra_activa, tenant_client,
):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    respuesta = _login(tenant_client, 'jefe@test.com', 'jefe123')
    assert respuesta.status_code in (200, 302)
    return tenant_client


class TestRecursosActivosAuthz:
    def test_operario_no_puede_listar_recursos_activos(self, operario_client):
        response = operario_client.get('/api/v6/recursos_activos')
        assert response.status_code == 403

    def test_admin_ve_usuarios_en_recursos_activos(
        self, authenticated_client, tenant_soltec, user_operario, obra_activa, session,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        response = authenticated_client.get('/api/v6/recursos_activos')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'users' in data
        assert isinstance(data['users'], list)
        assert len(data['users']) >= 1
        ids = {u['id'] for u in data['users']}
        assert user_operario.id in ids

    def test_jefe_recursos_activos_no_es_403_y_acotado_a_sus_obras(
        self, jefe_client, tenant_soltec, user_jefe, user_operario,
        obra_activa, company_internal, session,
    ):
        """
        El jefe recibe 200. Los users son él + asignados a sus obras
        (no la plantilla completa).
        """
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))

        ajeno = User(
            email='ajeno@test.com',
            password_hash=generate_password_hash('ajeno123'),
            role='operario',
            name='Pedro',
            lastname='Ajeno',
            dni='55555555E',
            company_id=company_internal.id,
            active=True,
            email_verified=True,
        )
        session.add(ajeno)
        session.flush()
        session.add(Asignacion(
            user_id=user_operario.id,
            obra_id=obra_activa.id,
            fecha=date.today(),
        ))
        session.commit()

        response = jefe_client.get('/api/v6/recursos_activos')
        assert response.status_code == 200
        data = json.loads(response.data)
        ids = {u['id'] for u in data['users']}
        assert user_jefe.id in ids
        assert user_operario.id in ids
        assert ajeno.id not in ids


class TestUniversalCalendarAuthz:
    def test_operario_no_ve_calendario_de_otro_trabajador(
        self, operario_client, user_admin,
    ):
        today = date.today()
        start = (today - timedelta(days=7)).strftime('%Y-%m-%d')
        end = (today + timedelta(days=7)).strftime('%Y-%m-%d')
        response = operario_client.get(
            f'/api/v6/universal-calendar'
            f'?context=worker&id={user_admin.id}&start={start}&end={end}'
        )
        assert response.status_code == 403


class TestAdminSolicitudesAuthz:
    def test_operario_redirigido_fuera_de_solicitudes(self, operario_client):
        """No debe devolver 200 con el listado completo de solicitudes."""
        response = operario_client.get('/admin/solicitudes', follow_redirects=False)
        assert response.status_code in (302, 403)
        if response.status_code == 302:
            loc = response.location or ''
            assert '/admin/solicitudes' not in loc
            assert '/mi' in loc or '/auth/login' in loc or '/login' in loc
