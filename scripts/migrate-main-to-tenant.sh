#!/bin/bash
set -euo pipefail

# =============================================================================
# SignaPlan - Migrar instalacion MAIN -> tenant SaaS
# =============================================================================
# Uso (desde raiz del proyecto saas, ej. /opt/saas o /opt/planificador/saas):
#   ./scripts/migrate-main-to-tenant.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAAS_DB="gestion_obra_saas"
IMPORT_DB="gestion_obra_main_import"
ALEMBIC_HEAD="e5f6a7b8c9d0"
SQL_FILE="${SCRIPT_DIR}/migrate_main_to_tenant.sql"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${CYAN}$*${NC}"; }
ok() { echo -e "${GREEN}$*${NC}"; }
warn() { echo -e "${YELLOW}$*${NC}"; }
err() { echo -e "${RED}$*${NC}"; }

resolve_saas_root() {
    if [[ -f "${PWD}/docker-compose.yml" && -d "${PWD}/scripts" ]]; then
        SAAS_ROOT="${PWD}"
        return 0
    fi
    if [[ -f "${SCRIPT_DIR}/../docker-compose.yml" ]]; then
        SAAS_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
        cd "${SAAS_ROOT}"
        return 0
    fi
    err "Ejecuta este script desde la raiz del proyecto saas (/opt/saas) o desde scripts/."
    exit 1
}

ensure_db_running() {
    if ! docker compose -f "${COMPOSE_FILE}" ps --status running --services 2>/dev/null | grep -qx db; then
        warn "[db] Contenedor db no esta en ejecucion; iniciando..."
        docker compose -f "${COMPOSE_FILE}" up -d db
        sleep 3
    fi
    docker compose -f "${COMPOSE_FILE}" exec -T db pg_isready -U postgres >/dev/null
}

restore_import_db() {
    local backup_path="$1"
    warn "[import] Recreando base ${IMPORT_DB}..."
    docker compose -f "${COMPOSE_FILE}" exec -T db \
        psql -U postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${IMPORT_DB};"
    docker compose -f "${COMPOSE_FILE}" exec -T db \
        psql -U postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${IMPORT_DB};"

    warn "[import] Restaurando backup en ${IMPORT_DB}..."
    if [[ "${backup_path}" == *.gz ]]; then
        gunzip -c "${backup_path}" | docker compose -f "${COMPOSE_FILE}" exec -T db \
            psql -U postgres -v ON_ERROR_STOP=1 "${IMPORT_DB}"
    else
        docker compose -f "${COMPOSE_FILE}" exec -T db \
            psql -U postgres -v ON_ERROR_STOP=1 "${IMPORT_DB}" < "${backup_path}"
    fi
    ok "  -> Backup MAIN restaurado en ${IMPORT_DB}"
}

run_migration_sql() {
    local schema="$1"
    local sub="$2"
    local name="$3"
    warn "[migrate] Ejecutando migrate_main_to_tenant.sql..."
    if [[ ! -f "${SQL_FILE}" ]]; then
        err "No se encuentra ${SQL_FILE}"
        exit 1
    fi
    docker compose -f "${COMPOSE_FILE}" exec -T db \
        psql -U postgres -d "${SAAS_DB}" -v ON_ERROR_STOP=1 \
        -v tenant_schema="${schema}" \
        -v tenant_subdominio="${sub}" \
        -v tenant_nombre="${name}" \
        -v import_db="dbname=${IMPORT_DB} user=postgres" \
        -v alembic_head="${ALEMBIC_HEAD}" \
        -f - < "${SQL_FILE}"
    ok "  -> Migracion SQL aplicada (alembic tenant: ${ALEMBIC_HEAD})"
}

table_count() {
    local db="$1"
    local schema="$2"
    local table="$3"
    docker compose -f "${COMPOSE_FILE}" exec -T db psql -U postgres -d "${db}" -tAc \
        "SELECT COUNT(*) FROM ${schema}.${table};" 2>/dev/null | tr -d "[:space:]" || echo "missing"
}

verify_counts() {
    local schema="$1"
    local tables=(
        companies users obras asignaciones solicitudes registros_fichajes
        configuracion_global notas system_logs
    )
    warn "[verify] Comparando conteos import vs tenant..."
    local mismatches=0
    for t in "${tables[@]}"; do
        local import_cnt tenant_cnt
        import_cnt="$(table_count "${IMPORT_DB}" "public" "${t}")"
        if [[ "${import_cnt}" == "missing" ]]; then
            warn "  ${t}: no existe en import (omitido)"
            continue
        fi
        tenant_cnt="$(table_count "${SAAS_DB}" "${schema}" "${t}")"
        if [[ "${t}" == "configuracion_global" ]]; then
            # El tenant puede tener +1 fila (motor_sincronizacion) si no existia en el MAIN.
            if [[ "${tenant_cnt}" == "${import_cnt}" || "${tenant_cnt}" == "$((import_cnt + 1))" ]]; then
                ok "  ${t}: ${tenant_cnt} (import=${import_cnt})"
            else
                err "  MISMATCH ${t}: import=${import_cnt} tenant=${tenant_cnt}"
                mismatches=$((mismatches + 1))
            fi
        elif [[ "${import_cnt}" != "${tenant_cnt}" ]]; then
            err "  MISMATCH ${t}: import=${import_cnt} tenant=${tenant_cnt}"
            mismatches=$((mismatches + 1))
        else
            ok "  ${t}: ${tenant_cnt}"
        fi
    done
    if [[ "${mismatches}" -gt 0 ]]; then
        err "Verificacion con ${mismatches} diferencia(s). Revisa logs."
        exit 1
    fi
    ok "Verificacion de conteos OK"
}

restore_uploads() {
    local uploads_path="$1"
    [[ -z "${uploads_path}" ]] && return 0
    if [[ ! -f "${uploads_path}" ]]; then
        err "Archivo uploads no encontrado: ${uploads_path}"
        exit 1
    fi
    warn "[uploads] Extrayendo en contenedor web /app/uploads..."
    docker compose -f "${COMPOSE_FILE}" exec -T web mkdir -p /app/uploads
    cat "${uploads_path}" | docker compose -f "${COMPOSE_FILE}" exec -T web tar -xzf - -C /app
    ok "  -> Uploads restaurados"
}

configure_odoo_from_env() {
    local sub="$1"
    if [[ ! -f .env ]]; then
        return 0
    fi
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
    if [[ -z "${ODOO_URL:-}" && -z "${ODOO_DB:-}" && -z "${ODOO_USER:-}" && -z "${ODOO_PASSWORD:-}" ]]; then
        warn "[odoo] Sin variables ODOO_* en .env; omitiendo configuracion"
        return 0
    fi
    warn "[odoo] Configurando integracion Odoo en tenant ${sub}..."
    docker compose -f "${COMPOSE_FILE}" exec -T web flask shell <<PY
import os
from sqlalchemy import text
from app import db
from app.models import Tenant
from app.services.config_service import set_tenant_config

sub = "${sub}"
tenant = Tenant.query.filter_by(subdominio=sub).first()
if not tenant:
    raise SystemExit(f"Tenant {sub} no encontrado")
db.session.execute(text(f"SET search_path TO {tenant.schema_name}, public"))
for key, env_key, enc in [
    ("odoo_url", "ODOO_URL", False),
    ("odoo_db", "ODOO_DB", False),
    ("odoo_user", "ODOO_USER", False),
    ("odoo_password", "ODOO_PASSWORD", True),
]:
    val = (os.environ.get(env_key) or "").strip()
    if val:
        set_tenant_config(key, val, encriptar=enc)
db.session.commit()
print("Odoo config aplicada para", sub)
PY
    ok "  -> Configuracion Odoo guardada en configuracion_global"
}

main() {
    resolve_saas_root

    echo ""
    info "SignaPlan - Migracion MAIN -> Tenant SaaS"
    info "Directorio saas: ${SAAS_ROOT}"
    echo ""

    local backup_path=""
    while [[ -z "${backup_path}" ]]; do
        read -r -p "Ruta al backup SQL del MAIN (.sql o .sql.gz) [requerido]: " backup_path
        backup_path="${backup_path/#\~/$HOME}"
        if [[ -z "${backup_path}" ]]; then
            err "La ruta del backup es obligatoria."
            continue
        fi
        if [[ ! -f "${backup_path}" ]]; then
            err "No existe el archivo: ${backup_path}"
            backup_path=""
        fi
    done

    local subdominio nombre env uploads_path compose_answer
    read -r -p "Subdominio del tenant [soltec]: " subdominio
    subdominio="${subdominio:-soltec}"
    read -r -p "Nombre del tenant [Soltec]: " nombre
    nombre="${nombre:-Soltec}"
    read -r -p "Ruta uploads tar.gz (opcional, Enter para omitir): " uploads_path
    uploads_path="${uploads_path/#\~/$HOME}"

    read -r -p "Entorno docker [dev/prod] (default prod): " compose_answer
    compose_answer="${compose_answer:-prod}"
    if [[ "${compose_answer}" == "dev" ]]; then
        COMPOSE_FILE="docker-compose.yml"
    else
        COMPOSE_FILE="docker-compose.prod.yml"
    fi
    export COMPOSE_FILE

    local tenant_schema="tenant_${subdominio//-/_}"

    warn "[1/6] Comprobando servicio db (${COMPOSE_FILE})..."
    ensure_db_running

    warn "[2/6] Aplicando flask db upgrade en web..."
    docker compose -f "${COMPOSE_FILE}" up -d web >/dev/null
    docker compose -f "${COMPOSE_FILE}" exec -T web flask db upgrade
    ok "  -> Migraciones Alembic aplicadas"

    warn "[3/6] Restaurando dump MAIN en ${IMPORT_DB}..."
    restore_import_db "${backup_path}"

    warn "[4/6] Copiando datos al tenant ${tenant_schema}..."
    run_migration_sql "${tenant_schema}" "${subdominio}" "${nombre}"

    warn "[5/6] Verificacion..."
    verify_counts "${tenant_schema}"

    if [[ -n "${uploads_path}" ]]; then
        restore_uploads "${uploads_path}"
    else
        warn "[uploads] Omitido"
    fi

    warn "[6/6] Integraciones opcionales..."
    configure_odoo_from_env "${subdominio}"

    local domain_hint="${subdominio}.domain"
    if [[ -f .env ]]; then
        set -a
        # shellcheck disable=SC1091
        source .env
        set +a
        if [[ -n "${DOMAIN:-}" ]]; then
            domain_hint="${subdominio}.${DOMAIN}"
        fi
    fi

    echo ""
    ok "Migracion completada correctamente"
    ok "  Tenant: ${nombre} (${subdominio}) -> esquema ${tenant_schema}"
    ok "  Acceso: https://${domain_hint}"
    echo ""
}

main "$@"