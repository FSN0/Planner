#!/bin/bash
set -uo pipefail

# =============================================================================
# SignaPlan - Smoke Tests (Post-deploy verification)
# =============================================================================
# Verifica que todos los servicios están funcionando correctamente.
# Seguro para ejecutar en PRODUCCIÓN (solo lectura, no modifica datos).
#
# Uso: ./scripts/smoke-test.sh [dominio]
#   Ejemplo: ./scripts/smoke-test.sh signaplan.com
#            ./scripts/smoke-test.sh localhost
# =============================================================================

DOMAIN="${1:-localhost}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PASSED=0
FAILED=0

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

check() {
    local description="$1"
    local command="$2"

    if eval "$command" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $description"
        ((PASSED++))
    else
        echo -e "  ${RED}✗${NC} $description"
        ((FAILED++))
    fi
}

echo ""
echo -e "${YELLOW}╔════════════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}║     SignaPlan - Smoke Tests (Producción)       ║${NC}"
echo -e "${YELLOW}╚════════════════════════════════════════════════╝${NC}"
echo ""

# --- 1. SERVICIOS DOCKER ---
echo -e "${YELLOW}[1/4] Servicios Docker${NC}"
check "PostgreSQL está healthy" \
    "docker compose -f $COMPOSE_FILE exec -T db pg_isready -U postgres"

check "Redis responde" \
    "docker compose -f $COMPOSE_FILE exec -T redis redis-cli ping | grep -q PONG"

check "Web container está corriendo" \
    "docker compose -f $COMPOSE_FILE ps web | grep -q 'running\|Up'"

check "Celery worker está corriendo" \
    "docker compose -f $COMPOSE_FILE ps celery_worker | grep -q 'running\|Up'"

check "Celery beat está corriendo" \
    "docker compose -f $COMPOSE_FILE ps celery_beat | grep -q 'running\|Up'"

check "Caddy está corriendo" \
    "docker compose -f $COMPOSE_FILE ps caddy | grep -q 'running\|Up'"

# --- 2. CONECTIVIDAD HTTP ---
echo ""
echo -e "${YELLOW}[2/4] Endpoints HTTP${NC}"

if [ "$DOMAIN" = "localhost" ]; then
    BASE_URL="http://localhost"
else
    BASE_URL="https://$DOMAIN"
fi

check "Login page responde (200 o redirect)" \
    "curl -sS -o /dev/null -w '%{http_code}' -L ${BASE_URL}/auth/login | grep -qE '200|302'"

check "Static assets accesibles" \
    "curl -sSf -o /dev/null ${BASE_URL}/static/css/styles.css"

check "Superadmin responde" \
    "curl -sS -o /dev/null -w '%{http_code}' ${BASE_URL}/superadmin/ | grep -qE '200|401'"

check "API check-domain responde" \
    "curl -sSf -o /dev/null -w '%{http_code}' '${BASE_URL}/api/v6/check-domain?domain=${DOMAIN}' | grep -qE '200|404'"

# --- 3. BASE DE DATOS ---
echo ""
echo -e "${YELLOW}[3/4] Base de datos${NC}"

check "Tabla 'tenants' existe" \
    "docker compose -f $COMPOSE_FILE exec -T db psql -U postgres -d gestion_obra_saas -c 'SELECT count(*) FROM public.tenants;'"

check "Tabla 'users' existe" \
    "docker compose -f $COMPOSE_FILE exec -T db psql -U postgres -d gestion_obra_saas -c 'SELECT count(*) FROM users;'"

check "Migraciones aplicadas (alembic_version)" \
    "docker compose -f $COMPOSE_FILE exec -T db psql -U postgres -d gestion_obra_saas -c 'SELECT version_num FROM alembic_version;'"

# --- 4. CERTIFICADOS TLS (solo si no es localhost) ---
echo ""
echo -e "${YELLOW}[4/4] TLS / HTTPS${NC}"

if [ "$DOMAIN" != "localhost" ]; then
    check "Certificado SSL válido para $DOMAIN" \
        "curl -sSf https://$DOMAIN -o /dev/null"

    check "Redirect HTTP → HTTPS" \
        "curl -sI http://$DOMAIN | grep -qi 'location.*https'"
else
    echo -e "  ${YELLOW}→${NC} Saltando (localhost no usa HTTPS)"
fi

# --- RESUMEN ---
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
TOTAL=$((PASSED + FAILED))

if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}  ✓ TODOS LOS CHECKS PASARON ($PASSED/$TOTAL)${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}  ✗ $FAILED CHECKS FALLARON ($PASSED/$TOTAL pasaron)${NC}"
    echo ""
    exit 1
fi
