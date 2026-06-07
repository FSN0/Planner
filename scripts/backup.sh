#!/bin/bash
set -euo pipefail

# =============================================================================
# SignaPlan - Backup de base de datos y uploads
# =============================================================================
# Uso: ./scripts/backup.sh
# Genera: backups/db_YYYYMMDD_HHMMSS.sql.gz + backups/uploads_YYYYMMDD_HHMMSS.tar.gz
# =============================================================================

BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

mkdir -p "$BACKUP_DIR"

echo -e "${GREEN}[Backup] Iniciando backup - $TIMESTAMP${NC}"

# --- Base de datos ---
echo -e "${YELLOW}[1/2] Exportando base de datos...${NC}"
docker compose -f "$COMPOSE_FILE" exec -T db \
    pg_dump -U postgres --clean --if-exists gestion_obra_saas | \
    gzip > "$BACKUP_DIR/db_${TIMESTAMP}.sql.gz"

DB_SIZE=$(du -sh "$BACKUP_DIR/db_${TIMESTAMP}.sql.gz" | cut -f1)
echo "      → db_${TIMESTAMP}.sql.gz ($DB_SIZE)"

# --- Uploads ---
echo -e "${YELLOW}[2/2] Comprimiendo uploads...${NC}"
UPLOADS_VOLUME=$(docker compose -f "$COMPOSE_FILE" exec -T web find /app/uploads -maxdepth 0 -type d 2>/dev/null && echo "exists" || echo "")

if [ -n "$UPLOADS_VOLUME" ]; then
    docker compose -f "$COMPOSE_FILE" exec -T web tar -czf - -C /app uploads > "$BACKUP_DIR/uploads_${TIMESTAMP}.tar.gz"
    UPLOADS_SIZE=$(du -sh "$BACKUP_DIR/uploads_${TIMESTAMP}.tar.gz" | cut -f1)
    echo "      → uploads_${TIMESTAMP}.tar.gz ($UPLOADS_SIZE)"
else
    echo "      → Sin carpeta uploads (saltando)"
fi

# --- Limpiar backups antiguos (>30 días) ---
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +30 -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete 2>/dev/null || true

echo ""
echo -e "${GREEN}✓ Backup completado: $BACKUP_DIR/*_${TIMESTAMP}.*${NC}"
echo "  Para restaurar: ./scripts/restore.sh $TIMESTAMP"
