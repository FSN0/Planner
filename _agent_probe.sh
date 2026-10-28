#!/bin/bash
set -euo pipefail
cd /opt/soltec/planner
echo "=== schemas ==="
docker compose exec -T db psql -U postgres -d gestion_obra_saas -Atc \
  "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema' ORDER BY 1;"
echo "=== public tables of interest ==="
docker compose exec -T db psql -U postgres -d gestion_obra_saas -Atc \
  "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('obras','asignaciones','registros_fichajes','users','companies','tenants') ORDER BY 1;"
echo "=== tenant_* sample tables ==="
SCH=$(docker compose exec -T db psql -U postgres -d gestion_obra_saas -Atc \
  "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'tenant_%' ORDER BY 1 LIMIT 1;")
echo "sample schema: ${SCH}"
if [ -n "$SCH" ]; then
  docker compose exec -T db psql -U postgres -d gestion_obra_saas -Atc \
    "SELECT tablename FROM pg_tables WHERE schemaname='${SCH}' AND tablename IN ('obras','asignaciones','registros_fichajes','users','companies') ORDER BY 1;"
  docker compose exec -T db psql -U postgres -d gestion_obra_saas -Atc \
    "SELECT 'obras', count(*) FROM ${SCH}.obras UNION ALL SELECT 'asignaciones', count(*) FROM ${SCH}.asignaciones UNION ALL SELECT 'fichajes', count(*) FROM ${SCH}.registros_fichajes;"
fi
echo "=== agent stack ==="
ls /opt/corporate-ai-agent 2>/dev/null | head -15 || echo "no agent dir"
docker compose -f /opt/corporate-ai-agent/docker-compose.yml ps --format 'table {{.Name}}\t{{.Status}}' 2>/dev/null | head || echo "agent compose not up"
echo "=== published 5432 ==="
docker port planner-db-1 5432 2>/dev/null || true
