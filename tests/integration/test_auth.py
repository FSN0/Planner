"""
Tests de Autenticación y Autorización

Estos tests verifican:
- Login correcto e incorrecto
- Que no exista alta pública de usuarios
- Control de acceso por roles
- Protección de rutas
"""

import pytest
from flask import session
from sqlalchemy import text
from werkzeug.security import generate_password_hash
from app.models import User


class TestLogin:
    """Tests del proceso de login"""
    
    def test_login_page_loads(self, tenant_client):
        """
        Test básico: verifica que la página de login carga correctamente.
        """
        response = tenant_client.get('/auth/login')
        assert response.status_code == 200
        assert b'login' in response.data.lower() or b'email' in response.data.lower()
    
    
    def test_login_successful(self, tenant_client, user_admin, tenant_soltec, session):
        """
        Test: Login exitoso con credenciales correctas
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = tenant_client.post('/auth/login', data={
            'email': 'admin@test.com',
            'password': 'admin123'
        }, follow_redirects=False)
        
        assert response.status_code == 302
        assert '/admin' in response.location

        from app.models import SystemLog
        log = (
            SystemLog.query
            .filter_by(category='accesos', action='Inicio de Sesión', user_id=user_admin.id)
            .order_by(SystemLog.id.desc())
            .first()
        )
        assert log is not None
        assert 'local' in (log.detail or '')
    
    
    def test_login_wrong_password(self, tenant_client, user_admin, tenant_soltec, session):
        """
        Test: Login fallido con contraseña incorrecta
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = tenant_client.post('/auth/login', data={
            'email': 'admin@test.com',
            'password': 'contraseña_incorrecta'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'inv' in response.data.lower() or b'error' in response.data.lower() or b'danger' in response.data.lower()
    
    
    def test_login_nonexistent_user(self, tenant_client, tenant_soltec, session):
        """
        Test: Intento de login con email que no existe
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = tenant_client.post('/auth/login', data={
            'email': 'noexiste@test.com',
            'password': 'cualquiera'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'inv' in response.data.lower() or b'error' in response.data.lower() or b'danger' in response.data.lower()
    
    
    def test_login_inactive_user(self, tenant_client, tenant_soltec, company_internal, session):
        """
        Test: Usuario desactivado no puede hacer login
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        from werkzeug.security import generate_password_hash
        inactive_user = User(
            email="inactive@test.com",
            password_hash=generate_password_hash("123456"),
            role="operario",
            name="Inactivo",
            lastname="Test",
            dni="99999999Z",
            company_id=company_internal.id,
            active=False
        )
        session.add(inactive_user)
        session.commit()
        
        response = tenant_client.post('/auth/login', data={
            'email': 'inactive@test.com',
            'password': '123456'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'activ' in response.data.lower() or b'no' in response.data.lower()
    
    
    def test_logout(self, authenticated_client):
        """
        Test: Logout cierra la sesión correctamente
        """
        response = authenticated_client.get('/auth/logout', follow_redirects=False)
        
        assert response.status_code == 302
        assert '/auth/login' in response.location

    def test_logout_con_remember_no_revive_la_sesion(
        self, tenant_client, tenant_soltec, company_internal, session,
    ):
        """Cerrar sesión debe caducar remember_token.

        Si no, el login reautentica y el perfil laboral vuelve a su inicio
        con el flash «Sesión cerrada» todavía visible.
        """
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        laboral = User(
            email='laboral@test.com',
            password_hash=generate_password_hash('laboral123'),
            role='laboral',
            name='Laura',
            lastname='Laboral',
            dni='88888888L',
            company_id=company_internal.id,
            active=True,
            email_verified=True,
        )
        session.add(laboral)
        session.commit()

        login = tenant_client.post('/auth/login', data={
            'email': 'laboral@test.com',
            'password': 'laboral123',
            'remember': 'on',
        }, follow_redirects=False)
        assert login.status_code == 302
        assert 'panel-laboral' in (login.location or '')
        assert any(
            c.name == 'remember_token' and c.value
            for c in tenant_client._client.cookie_jar
        )

        logout = tenant_client.get('/auth/logout', follow_redirects=False)
        assert logout.status_code == 302
        assert '/auth/login' in logout.location
        set_cookie = ' '.join(logout.headers.getlist('Set-Cookie'))
        assert 'remember_token=' in set_cookie

        pantallalogin = tenant_client.get('/auth/login', follow_redirects=False)
        assert pantallalogin.status_code == 200

        panel = tenant_client.get('/admin/panel-laboral', follow_redirects=False)
        assert panel.status_code in (302, 401)
        if panel.status_code == 302:
            assert '/auth/login' in (panel.location or '')

    def test_remember_me_revive_sesion_sin_tenant_id(
        self, tenant_client, tenant_soltec, company_internal, session,
    ):
        """Tras perder la cookie de sesión, remember_token debe reabrir la cuenta."""
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        laboral = User(
            email='remember@test.com',
            password_hash=generate_password_hash('remember123'),
            role='laboral',
            name='Reme',
            lastname='Mber',
            dni='77777777R',
            company_id=company_internal.id,
            active=True,
            email_verified=True,
        )
        session.add(laboral)
        session.commit()

        login = tenant_client.post('/auth/login', data={
            'email': 'remember@test.com',
            'password': 'remember123',
            'remember': 'on',
        }, follow_redirects=False)
        assert login.status_code == 302
        assert any(
            c.name == 'remember_token' and c.value
            for c in tenant_client._client.cookie_jar
        )

        # Simula cerrar el navegador: se pierde la cookie de sesión, queda remember.
        jar = tenant_client._client.cookie_jar
        for c in list(jar):
            if c.name == 'session':
                jar.clear(c.domain, c.path, c.name)

        with tenant_client.session_transaction() as sess:
            sess.pop('tenant_id', None)
            sess.pop('_user_id', None)
            sess.pop('_id', None)

        panel = tenant_client.get('/admin/panel-laboral', follow_redirects=False)
        assert panel.status_code == 200
        with tenant_client.session_transaction() as sess:
            assert sess.get('tenant_id') == tenant_soltec.id


class TestRegistro:
    """
    El auto-registro público se eliminó.

    Permitía que cualquiera con el código de una subcontrata se creara una
    cuenta en el tenant de esa empresa, sin autenticarse y sin límite de
    peticiones. Las personas entran por la sincronización del ERP o las da de
    alta administración. Estos tests están para que no vuelva sin querer.
    """

    def test_no_existe_alta_publica(self, tenant_client, tenant_soltec, session):
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        assert tenant_client.get('/auth/register').status_code == 404

    def test_no_se_pueden_crear_usuarios_sin_autenticarse(
        self, tenant_client, tenant_soltec, company_internal, session
    ):
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        session.commit()

        respuesta = tenant_client.post('/auth/register', data={
            'email': 'intruso@test.com',
            'password': 'password123',
            'name': 'Intruso',
            'lastname': 'Anónimo',
            'dni': '55555555E',
            'company_code': company_internal.code,
        })

        assert respuesta.status_code == 404

        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        assert User.query.filter_by(email='intruso@test.com').first() is None

    def test_la_pantalla_de_login_no_ofrece_registrarse(
        self, tenant_client, tenant_soltec, session
    ):
        """El enlace apuntaba a una plantilla borrada y devolvía un error 500."""
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        html = tenant_client.get('/auth/login').get_data(as_text=True)

        assert 'Regístrate aquí' not in html
        assert '/auth/register' not in html


class TestAutorizacion:
    """Tests de control de acceso por roles"""
    
    def test_admin_can_access_admin_panel(self, tenant_client, user_admin, tenant_soltec, session):
        """
        Test: Admin puede acceder al panel de administración
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        tenant_client.post('/auth/login', data={
            'email': 'admin@test.com',
            'password': 'admin123'
        })
        
        response = tenant_client.get('/admin/panel')
        
        assert response.status_code in [200, 302]
    
    
    def test_operario_cannot_access_admin_panel(self, tenant_client, user_operario, tenant_soltec, session):
        """
        Test CRÍTICO: Operario NO puede acceder al panel de admin
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        tenant_client.post('/auth/login', data={
            'email': 'operario@test.com',
            'password': 'operario123'
        })
        
        response = tenant_client.get('/admin/panel', follow_redirects=False)
        
        assert response.status_code in [302, 403]
    
    
    def test_jefe_can_access_jefe_panel(self, tenant_client, user_jefe, tenant_soltec, session):
        """Test: Jefe de obra puede acceder a su panel"""
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        tenant_client.post('/auth/login', data={
            'email': 'jefe@test.com',
            'password': 'jefe123'
        })
        
        response = tenant_client.get('/jefe/panel')
        assert response.status_code in [200, 302]
    
    
    def test_unauthenticated_redirects_to_login(self, tenant_client):
        """
        Test: Usuario no autenticado es redirigido al login
        """
        response = tenant_client.get('/admin/panel', follow_redirects=False)
        
        assert response.status_code == 302
        assert '/auth/login' in response.location or '/login' in response.location
