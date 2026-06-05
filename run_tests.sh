#!/bin/bash
# Script mejorado para ejecutar tests con Docker

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}╔════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}║     SUITE DE TESTS - GESTION OBRA      ║${NC}"
echo -e "${YELLOW}╚════════════════════════════════════════╝${NC}"
echo ""

# [1/5] Detectar entorno
echo -e "${YELLOW}[1/5] Detectando entorno...${NC}"

# Verificar si hay docker-compose corriendo
if docker-compose ps | grep -q "db.*Up"; then
    echo "✓ Docker detectado - usando base de datos en contenedor"
    USE_DOCKER=true
    
    # Obtener contraseña de .env o usar por defecto
    if [ -f .env ]; then
        source .env
        DB_PASSWORD=${POSTGRES_PASSWORD:-postgres}
    else
        echo -e "${YELLOW}⚠ Archivo .env no encontrado, usando contraseña por defecto${NC}"
        DB_PASSWORD="postgres"
    fi
    
    # URL para conectar al contenedor desde fuera
    export TEST_DATABASE_URL="postgresql://postgres:${DB_PASSWORD}@localhost:5432/gestion_obra_test"
    DB_CONTAINER="project-db-1"
    
else
    echo "✓ PostgreSQL local detectado"
    USE_DOCKER=false
    export TEST_DATABASE_URL=${TEST_DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/gestion_obra_test}
fi

# Variables de entorno para tests
export FLASK_ENV=testing
export TESTING=true
export SECRET_KEY='test-secret-key-super-segura-para-tests'
export ENCRYPTION_KEY='hIQxMPbaYZ_WxJx4w3d9OaV8gQSNJFnKHQVfQPl7S1k='
export CELERY_TASK_ALWAYS_EAGER=true
export MAIL_SUPPRESS_SEND=true

echo "✓ Variables de entorno configuradas"

# [2/5] Verificar pytest
echo ""
echo -e "${YELLOW}[2/5] Verificando pytest...${NC}"

if ! python3 -m pytest --version &> /dev/null; then
    echo -e "${RED}✗ pytest no está instalado${NC}"
    echo "Instalando dependencias de test..."
    pip install -r requirements-test.txt
fi

echo -e "${GREEN}✓ pytest encontrado${NC}"

# [3/5] Crear y limpiar base de datos de test
echo ""
echo -e "${YELLOW}[3/5] Preparando base de datos de test...${NC}"

if [ "$USE_DOCKER" = true ]; then
    echo "→ Preparando base de datos en contenedor Docker..."
    
    # Verificar que el contenedor está corriendo
    if ! docker ps --format '{{.Names}}' | grep -q "db"; then
        echo -e "${RED}✗ Contenedor de PostgreSQL no está corriendo${NC}"
        echo "Iniciando contenedor..."
        docker-compose up -d db
        echo "Esperando que PostgreSQL esté listo..."
        sleep 5
    fi
    
    # Eliminar base de datos si existe y crearla de nuevo (limpieza completa)
    echo "→ Limpiando y recreando base de datos..."
    docker-compose exec -T db psql -U postgres -c "DROP DATABASE IF EXISTS gestion_obra_test;" 2>/dev/null || true
    docker-compose exec -T db psql -U postgres -c "CREATE DATABASE gestion_obra_test;"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Base de datos de test limpia y lista${NC}"
    else
        echo -e "${RED}✗ Error preparando base de datos${NC}"
        exit 1
    fi
    
else
    # PostgreSQL local
    DB_NAME="gestion_obra_test"
    
    if command -v psql &> /dev/null; then
        echo "→ Limpiando y recreando base de datos $DB_NAME..."
        PGPASSWORD=postgres psql -h localhost -U postgres -c "DROP DATABASE IF EXISTS $DB_NAME;" 2>/dev/null || true
        PGPASSWORD=postgres psql -h localhost -U postgres -c "CREATE DATABASE $DB_NAME;"
        echo -e "${GREEN}✓ Base de datos de test limpia y lista${NC}"
    else
        echo -e "${YELLOW}⚠ psql no encontrado. Asegúrate de que la BD existe.${NC}"
    fi
fi

# [4/5] Determinar qué tests ejecutar
echo ""
echo -e "${YELLOW}[4/5] Determinando tests a ejecutar...${NC}"

TEST_PATH="tests/"
PYTEST_ARGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        unit)
            TEST_PATH="tests/unit/"
            echo "→ Ejecutando solo tests unitarios"
            ;;
        integration)
            TEST_PATH="tests/integration/"
            echo "→ Ejecutando solo tests de integración"
            ;;
        --parallel|-n)
            PYTEST_ARGS="$PYTEST_ARGS -n auto"
            echo "→ Modo paralelo activado"
            ;;
        --cov)
            PYTEST_ARGS="$PYTEST_ARGS --cov=app --cov-report=html --cov-report=term"
            echo "→ Reporte de cobertura activado"
            ;;
        -k)
            PYTEST_ARGS="$PYTEST_ARGS -k $2"
            echo "→ Filtrando tests: $2"
            shift
            ;;
        --verbose|-v)
            PYTEST_ARGS="$PYTEST_ARGS -vv"
            echo "→ Modo verboso activado"
            ;;
        --stop)
            PYTEST_ARGS="$PYTEST_ARGS -x"
            echo "→ Detendrá en el primer fallo"
            ;;
        --help|-h)
            echo "Uso: ./run_tests.sh [OPTIONS]"
            echo ""
            echo "Opciones:"
            echo "  unit              Ejecuta solo tests unitarios"
            echo "  integration       Ejecuta solo tests de integración"
            echo "  --parallel, -n    Ejecuta tests en paralelo"
            echo "  --cov             Genera reporte de cobertura"
            echo "  -k EXPRESION      Filtra tests por nombre"
            echo "  --verbose, -v     Modo verboso"
            echo "  --stop            Detiene en el primer fallo"
            echo "  --help, -h        Muestra esta ayuda"
            exit 0
            ;;
        *)
            PYTEST_ARGS="$PYTEST_ARGS $1"
            ;;
    esac
    shift
done

echo "→ Ejecutando todos los tests"

# [5/5] Ejecutar tests
echo ""
echo -e "${YELLOW}[5/5] Ejecutando tests...${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 -m pytest $TEST_PATH $PYTEST_ARGS

TEST_EXIT_CODE=$?

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ TODOS LOS TESTS PASARON${NC}"
    echo ""
    
    if [[ $PYTEST_ARGS == *"--cov"* ]]; then
        echo -e "📊 Reporte de cobertura generado en: ${YELLOW}htmlcov/index.html${NC}"
    fi
    
    exit 0
else
    echo -e "${RED}✗ ALGUNOS TESTS FALLARON${NC}"
    echo ""
    echo "Tip: Ejecuta con --verbose para ver más detalles"
    exit 1
fi
