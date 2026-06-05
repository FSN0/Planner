# ARREGLO FINAL - Sistema de Tests Simplificado

## Problema Principal Identificado

```python
AttributeError: 'Session' object has no attribute 'remove'
TypeError: 'Session' object is not callable
```

**Causa Raíz**: Estaba intentando reemplazar `db.session` (un `scoped_session` de Flask-SQLAlchemy) con una `Session` normal, rompiendo toda la funcionalidad de Flask-SQLAlchemy.

## Solución Aplicada

### 1. Simplificado el Fixture `session`

**ANTES** (Roto):
```python
@pytest.fixture(scope='function')
def session(db, app):
    with app.app_context():
        connection = db.engine.connect()
        transaction = connection.begin()
        SessionLocal = sessionmaker(bind=connection)
        session = SessionLocal()
        
        db.session = session  # ❌ ESTO ROMPÍA TODO
        
        yield session
```

**AHORA** (Funciona):
```python
@pytest.fixture(scope='function')
def session(db, app):
    with app.app_context():
        # Usar la sesión de Flask-SQLAlchemy directamente
        session = db.session
        
        session.execute(text("SET search_path TO public"))
        
        yield session
        
        # Limpieza: rollback y remove
        session.rollback()
        session.remove()
```

### 2. Arreglado Fixture `db`

Añadido `with app.app_context()` al inicio para asegurar que todo se ejecuta en el contexto correcto.

### 3. Arreglado Test de Asignaciones

**Problema**: El modelo `Asignacion` solo tiene el campo `fecha`, no `fecha_inicio` ni `fecha_fin`.

**ANTES**:
```python
asig1 = Asignacion(
    user_id=user_operario.id,
    obra_id=obra_activa.id,
    fecha_inicio=date(2024, 1, 1),  # ❌ No existe
    fecha_fin=date(2024, 1, 10),    # ❌ No existe
    estado='activa'                 # ❌ No existe
)
```

**AHORA**:
```python
asig1 = Asignacion(
    user_id=user_operario.id,
    obra_id=obra_activa.id,
    fecha=date(2024, 1, 1)  # ✅ Campo correcto
)
```

## Cambios Aplicados

1. **`tests/conftest.py`**
   - ✅ Simplificado fixture `session` - ya no reemplaza `db.session`
   - ✅ Arreglado fixture `db` - añadido context manager
   - ✅ Mantiene fixtures `_tenant_schemas`, `tenant_soltec`, `tenant_acme`

2. **`tests/unit/test_services.py`**
   - ✅ Arreglado `test_check_assignment_overlap` - usa campos correctos del modelo
   - ✅ Ahora prueba la restricción de unique constraint

## Ejecuta Ahora

```bash
./run_tests.sh unit
```

**Deberías ver**: Al menos 3-4 tests PASSED (los que no dependen de la app context problemática).

Los tests que usan `with app.app_context():` dentro pueden aún fallar porque están creando contextos anidados, pero el sistema básico ahora funciona.

## Tests que DEBERÍAN Pasar Ahora

1. ✅ `TestEmailService::test_send_email_success`
2. ✅ `TestEmailService::test_send_email_handles_failure`  
3. ✅ `TestTenantService::test_validate_schema_name_security`

## Tests que Pueden Seguir Fallando

Los tests que hacen `with app.app_context():` DENTRO del test están creando contextos anidados que pueden causar el error de `session.remove()`.

**Solución**: Quitar el `with app.app_context():` de dentro de esos tests, ya que el fixture `session` ya proporciona el contexto.

¿Quieres que arregle esos tests también?
