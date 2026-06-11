#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAAS_DB="gestion_obra_saas"
IMPORT_DB="gestion_obra_main_import"
SQL_FILE="${SCRIPT_DIR}/repair_timeline_logs.sql"

if [[ -f "${PWD}/docker-compose.prod.yml" ]]; then
    COMPOSE_FILE="docker-compose.prod.yml"
elif [[ -f "${SCRIPT_DIR}/../docker-compose.prod.yml" ]]; then
    cd "${SCRIPT_DIR}/.."
    COMPOSE_FILE="docker-compose.prod.yml"
else
    COMPOSE_FILE="docker-compose.yml"
fi

read -r -p "Subdominio del tenant [soltec]: " subdominio
subdominio="${subdominio:-soltec}"
tenant_schema="tenant_${subdominio//-/_}"

echo "Reparando timeline en ${tenant_schema} desde ${IMPORT_DB}..."
docker compose -f "${COMPOSE_FILE}" exec -T db \
    psql -U postgres -d "${SAAS_DB}" -v ON_ERROR_STOP=1 \
    -v tenant_schema="${tenant_schema}" \
    -v import_db="dbname=${IMPORT_DB} user=postgres" \
    -f - < "${SQL_FILE}"

echo "Listo. Recarga auditoría de fichajes y abre el timeline persona/día."
