#!/bin/bash
set -euo pipefail

# =============================================================================
# SignaPlan - Restaurar backup
# =============================================================================
# Uso: COMPOSE_FILE=docker-compose.yml ./scripts/restore.sh YYYYMMDD_HHMMSS
# =============================================================================

BACKUP_DIR="./backups"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
DB_NAME="${DB_NAME:-gestion_obra_saas}"

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
echo -e "${RED}  Compose: $COMPOSE_FILE${NC}"
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

# --- Wipe completa (public + todos los tenant_*) ---
# pg_dump --clean no usa CASCADE: si hay tablas nuevas (p.ej. etiquetas) que
# no estaban en el backup, los DROP fallan y el restore queda a medias.
echo -e "${YELLOW}[2/4] Restaurando base de datos...${NC}"
docker compose -f "$COMPOSE_FILE" exec -T db \
    psql -U postgres -v ON_ERROR_STOP=1 -d postgres <<EOF
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS ${DB_NAME};
CREATE DATABASE ${DB_NAME} OWNER postgres;
EOF

RESTORE_LOG=$(mktemp)
if ! gunzip -c "$DB_FILE" | docker compose -f "$COMPOSE_FILE" exec -T db \
    psql -U postgres -v ON_ERROR_STOP=1 "$DB_NAME" >"$RESTORE_LOG" 2>&1; then
    echo -e "${RED}ERROR: falló la restauración SQL. Últimas líneas:${NC}"
    tail -n 40 "$RESTORE_LOG"
    rm -f "$RESTORE_LOG"
    exit 1
fi
rm -f "$RESTORE_LOG"
echo "      → Base de datos restaurada"

# --- Restaurar uploads ---
# El tar guarda `uploads/...`. No se extrae sobre `/app` porque `uploads` es un
# volumen montado y tar falla al intentar cambiarle modo/mtime al mount point.
if [ -f "$UPLOADS_FILE" ]; then
    echo -e "${YELLOW}[3/4] Restaurando uploads...${NC}"
    docker compose -f "$COMPOSE_FILE" start web
    sleep 2
    docker compose -f "$COMPOSE_FILE" exec -T web \
        sh -c 'find /app/uploads -mindepth 1 -maxdepth 1 -exec rm -rf {} +'
    cat "$UPLOADS_FILE" | docker compose -f "$COMPOSE_FILE" exec -T web \
        tar -xzf - -C /app/uploads --strip-components=1 --no-same-owner --no-same-permissions
    docker compose -f "$COMPOSE_FILE" stop web
    echo "      → Uploads restaurados"
else
    echo -e "${YELLOW}[3/4] Sin archivo de uploads (saltando)${NC}"
fi

# --- Arrancar servicios ---
echo -e "${YELLOW}[4/4] Arrancando servicios...${NC}"
docker compose -f "$COMPOSE_FILE" start web celery_worker celery_beat

echo ""
echo -e "${GREEN}✓ Restauración completada exitosamente${NC}"
echo "  Si el backup es anterior a migraciones recientes: make migrate"
echo "  Verificar: docker compose -f $COMPOSE_FILE ps"
