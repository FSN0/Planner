#!/bin/bash
set -euo pipefail

# =============================================================================
# SignaPlan - Restaurar backup
# =============================================================================
# Uso: ./scripts/restore.sh YYYYMMDD_HHMMSS
# =============================================================================

BACKUP_DIR="./backups"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ -z "${1:-}" ]; then
    echo "Uso: $0 TIMESTAMP"
    echo ""
    echo "Backups disponibles:"
    ls -1 "$BACKUP_DIR"/db_*.sql.gz 2>/dev/null | \
        sed 's|.*/db_||; s|\.sql\.gz||' | \
        sort -r
    exit 1
fi

TIMESTAMP="$1"
DB_FILE="$BACKUP_DIR/db_${TIMESTAMP}.sql.gz"
UPLOADS_FILE="$BACKUP_DIR/uploads_${TIMESTAMP}.tar.gz"

# --- Verificaciones ---
if [ ! -f "$DB_FILE" ]; then
    echo -e "${RED}ERROR: No existe $DB_FILE${NC}"
    exit 1
fi

echo -e "${RED}════════════════════════════════════════════════════════════${NC}"
echo -e "${RED}  ATENCIÓN: Vas a restaurar el backup del $TIMESTAMP${NC}"
echo -e "${RED}  Esto SOBREESCRIBIRÁ todos los datos actuales.${NC}"
echo -e "${RED}════════════════════════════════════════════════════════════${NC}"
echo ""
read -p "¿Continuar? (escribe 'si' para confirmar): " CONFIRM

if [ "$CONFIRM" != "si" ]; then
    echo "Cancelado."
    exit 0
fi

# --- Parar web y workers ---
echo -e "${YELLOW}[1/4] Deteniendo aplicación...${NC}"
docker compose -f "$COMPOSE_FILE" stop web celery_worker celery_beat

# --- Restaurar DB ---
echo -e "${YELLOW}[2/4] Restaurando base de datos...${NC}"
docker compose -f "$COMPOSE_FILE" exec -T db \
    psql -U postgres -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" gestion_obra_saas

gunzip -c "$DB_FILE" | docker compose -f "$COMPOSE_FILE" exec -T db \
    psql -U postgres gestion_obra_saas > /dev/null 2>&1

echo "      → Base de datos restaurada"

# --- Restaurar uploads ---
if [ -f "$UPLOADS_FILE" ]; then
    echo -e "${YELLOW}[3/4] Restaurando uploads...${NC}"
    docker compose -f "$COMPOSE_FILE" exec -T web rm -rf /app/uploads/*
    cat "$UPLOADS_FILE" | docker compose -f "$COMPOSE_FILE" exec -T web tar -xzf - -C /app
    echo "      → Uploads restaurados"
else
    echo -e "${YELLOW}[3/4] Sin archivo de uploads (saltando)${NC}"
fi

# --- Arrancar servicios ---
echo -e "${YELLOW}[4/4] Arrancando servicios...${NC}"
docker compose -f "$COMPOSE_FILE" start web celery_worker celery_beat

echo ""
echo -e "${GREEN}✓ Restauración completada exitosamente${NC}"
echo "  Verificar: docker compose -f $COMPOSE_FILE ps"
