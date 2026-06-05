# Guía de Testing - Gestión de Obra SaaS

## 📚 Índice

1. [Introducción](#introducción)
2. [Configuración Inicial](#configuración-inicial)
3. [Ejecutar Tests](#ejecutar-tests)
4. [Estructura de Tests](#estructura-de-tests)
5. [Escribir Tests](#escribir-tests)
6. [Fixtures](#fixtures)
7. [Mocking](#mocking)
8. [Cobertura de Código](#cobertura-de-código)
9. [CI/CD](#cicd)
10. [Troubleshooting](#troubleshooting)

---

## 🎯 Introducción

Esta aplicación usa **pytest** como framework de testing. Los tests garantizan que:

- ✅ El código funciona correctamente
- ✅ Los cambios no rompen funcionalidad existente
- ✅ La seguridad multi-tenant está garantizada
- ✅ La integración con Odoo funciona
- ✅ La API responde correctamente

## 🚀 Configuración Inicial

### 1. Instalar Dependencias

```bash
pip install -r requirements-test.txt
```

Esto instala:
- `pytest`: Framework de testing
- `pytest-flask`: Extensiones para Flask
- `pytest-cov`: Cobertura de código
- `pytest-mock`: Para mockear dependencias
- `pytest-xdist`: Ejecución paralela
- Y más...

### 2. Crear Base de Datos de Test

**IMPORTANTE**: Usa una base de datos DIFERENTE a la de desarrollo.

```bash
# Conectar a PostgreSQL
psql -U postgres

# Crear base de datos de test
CREATE DATABASE gestion_obra_test;

# Salir
\q
```

### 3. Configurar Variables de Entorno

Puedes crear un archivo `.env.test`:

```bash
# .env.test
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/gestion_obra_test
SECRET_KEY=test-secret-key-super-segura
ENCRYPTION_KEY=hIQxMPbaYZ_WxJx4w3d9OaV8gQSNJFnKHQVfQPl7S1k=
CELERY_TASK_ALWAYS_EAGER=true
MAIL_SUPPRESS_SEND=true
TESTING=true
```

## 🏃 Ejecutar Tests

### Todos los tests

```bash
./run_tests.sh
# o directamente:
pytest
```

### Solo tests unitarios (rápidos)

```bash
./run_tests.sh unit
# o:
pytest tests/unit/
```

### Solo tests de integración

```bash
./run_tests.sh integration
# o:
pytest tests/integration/
```

### Tests específicos

```bash
# Todos los tests de autenticación
pytest -k auth

# Test específico por nombre
pytest -k test_login_successful

# Test específico por archivo
pytest tests/integration/test_auth.py::TestLogin::test_login_successful
```

### Con cobertura de código

```bash
./run_tests.sh --cov
# Genera reporte en htmlcov/index.html
```

### Modo verboso (ver cada test)

```bash
pytest -vv
```

### Detener en el primer fallo

```bash
pytest -x
```

### Ejecutar en paralelo (más rápido)

```bash
./run_tests.sh --parallel
# o:
pytest -n auto
```

## 📁 Estructura de Tests

```
tests/
├── __init__.py
├── conftest.py              # Fixtures globales y configuración
│
├── unit/                    # Tests unitarios (rápidos)
│   ├── __init__.py
│   └── test_services.py     # Tests de servicios individuales
│
└── integration/             # Tests de integración (más lentos)
    ├── __init__.py
    ├── test_auth.py         # Tests de autenticación
    ├── test_multitenant.py  # Tests multi-tenant (CRÍTICOS)
    ├── test_fichajes.py     # Tests de fichajes
    ├── test_sync.py         # Tests de sincronización Odoo
    └── test_api.py          # Tests de API REST
```

### Diferencia entre Unit e Integration

**Tests Unitarios (Unit)**:
- Testean funciones/métodos individuales
- Usan mocks para dependencias externas
- Muy rápidos (< 1s)
- No tocan la base de datos (o usan SQLite en memoria)

**Tests de Integración (Integration)**:
- Testean múltiples componentes juntos
- Usan base de datos real (PostgreSQL)
- Más lentos (1-5s por test)
- Simulan flujos completos de usuario

## ✍️ Escribir Tests

### Anatomía de un Test

```python
import pytest
from app.models import User

class TestUsuarios:
    """Agrupa tests relacionados en una clase"""
    
    def test_crear_usuario(self, session, tenant_soltec, company_internal):
        """
        Nombre del test: debe ser descriptivo.
        
        Parámetros:
        - session: fixture que proporciona sesión de BD
        - tenant_soltec: fixture que crea un tenant
        - company_internal: fixture que crea una empresa
        """
        # ARRANGE (Preparar)
        # Configurar el contexto y datos necesarios
        session.execute(f"SET search_path TO {tenant_soltec.schema_name}")
        
        # ACT (Actuar)
        # Ejecutar la acción que quieres testear
        user = User(
            email="nuevo@test.com",
            password_hash="hash",
            role="operario",
            name="Test",
            lastname="User",
            dni="12345678A",
            company_id=company_internal.id,
            active=True
        )
        session.add(user)
        session.commit()
        
        # ASSERT (Afirmar)
        # Verificar que el resultado es el esperado
        assert user.id is not None
        assert user.email == "nuevo@test.com"
        assert user.active == True
```

### Convenciones de Nombres

- Archivos: `test_*.py` (ej: `test_auth.py`)
- Clases: `Test*` (ej: `TestLogin`)
- Funciones: `test_*` (ej: `test_login_successful`)

### Assertions (Afirmaciones)

```python
# Igualdad
assert valor == esperado

# Veracidad
assert condicion
assert not condicion

# Pertenencia
assert item in lista
assert item not in lista

# Excepciones
with pytest.raises(ValueError):
    funcion_que_debe_fallar()

# Comparaciones
assert len(lista) > 0
assert resultado >= 10
```

## 🔧 Fixtures

Los fixtures preparan el entorno para tus tests. Se definen en `conftest.py`.

### Usar Fixtures

```python
def test_algo(session, user_admin, obra_activa):
    # session, user_admin, obra_activa están listos para usar
    assert user_admin.role == "admin"
    assert obra_activa.estado == "En proceso"
```

### Fixtures Disponibles

#### Básicos
- `app`: Aplicación Flask configurada para testing
- `client`: Cliente HTTP para hacer requests
- `session`: Sesión de base de datos
- `db`: Base de datos

#### Tenants
- `tenant_soltec`: Tenant "SOLTEC"
- `tenant_acme`: Tenant "ACME" (para tests multi-tenant)

#### Empresas
- `company_internal`: Empresa interna
- `company_subcontrata`: Empresa subcontratada

#### Usuarios
- `user_admin`: Usuario administrador
- `user_jefe`: Jefe de obra
- `user_rrhh`: Recursos humanos
- `user_operario`: Operario

#### Obras
- `obra_activa`: Obra en estado activo

#### HTTP
- `authenticated_client`: Cliente ya autenticado como admin

### Crear tus propios Fixtures

Agrégalos en `conftest.py`:

```python
@pytest.fixture
def mi_fixture(session):
    """Descripción del fixture"""
    # Preparar
    dato = CrearAlgo()
    session.add(dato)
    session.commit()
    
    # Entregar al test
    yield dato
    
    # Limpieza (opcional)
    session.delete(dato)
    session.commit()
```

## 🎭 Mocking

Mockear = simular componentes externos (APIs, emails, etc.) sin ejecutarlos realmente.

### Mock de Odoo

```python
def test_sync_odoo(mocker):
    # Simular respuesta de Odoo
    mock_adapter = mocker.Mock()
    mock_adapter.get_diff_obras.return_value = {
        'nuevas': [...],
        'actualizadas': [],
        'finalizadas': []
    }
    
    mocker.patch(
        'app.sync.dispatcher.get_sync_adapter',
        return_value=mock_adapter
    )
    
    # Tu código usa el mock en lugar de Odoo real
    adapter = get_sync_adapter()
    diff = adapter.get_diff_obras()
    assert len(diff['nuevas']) > 0
```

### Mock de Email

```python
@patch('app.services.email_service.mail.send')
def test_enviar_email(mock_send):
    # No envía email real, solo simula
    mock_send.return_value = None
    
    enviar_email("test@example.com", "Asunto", "Cuerpo")
    
    # Verificar que se intentó enviar
    assert mock_send.called
```

## 📊 Cobertura de Código

La cobertura mide qué % de tu código está testeado.

### Generar Reporte

```bash
pytest --cov=app --cov-report=html
# Abre: htmlcov/index.html
```

### Interpretar Resultados

```
Name                      Stmts   Miss  Cover
---------------------------------------------
app/__init__.py             50      5    90%
app/models.py              200     20    90%
app/auth/routes.py          80     10    87%
---------------------------------------------
TOTAL                      330     35    89%
```

- **Stmts**: Total de líneas ejecutables
- **Miss**: Líneas NO testeadas
- **Cover**: Porcentaje de cobertura

### Objetivo de Cobertura

- **Crítico**: Auth, Multi-tenant → 90%+
- **Importante**: Services, API → 80%+
- **Deseable**: General → 70%+

### Ver Líneas No Testeadas

```bash
pytest --cov=app --cov-report=term-missing
```

Muestra qué líneas específicas faltan por testear.

## 🔄 CI/CD

### GitHub Actions (Ejemplo)

Crea `.github/workflows/tests.yml`:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:13
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: gestion_obra_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: 3.9
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install -r requirements-test.txt
    
    - name: Run tests
      env:
        TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/gestion_obra_test
        SECRET_KEY: test-secret-key
        ENCRYPTION_KEY: hIQxMPbaYZ_WxJx4w3d9OaV8gQSNJFnKHQVfQPl7S1k=
      run: |
        pytest --cov=app --cov-report=xml
    
    - name: Upload coverage
      uses: codecov/codecov-action@v2
```

## 🔧 Troubleshooting

### Error: "Base de datos no existe"

```bash
# Crear la base de datos
createdb -U postgres gestion_obra_test
```

### Error: "Could not import app"

```bash
# Asegúrate de estar en el directorio raíz
cd /home/app_soctec/project

# Verificar que app está en el PYTHONPATH
export PYTHONPATH=$PYTHONPATH:$(pwd)
```

### Error: "ENCRYPTION_KEY inválida"

La clave debe ser una clave Fernet válida (32 bytes en base64).

Generar una nueva:

```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

### Tests lentos

```bash
# Ejecutar en paralelo
pytest -n auto

# Solo tests rápidos (unitarios)
pytest tests/unit/

# Ver qué tests son más lentos
pytest --durations=10
```

### Error: "SET search_path" falla

Asegúrate de que el schema del tenant existe:

```python
session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {tenant.schema_name}"))
session.commit()
```

## 📖 Recursos Adicionales

- [Documentación de pytest](https://docs.pytest.org/)
- [pytest-flask](https://pytest-flask.readthedocs.io/)
- [Testing Flask Applications](https://flask.palletsprojects.com/en/2.0.x/testing/)

## 🎯 Próximos Pasos

1. ✅ Ejecuta los tests existentes: `./run_tests.sh`
2. ✅ Revisa la cobertura: `pytest --cov=app --cov-report=html`
3. ✅ Escribe tests para funcionalidad nueva antes de implementarla (TDD)
4. ✅ Configura CI/CD para ejecutar tests automáticamente
5. ✅ Apunta a 80%+ de cobertura

---

**¿Preguntas?** Revisa este documento o consulta la documentación de pytest.
