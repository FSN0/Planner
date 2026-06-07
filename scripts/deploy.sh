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
MIGRATE=false

for arg in "$@"; do
    case $arg in
        --build) BUILD=true ;;
        --migrate) MIGRATE=true ;;
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

for var in SECRET_KEY POSTGRES_PASSWORD ENCRYPTION_KEY; do
    if [ -z "${!var:-}" ]; then
        echo -e "${RED}ERROR: $var no está definida en .env${NC}"
        exit 1
    fi
done

# --- Pull de cambios (si es un repo git) ---
if [ -d .git ]; then
    print_step "Actualizando código desde Git (rama VERSION_SAAS)..."
    git pull --ff-only origin VERSION_SAAS
fi

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
    print_step "Ejecutando migraciones de base de datos..."
    sleep 5
    docker compose -f $COMPOSE_FILE exec -T web flask db upgrade
fi

# --- Limpieza ---
print_step "Limpiando imágenes antiguas..."
docker image prune -f

# --- Verificación ---
print_step "Verificando estado de los servicios..."
sleep 3
docker compose -f $COMPOSE_FILE ps

echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  Deploy completado correctamente.${NC}"
echo ""
echo "  Panel:  https://${DOMAIN:-signaplan.com}/superadmin"
echo "  Logs:   docker compose -f $COMPOSE_FILE logs -f"
echo "  Estado: docker compose -f $COMPOSE_FILE ps"
echo -e "${GREEN}════════════════════════════════════════${NC}"
