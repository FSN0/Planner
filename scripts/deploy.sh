#!/bin/bash
set -euo pipefail

# =============================================================================
# SignaPlan - Deploy / Update producción
# =============================================================================
# Uso: ./scripts/deploy.sh [--build] [--migrate]
#   --build    Fuerza rebuild de imágenes (por defecto solo si hay cambios)
#   --migrate  Ejecuta migraciones de DB tras el deploy
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

COMPOSE_FILE="docker-compose.prod.yml"
BUILD=false
MIGRATE=true

for arg in "$@"; do
    case $arg in
        --build) BUILD=true ;;
        --migrate) MIGRATE=true ;;
        --no-migrate) MIGRATE=false ;;
    esac
done

print_step() { echo -e "\n${GREEN}[$(date +%H:%M:%S)] ▶ $1${NC}"; }

echo -e "${GREEN}"
echo "╔════════════════════════════════════════╗"
echo "║   SignaPlan - Deploy a Producción      ║"
echo "╚════════════════════════════════════════╝"
echo -e "${NC}"

# --- Verificaciones ---
if [ ! -f .env ]; then
    echo -e "${RED}ERROR: No existe el archivo .env${NC}"
    echo "  cp .env.production.example .env && nano .env"
    exit 1
fi

source .env

for var in SECRET_KEY POSTGRES_PASSWORD ENCRYPTION_KEY SSO_SECRET_KEY; do
    if [ -z "${!var:-}" ]; then
        echo -e "${RED}ERROR: $var no está definida en .env${NC}"
        exit 1
    fi
done

if [ -z "${ODOO_ALTA_APP_URL:-}" ]; then
    echo -e "${YELLOW}AVISO: ODOO_ALTA_APP_URL no definida — el enlace SSO a Alta Odoo no funcionará${NC}"
    echo "  (La app de altas se despliega en otro servidor/dominio del cliente)"
fi

# --- Pull de cambios (si es un repo git) ---
if [ -d .git ]; then
    print_step "Actualizando código desde Git (rama VERSION_SAAS)..."
    git pull --ff-only origin VERSION_SAAS
fi

# --- Brand assets (before image build) ---
print_step "Sincronizando assets de marca (logos_signaplan)..."
bash scripts/sync_brand_assets.sh

# --- Build ---
print_step "Construyendo imágenes..."
if [ "$BUILD" = true ]; then
    docker compose -f $COMPOSE_FILE build --no-cache
else
    docker compose -f $COMPOSE_FILE build
fi

# --- Deploy con zero-downtime (restart escalonado) ---
print_step "Desplegando servicios..."
docker compose -f $COMPOSE_FILE up -d --remove-orphans

# --- Migraciones ---
if [ "$MIGRATE" = true ]; then
    print_step "Preparando migraciones..."
    bash scripts/fix_migration_heads.sh
    print_step "Reconstruyendo imagen web (migraciones van dentro de la imagen)..."
    docker compose -f $COMPOSE_FILE build web
    print_step "Ejecutando migraciones de base de datos..."
    docker compose -f $COMPOSE_FILE run --rm --no-deps web flask db upgrade
fi

# --- Limpieza ---
print_step "Limpiando imágenes antiguas..."
docker image prune -f

# --- Verificación ---
print_step "Verificando estado de los servicios..."
sleep 5
docker compose -f $COMPOSE_FILE ps

# --- Smoke tests ---
print_step "Ejecutando smoke tests..."
COMPOSE_FILE=$COMPOSE_FILE bash scripts/smoke-test.sh "${DOMAIN:-signaplan.com}"

echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  Deploy completado.${NC}"
echo ""
echo "  Panel:  https://${DOMAIN:-signaplan.com}/superadmin"
echo "  Logs:   docker compose -f $COMPOSE_FILE logs -f"
echo "  Estado: docker compose -f $COMPOSE_FILE ps"
echo -e "${GREEN}════════════════════════════════════════${NC}"
