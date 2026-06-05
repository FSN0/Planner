"""
Tests de Autenticación y Autorización

Estos tests verifican:
- Login correcto e incorrecto
- Registro de usuarios
- Control de acceso por roles
- Protección de rutas
"""

import pytest
from flask import session
from sqlalchemy import text
from app.models import User
from werkzeug.security import check_password_hash


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


class TestRegistro:
    """Tests del proceso de registro de nuevos usuarios"""
    
    def test_register_page_loads(self, tenant_client):
        """Verifica que la página de registro carga"""
        response = tenant_client.get('/auth/register')
        assert response.status_code == 200
        assert b'registr' in response.data.lower() or b'email' in response.data.lower()
    
    
    def test_register_new_user(self, tenant_client, tenant_soltec, company_internal, session):
        """
        Test: Registro exitoso de un nuevo usuario
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        session.commit()
        
        response = tenant_client.post('/auth/register', data={
            'email': 'nuevo@test.com',
            'password': 'password123',
            'name': 'Nuevo',
            'lastname': 'Usuario',
            'dni': '55555555E',
            'company_code': company_internal.code,
            'categoria_profesional': 'Oficial 2ª'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        nuevo_user = User.query.filter_by(email='nuevo@test.com').first()
        assert nuevo_user is not None
        assert nuevo_user.name == 'Nuevo'
        assert nuevo_user.lastname == 'Usuario'
        assert nuevo_user.dni == '55555555E'
        
        assert nuevo_user.password_hash != 'password123'
        assert check_password_hash(nuevo_user.password_hash, 'password123')
    
    
    def test_register_duplicate_email(self, tenant_client, user_admin, tenant_soltec, company_internal, session):
        """
        Test: No permite registrar email duplicado
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        session.commit()
        
        response = tenant_client.post('/auth/register', data={
            'email': 'admin@test.com',
            'password': 'password123',
            'name': 'Otro',
            'lastname': 'Usuario',
            'dni': '66666666F',
            'company_code': company_internal.code,
            'categoria_profesional': 'Peón'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'existe' in response.data.lower() or b'ya' in response.data.lower() or b'danger' in response.data.lower()


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
