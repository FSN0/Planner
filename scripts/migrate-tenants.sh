#!/bin/bash
set -euo pipefail

# =============================================================================
# SignaPlan - Migración multi-tenant
# =============================================================================
# Sincroniza la estructura de tablas entre public y todos los tenant schemas.
# Ejecutar ANTES de aplicar migraciones nuevas si hay tablas nuevas.
#
# Uso: ./scripts/migrate-tenants.sh [dev|prod]
# =============================================================================

ENV="${1:-dev}"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$ENV" = "prod" ]; then
    COMPOSE_FILE="docker-compose.prod.yml"
else
    COMPOSE_FILE="docker-compose.yml"
fi

echo -e "${YELLOW}[1/3] Asegurando servicios levantados...${NC}"
docker compose -f "$COMPOSE_FILE" up -d db
sleep 2

echo -e "${YELLOW}[2/3] Sincronizando estructuras de tenant schemas...${NC}"
docker compose -f "$COMPOSE_FILE" exec -T db psql -U postgres -d gestion_obra_saas <<'SQL'
DO $$
DECLARE
    tenant_schema TEXT;
    table_record RECORD;
BEGIN
    FOR tenant_schema IN SELECT schema_name FROM public.tenants WHERE is_active = true LOOP
        FOR table_record IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
            AND tablename NOT IN ('alembic_version', 'tenants')
        LOOP
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I.%I (LIKE public.%I INCLUDING ALL);',
                tenant_schema, table_record.tablename, table_record.tablename
            );
        END LOOP;
    END LOOP;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Sin tenants activos o tabla tenants no existe aún (normal en primer deploy)';
END;
$$;
SQL
echo -e "${GREEN}  → Estructuras sincronizadas${NC}"

echo -e "${YELLOW}[3/3] Aplicando migraciones...${NC}"
docker compose -f "$COMPOSE_FILE" exec -T web flask db upgrade

echo -e "${GREEN}✓ Migración completada${NC}"
