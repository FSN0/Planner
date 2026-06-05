"""
conftest.py - Configuración global de pytest y fixtures compartidos

Los 'fixtures' son funciones que preparan el entorno para los tests.
Por ejemplo: crear una base de datos de prueba, un usuario de test, etc.

Pytest ejecuta automáticamente los fixtures que cada test necesite.
"""

import os
os.environ['RATELIMIT_STORAGE_URI'] = 'memory://'

import pytest
from sqlalchemy import text, create_engine
from app import create_app, db as _db, limiter as _limiter

_limiter._disabled = True
_limiter._check_request_limit = lambda *args, **kwargs: None
from app.models import (
    User, Tenant, Company, Obra, Asignacion, 
    RegistroFichaje, Solicitud, ConfiguracionGlobal
)
from werkzeug.security import generate_password_hash
from datetime import date, datetime


# ============================================================================
# CONFIGURACIÓN DE BASE DE DATOS DE TEST
# ============================================================================

@pytest.fixture(scope='session')
def database_url():
    """
    URL de la base de datos de test.
    
    IMPORTANTE: Usa una base de datos DIFERENTE a la de desarrollo/producción.
    Esta base de datos se limpiará completamente durante los tests.
    """
    # Puedes configurar esto con variables de entorno
    return os.environ.get(
        'TEST_DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/gestion_obra_test'
    )


@pytest.fixture(scope='session')
def app(database_url):
    """
    Crea la aplicación Flask configurada para testing.
    
    scope='session' significa que se crea UNA SOLA VEZ para todos los tests.
    """
    # Variables de entorno para testing
    os.environ['SECRET_KEY'] = 'test-secret-key-super-segura-para-tests'
    os.environ['ENCRYPTION_KEY'] = 'hIQxMPbaYZ_WxJx4w3d9OaV8gQSNJFnKHQVfQPl7S1k='
    os.environ['DATABASE_URL'] = database_url
    os.environ['CELERY_TASK_ALWAYS_EAGER'] = 'true'
    os.environ['MAIL_SUPPRESS_SEND'] = 'true'
    os.environ['TESTING'] = 'true'
    os.environ['RATELIMIT_STORAGE_URI'] = 'memory://'
    
    # Crear la aplicación
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['WTF_CSRF_CHECK_DEFAULT'] = False
    app.config['RATELIMIT_ENABLED'] = False
    app.config['RATELIMIT_STORAGE_URI'] = 'memory://'
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['REMEMBER_COOKIE_SECURE'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    
    # Contexto de aplicación (necesario para acceder a db, current_app, etc.)
    with app.app_context():
        yield app


@pytest.fixture(scope='session')
def db(app):
    """
    Crea las tablas de la base de datos de test.
    
    Se ejecuta UNA VEZ al inicio de todos los tests.
    Al final, borra todas las tablas (limpieza).
    """
    with app.app_context():
        # Crear el esquema public si no existe
        _db.session.execute(text("CREATE SCHEMA IF NOT EXISTS public"))
        _db.session.commit()
        
        # Limpiar TODOS los schemas de tenants antiguos
        result = _db.session.execute(text("""
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name LIKE 'tenant_%'
        """))
        for row in result:
            schema_name = row[0]
            _db.session.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
        _db.session.commit()
        
        # Crear todas las tablas
        _db.create_all()
        
        yield _db
        
        # Limpieza: borra todas las tablas al finalizar los tests
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(scope='function')
def session(db, app):
    """
    Crea una sesión de base de datos limpia para cada test.
    
    IMPORTANTE: NO intenta reemplazar db.session porque rompe Flask-SQLAlchemy.
    En su lugar, usa db.session directamente.
    """
    with app.app_context():
        # Usar la sesión de Flask-SQLAlchemy directamente
        session = db.session
        
        # Por defecto, trabajamos en el esquema 'public'
        session.execute(text("SET search_path TO public"))
        
        yield session
        
        # Limpieza: solo remove, no rollback (los fixtures ya hacen commit)
        try:
            session.remove()
        except:
            pass


# ============================================================================
# FIXTURES DE DATOS - Tenants
# ============================================================================

@pytest.fixture(scope='session')
def _tenant_schemas(db):
    """
    Crea los schemas de tenants UNA VEZ para toda la sesión de tests.
    Esto evita problemas con transacciones.
    """
    # Crear schemas de tenants
    schemas = ['tenant_soltec', 'tenant_acme']
    
    for schema_name in schemas:
        db.session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
    db.session.commit()
    
    # Crear tablas en cada schema
    for schema_name in schemas:
        db.session.execute(text(f"SET search_path TO {schema_name}"))
        
        # Crear todas las tablas (excepto tenants)
        from sqlalchemy import MetaData
        metadata = MetaData()
        
        for table in db.metadata.sorted_tables:
            if table.name != 'tenants':
                table.to_metadata(metadata, schema=schema_name)
        
        metadata.create_all(bind=db.engine)
    
    # Volver a public
    db.session.execute(text("SET search_path TO public"))
    db.session.commit()
    
    return schemas


@pytest.fixture
def tenant_soltec(session, db, _tenant_schemas):
    """
    Crea un tenant de ejemplo: SOLTEC
    El schema y tablas ya existen (creados en _tenant_schemas).
    """
    # Limpiar cualquier tenant existente con este subdominio
    session.execute(text("DELETE FROM public.tenants WHERE subdominio = 'soltec'"))
    session.commit()
    
    tenant = Tenant(
        nombre="SOLTEC",
        subdominio="soltec",
        schema_name="tenant_soltec",
        is_active=True,
        modulos_activos={
            "sync": True,
            "fichajes": True,
            "solicitudes": True
        }
    )
    session.add(tenant)
    session.commit()  # Commit para que esté disponible
    
    yield tenant
    
    # Limpieza después del test
    session.execute(text(f"TRUNCATE TABLE {tenant.schema_name}.users CASCADE"))
    session.execute(text(f"TRUNCATE TABLE {tenant.schema_name}.companies CASCADE"))
    session.execute(text(f"TRUNCATE TABLE {tenant.schema_name}.obras CASCADE"))
    session.execute(text("DELETE FROM public.tenants WHERE subdominio = 'soltec'"))
    session.commit()


@pytest.fixture
def tenant_acme(session, db, _tenant_schemas):
    """Crea un segundo tenant para tests multi-tenant"""
    # Limpiar cualquier tenant existente con este subdominio
    session.execute(text("DELETE FROM public.tenants WHERE subdominio = 'acme'"))
    session.commit()
    
    tenant = Tenant(
        nombre="ACME Corp",
        subdominio="acme",
        schema_name="tenant_acme",
        is_active=True,
        modulos_activos={}
    )
    session.add(tenant)
    session.commit()  # Commit para que esté disponible
    
    yield tenant
    
    # Limpieza después del test
    session.execute(text(f"TRUNCATE TABLE {tenant.schema_name}.users CASCADE"))
    session.execute(text(f"TRUNCATE TABLE {tenant.schema_name}.companies CASCADE"))
    session.execute(text(f"TRUNCATE TABLE {tenant.schema_name}.obras CASCADE"))
    session.execute(text("DELETE FROM public.tenants WHERE subdominio = 'acme'"))
    session.commit()


# ============================================================================
# FIXTURES DE DATOS - Empresas
# ============================================================================

@pytest.fixture
def company_internal(session, tenant_soltec, db):
    """Crea una empresa interna (la empresa propia)"""
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    
    company = Company(
        code="SOCTEC",
        nombre="SOCTEC - Empresa Principal",
        nif="B12345678",
        is_internal=True,
        color="#a8d5ba"
    )
    session.add(company)
    session.commit()  # Commit para que esté disponible
    
    session.execute(text("SET search_path TO public"))
    return company


@pytest.fixture
def company_subcontrata(session, tenant_soltec, db):
    """Crea una empresa subcontratada"""
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    
    company = Company(
        code="ELEC_EXT",
        nombre="Electricidad Externa S.L.",
        nif="B87654321",
        is_internal=False,
        gremio="Electricidad",
        color="#f4d06f"
    )
    session.add(company)
    session.commit()  # Commit para que esté disponible
    
    session.execute(text("SET search_path TO public"))
    return company


# ============================================================================
# FIXTURES DE DATOS - Usuarios
# ============================================================================

@pytest.fixture
def user_admin(session, tenant_soltec, company_internal, db):
    """Crea un usuario administrador"""
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    
    user = User(
        email="admin@test.com",
        password_hash=generate_password_hash("admin123"),
        role="admin",
        name="Admin",
        lastname="Test",
        dni="11111111A",
        company_id=company_internal.id,
        active=True
    )
    session.add(user)
    session.commit()  # Commit para que esté disponible
    
    session.execute(text("SET search_path TO public"))
    return user


@pytest.fixture
def user_jefe(session, tenant_soltec, company_internal, db):
    """Crea un usuario jefe de obra"""
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    
    user = User(
        email="jefe@test.com",
        password_hash=generate_password_hash("jefe123"),
        role="jefe_obra",
        name="Carlos",
        lastname="Jefe",
        dni="22222222B",
        company_id=company_internal.id,
        active=True
    )
    session.add(user)
    session.commit()  # Commit para que esté disponible
    
    session.execute(text("SET search_path TO public"))
    return user


@pytest.fixture
def user_rrhh(session, tenant_soltec, company_internal, db):
    """Crea un usuario de recursos humanos"""
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    
    user = User(
        email="rrhh@test.com",
        password_hash=generate_password_hash("rrhh123"),
        role="rrhh",
        name="María",
        lastname="RRHH",
        dni="33333333C",
        company_id=company_internal.id,
        active=True
    )
    session.add(user)
    session.commit()  # Commit para que esté disponible
    
    session.execute(text("SET search_path TO public"))
    return user


@pytest.fixture
def user_operario(session, tenant_soltec, company_internal, db):
    """Crea un usuario operario"""
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    
    user = User(
        email="operario@test.com",
        password_hash=generate_password_hash("operario123"),
        role="operario",
        name="Juan",
        lastname="Operario",
        dni="44444444D",
        company_id=company_internal.id,
        categoria_profesional="Oficial 1ª",
        active=True
    )
    session.add(user)
    session.commit()  # Commit para que esté disponible
    
    session.execute(text("SET search_path TO public"))
    return user


# ============================================================================
# FIXTURES DE DATOS - Obras
# ============================================================================

@pytest.fixture
def obra_activa(session, tenant_soltec, user_jefe, db):
    """Crea una obra activa con un jefe asignado"""
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    
    obra = Obra(
        codigo="OBR001",
        nombre="Reforma Hotel Central",
        descripcion="Cliente: Hoteles Unidos S.A.",
        fecha_inicio=date(2024, 1, 15),
        estado="En proceso",
        jefe_obra_id=user_jefe.id
    )
    session.add(obra)
    session.commit()  # Commit para que esté disponible
    
    session.execute(text("SET search_path TO public"))
    return obra


# ============================================================================
# FIXTURES DE CLIENTE HTTP
# ============================================================================

@pytest.fixture
def client(app):
    """
    Cliente HTTP para hacer peticiones a la aplicación.
    
    Úsalo en tests para simular peticiones web:
        response = client.get('/login')
        assert response.status_code == 200
    """
    return app.test_client()


@pytest.fixture
def tenant_client(client, tenant_soltec):
    """
    Cliente HTTP con el Host header configurado para el tenant soltec.
    Necesario porque las rutas de auth/registro requieren g.current_tenant.
    """
    class TenantTestClient:
        def __init__(self, client, host):
            self._client = client
            self._host = host
        
        def get(self, *args, **kwargs):
            kwargs.setdefault('headers', {})
            kwargs['headers']['Host'] = self._host
            return self._client.get(*args, **kwargs)
        
        def post(self, *args, **kwargs):
            kwargs.setdefault('headers', {})
            kwargs['headers']['Host'] = self._host
            return self._client.post(*args, **kwargs)
        
        def put(self, *args, **kwargs):
            kwargs.setdefault('headers', {})
            kwargs['headers']['Host'] = self._host
            return self._client.put(*args, **kwargs)
        
        def delete(self, *args, **kwargs):
            kwargs.setdefault('headers', {})
            kwargs['headers']['Host'] = self._host
            return self._client.delete(*args, **kwargs)
        
        def session_transaction(self, *args, **kwargs):
            return self._client.session_transaction(*args, **kwargs)
    
    return TenantTestClient(client, f'{tenant_soltec.subdominio}.localhost:5000')


@pytest.fixture
def authenticated_client(tenant_client, user_admin, tenant_soltec, session, db):
    """
    Cliente HTTP ya autenticado como admin con Host header correcto.
    
    Hace login real via POST para que Flask-Login establezca la sesión correctamente.
    """
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    
    response = tenant_client.post('/auth/login', data={
        'email': 'admin@test.com',
        'password': 'admin123'
    })
    
    return tenant_client


# ============================================================================
# FIXTURES DE UTILIDADES
# ============================================================================

@pytest.fixture
def mock_odoo_api(mocker):
    """
    Mock de la API de Odoo para no hacer llamadas reales durante tests.
    
    Simula respuestas de Odoo sin conectar realmente.
    """
    # Aquí puedes mockear las llamadas a Odoo
    # Ejemplo:
    # mocker.patch('app.sync.adapters.odoo_soltec.OdooSoltecAdapter.conectar')
    return mocker
