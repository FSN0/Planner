#!/bin/bash
# Provisiona agent_readonly con SELECT a TODO tenant_soltec + streams_json completo.
# Lo llama scripts/deploy.sh. También: make agent-readonly
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SQL_SRC="docs/sql/planner_agent_readonly.sql"
OUT_FILE="docs/sql/CONECTOR_AGENTE.txt"
STREAMS_OUT="docs/sql/planner_agent_streams.json"
GEN_PY="scripts/generate_agent_streams.py"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ ! -f .env ]; then
  echo -e "${RED}ERROR: falta .env${NC}"
  exit 1
fi

get_env() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" .env | tail -1 || true)"
  if [ -z "$line" ]; then
    echo ""
    return
  fi
  echo "${line#*=}" | sed 's/^["'\'']//;s/["'\'']$//'
}

AGENT_READONLY_PASSWORD="$(get_env AGENT_READONLY_PASSWORD)"
AGENT_READONLY_DB_PORT="$(get_env AGENT_READONLY_DB_PORT)"
AGENT_READONLY_DB_BIND="$(get_env AGENT_READONLY_DB_BIND)"
DOMAIN="$(get_env DOMAIN)"
TENANT_HOST_ALIASES="$(get_env TENANT_HOST_ALIASES)"

AGENT_READONLY_DB_PORT="${AGENT_READONLY_DB_PORT:-54329}"
AGENT_READONLY_DB_BIND="${AGENT_READONLY_DB_BIND:-0.0.0.0}"

if [ -z "$AGENT_READONLY_PASSWORD" ]; then
  AGENT_READONLY_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 28)"
  {
    echo ""
    echo "# Generado por ensure_agent_readonly.sh ($(date -Iseconds))"
    echo "AGENT_READONLY_PASSWORD=${AGENT_READONLY_PASSWORD}"
  } >> .env
  echo -e "${YELLOW}Generada AGENT_READONLY_PASSWORD y guardada en .env${NC}"
fi

# Host solo para el txt del conector (el agente lo necesita; SignaPlan no).
CONNECTOR_HOST="$(get_env AGENT_CONNECTOR_DB_HOST)"
if [ -z "$CONNECTOR_HOST" ] && [ -n "$TENANT_HOST_ALIASES" ]; then
  CONNECTOR_HOST="$(echo "$TENANT_HOST_ALIASES" | tr ',' '\n' | grep '\.' | head -1 | tr -d ' ' || true)"
fi
CONNECTOR_HOST="${CONNECTOR_HOST:-$DOMAIN}"
CONNECTOR_HOST="${CONNECTOR_HOST:-<IP_O_DNS_PUBLICO_DE_ESTE_SERVIDOR>}"

if [ ! -f "$SQL_SRC" ]; then
  echo -e "${RED}ERROR: no está $SQL_SRC${NC}"
  exit 1
fi

echo "Esperando Postgres..."
for i in $(seq 1 30); do
  if docker compose -f "$COMPOSE_FILE" exec -T db pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 2
  if [ "$i" -eq 30 ]; then
    echo -e "${RED}ERROR: db no responde${NC}"
    exit 1
  fi
done

if ! docker compose -f "$COMPOSE_FILE" exec -T db \
    psql -U postgres -d gestion_obra_saas -Atc \
    "SELECT 1 FROM pg_namespace WHERE nspname='tenant_soltec'" | grep -q 1; then
  echo -e "${YELLOW}AVISO: aún no existe tenant_soltec — se omite agent_readonly hasta el próximo deploy${NC}"
  exit 0
fi

TMP="$(mktemp)"
export AGENT_READONLY_PASSWORD SQL_SRC TMP
python3 - <<'PY'
import os
from pathlib import Path
pw = os.environ["AGENT_READONLY_PASSWORD"].replace("'", "''")
text = Path(os.environ["SQL_SRC"]).read_text(encoding="utf-8")
Path(os.environ["TMP"]).write_text(text.replace("CAMBIAR_PASSWORD_RO", pw), encoding="utf-8")
PY

echo "Aplicando grants SELECT a TODO tenant_soltec..."
docker compose -f "$COMPOSE_FILE" exec -T db \
  psql -U postgres -d gestion_obra_saas -v ON_ERROR_STOP=1 < "$TMP"
rm -f "$TMP"

docker compose -f "$COMPOSE_FILE" exec -T db \
  psql -U postgres -d gestion_obra_saas -v ON_ERROR_STOP=1 \
  -c "ALTER ROLE agent_readonly WITH LOGIN PASSWORD '${AGENT_READONLY_PASSWORD}';"

echo "Generando streams_json de todas las tablas..."
COLS="$(docker compose -f "$COMPOSE_FILE" exec -T db \
  psql -U postgres -d gestion_obra_saas -At -F '|' <<'SQL'
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'tenant_soltec'
ORDER BY table_name, ordinal_position;
SQL
)"
printf '%s\n' "$COLS" | python3 "$GEN_PY" > "$STREAMS_OUT"
N_STREAMS="$(python3 -c "import json; print(len(json.load(open('$STREAMS_OUT'))))")"

docker compose -f "$COMPOSE_FILE" up -d db >/dev/null

STREAMS="$(cat "$STREAMS_OUT")"

cat > "$OUT_FILE" <<EOF
# Generado en el deploy — NO subir a git.
# Corporate AI Agent → Conectores → Planner

host:     ${CONNECTOR_HOST}
port:     ${AGENT_READONLY_DB_PORT}
database: gestion_obra_saas
user:     agent_readonly
password: ${AGENT_READONLY_PASSWORD}
sslmode:  disable

# .env del AGENTE: ALLOW_INSECURE_CONNECTORS=true

# Acceso: SELECT a las ${N_STREAMS} tablas/vistas de tenant_soltec (todo el dato de Soltec).
# streams_json:
${STREAMS}

# Firewall SignaPlan: TCP ${AGENT_READONLY_DB_PORT} solo desde la IP del agente.
# Bind: ${AGENT_READONLY_DB_BIND}:${AGENT_READONLY_DB_PORT} → db:5432
EOF

echo ""
echo -e "${GREEN}✓ agent_readonly = SELECT total sobre tenant_soltec (${N_STREAMS} streams)${NC}"
echo -e "${GREEN}  Conector: ${OUT_FILE}${NC}"
echo -e "${GREEN}  Streams:  ${STREAMS_OUT}${NC}"
echo ""
echo "--- resumen conector ---"
echo "host=${CONNECTOR_HOST} port=${AGENT_READONLY_DB_PORT} db=gestion_obra_saas user=agent_readonly"
echo "password=${AGENT_READONLY_PASSWORD}"
echo "streams: ${N_STREAMS} (ver ${STREAMS_OUT})"
