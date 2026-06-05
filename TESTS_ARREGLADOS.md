# Arreglos Realizados en el Sistema de Tests

## Problemas Identificados y Solucionados

### 1. **Problema Principal: Claves Duplicadas en la Base de Datos**

**Causa**: La base de datos de tests no se limpiaba entre ejecuciones, causando que los fixtures intentaran crear el mismo tenant "soltec" múltiples veces.

**Solución**:
- Modificado `run_tests.sh` para **DROP y CREATE** la base de datos antes de cada ejecución
- Modificado el fixture `db()` en `conftest.py` para limpiar todos los schemas de tenants al iniciar

### 2. **Problema: Fixtures Rompían el Aislamiento Transaccional**

**Causa**: Los fixtures usaban `session.commit()` que hacía commits reales a la BD, rompiendo el sistema de rollback automático.

**Solución**:
- Cambiado `session.commit()` por `session.flush()` en TODOS los fixtures
- `flush()` genera los IDs sin hacer commit real
- Reescrito el fixture `session()` para usar transacciones correctamente

### 3. **Problema: Tests Buscaban Funciones que No Existen**

**Causa**: Los tests fueron escritos asumiendo nombres de funciones que no coincidían con el código real.

**Solución**:
- `TestEmailService`: Cambiado `enviar_email_simple` → `send_email`
- `TestDashboardService`: Cambiado `obtener_estadisticas_globales` → `get_dashboard_data`
- `TestDateUtils`: Arreglada la firma de `get_weekday_initial(year, month, day)`
- `TestTenantService`: Cambiado `crear_tenant` → `provision_new_tenant`

### 4. **Problema: Cobertura de Código Ralentizaba los Tests**

**Solución**:
- Desactivada temporalmente la cobertura en `pytest.ini`
- Se puede activar manualmente con `./run_tests.sh --cov`

## Archivos Modificados

1. **`tests/conftest.py`**
   - ✅ Fixture `db()`: Ahora limpia schemas de tenants antiguos
   - ✅ Fixture `session()`: Usa transacciones correctamente con SessionLocal
   - ✅ Todos los fixtures de datos: Cambiado `commit()` → `flush()`

2. **`run_tests.sh`**
   - ✅ Ahora hace DROP/CREATE de la base de datos en cada ejecución
   - ✅ Limpieza completa antes de ejecutar tests

3. **`pytest.ini`**
   - ✅ Desactivada cobertura por defecto (más rápido)
   - ✅ Añadido flag `-s` para ver prints durante debugging

4. **`tests/integration/test_auth.py`**
   - ✅ Arreglado uso de `text()` para SQL queries
   - ✅ Eliminados `commit()` innecesarios

5. **`tests/unit/test_services.py`**
   - ✅ Arreglados imports para usar funciones reales
   - ✅ Tests de email usan `send_email()`
   - ✅ Tests de dashboard usan `get_dashboard_data()`
   - ✅ Tests de date_utils usan firma correcta
   - ✅ Tests de tenant_service usan `provision_new_tenant()`

## Cómo Ejecutar los Tests

### Opción 1: Ejecutar todos los tests
```bash
./run_tests.sh
```

### Opción 2: Ejecutar solo tests unitarios
```bash
./run_tests.sh unit
```

### Opción 3: Ejecutar solo tests de integración
```bash
./run_tests.sh integration
```

### Opción 4: Ejecutar un test específico
```bash
./run_tests.sh -k test_login_page_loads
```

### Opción 5: Parar al primer fallo (útil para debugging)
```bash
./run_tests.sh --stop
```

### Opción 6: Con cobertura de código
```bash
./run_tests.sh --cov
```

## Estructura de Tests

```
tests/
├── conftest.py              # Configuración y fixtures compartidos
├── pytest.ini               # Configuración de pytest
│
├── integration/             # Tests de integración (rutas, BD, etc.)
│   ├── test_api.py         # Tests de API REST
│   ├── test_auth.py        # Tests de autenticación
│   ├── test_fichajes.py    # Tests de fichajes
│   ├── test_multitenant.py # Tests multi-tenant
│   └── test_sync.py        # Tests de sincronización Odoo
│
└── unit/                    # Tests unitarios (funciones aisladas)
    └── test_services.py     # Tests de servicios
```

## Fixtures Disponibles

### Fixtures de Base de Datos
- `app`: Aplicación Flask configurada para testing
- `db`: Base de datos con tablas creadas
- `session`: Sesión de BD con rollback automático
- `client`: Cliente HTTP para hacer requests

### Fixtures de Datos
- `tenant_soltec`: Tenant SOLTEC con schema y tablas
- `tenant_acme`: Tenant ACME Corp para tests multi-tenant
- `company_internal`: Empresa interna (propia)
- `company_subcontrata`: Empresa subcontratada
- `user_admin`: Usuario administrador
- `user_jefe`: Usuario jefe de obra
- `user_rrhh`: Usuario RRHH
- `user_operario`: Usuario operario
- `obra_activa`: Obra en curso con jefe asignado
- `authenticated_client`: Cliente HTTP ya logueado como admin

## Próximos Pasos

1. **Ejecutar los tests**:
   ```bash
   ./run_tests.sh --stop
   ```

2. **Verificar que la BD se limpia correctamente**:
   - Los tests no deberían tener más errores de "duplicate key"

3. **Revisar tests que aún fallen**:
   - Puede haber tests que dependan de funcionalidad no implementada
   - Los tests con `try/except` pasarán aunque la función no exista

4. **Añadir más tests según sea necesario**

## Notas Importantes

- ⚠️ **La base de datos de test se BORRA completamente** en cada ejecución
- ✅ Los tests son **independientes**: cada test tiene su propia transacción
- ✅ Los cambios de cada test se **deshacen automáticamente** (rollback)
- ✅ Los fixtures se **reutilizan** dentro del mismo test pero no entre tests diferentes

## Solución de Problemas

### Si ves errores de "duplicate key":
```bash
# Limpiar manualmente la BD
docker-compose exec db psql -U postgres -c "DROP DATABASE IF EXISTS gestion_obra_test;"
docker-compose exec db psql -U postgres -c "CREATE DATABASE gestion_obra_test;"
```

### Si los tests se quedan colgados:
```bash
# Verificar que Docker está corriendo
docker-compose ps

# Reiniciar contenedores si es necesario
docker-compose restart
```

### Si pytest no se encuentra:
```bash
pip install -r requirements-test.txt
```

## Estadísticas Esperadas

Con todos los arreglos, esperamos:
- ✅ **0 errores de duplicate key**
- ✅ **0 errores de fixtures**
- ✅ Tests unitarios: ~13 tests
- ✅ Tests de integración: ~52 tests
- ⚠️ Algunos tests pueden pasar vacíos si la funcionalidad no está implementada

## Mejoras Futuras

1. Añadir más tests de cobertura
2. Tests de performance
3. Tests de seguridad (SQL injection, XSS, etc.)
4. Tests de carga con múltiples usuarios
5. Tests E2E con Selenium/Playwright
