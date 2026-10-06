#!/usr/bin/env bash
# Diagnostic: why estado_fichaje is null on certificacion lines
set -euo pipefail
cd /opt/soltec/planner

echo "=== CONTAINERS ==="
docker compose ps -a

DB=gestion_obra_saas
echo "=== SCHEMAS ==="
docker compose exec -T db psql -U postgres -d "$DB" -c "
SELECT schema_name FROM information_schema.schemata
WHERE schema_name = 'public' OR schema_name LIKE 'tenant_%'
ORDER BY 1;
"

echo "=== ALEMBIC + estado_odoo COLUMN per schema ==="
docker compose exec -T db psql -U postgres -d "$DB" -c "
SELECT n.nspname AS schema,
       EXISTS (
         SELECT 1 FROM information_schema.columns c
         WHERE c.table_schema = n.nspname
           AND c.table_name = 'registros_fichajes'
           AND c.column_name = 'estado_odoo'
       ) AS has_estado_odoo,
       EXISTS (
         SELECT 1 FROM information_schema.tables t
         WHERE t.table_schema = n.nspname AND t.table_name = 'alembic_version'
       ) AS has_alembic
FROM pg_namespace n
WHERE n.nspname = 'public' OR n.nspname LIKE 'tenant_%'
ORDER BY 1;
"

for sch in $(docker compose exec -T db psql -U postgres -d "$DB" -Atc "SELECT nspname FROM pg_namespace WHERE nspname='public' OR nspname LIKE 'tenant_%' ORDER BY 1;"); do
  echo "=== SCHEMA $sch: alembic_version ==="
  docker compose exec -T db psql -U postgres -d "$DB" -c "SELECT version_num FROM ${sch}.alembic_version;" 2>/dev/null || echo "(no alembic_version)"

  echo "=== SCHEMA $sch: registros_fichajes estado_odoo counts ==="
  docker compose exec -T db psql -U postgres -d "$DB" -c "
  SELECT COUNT(*) AS total,
         COUNT(*) FILTER (WHERE estado_odoo IS NULL) AS null_estado,
         COUNT(*) FILTER (WHERE estado_odoo IS NOT NULL) AS not_null_estado
  FROM ${sch}.registros_fichajes;
  " 2>/dev/null || echo "(no registros_fichajes or no estado_odoo)"

  echo "=== SCHEMA $sch: DISTINCT estado_odoo ==="
  docker compose exec -T db psql -U postgres -d "$DB" -c "
  SELECT estado_odoo, COUNT(*) FROM ${sch}.registros_fichajes GROUP BY 1 ORDER BY 2 DESC LIMIT 20;
  " 2>/dev/null || true

  echo "=== SCHEMA $sch: certificacion_lineas estado_fichaje ==="
  docker compose exec -T db psql -U postgres -d "$DB" -c "
  SELECT COUNT(*) AS total,
         COUNT(*) FILTER (WHERE estado_fichaje IS NULL) AS null_ef,
         COUNT(*) FILTER (WHERE estado_fichaje IS NOT NULL) AS not_null_ef
  FROM ${sch}.certificacion_lineas;
  " 2>/dev/null || echo "(no certificacion_lineas)"
done

echo "=== SYNC LOG WARNINGS (campo estado fichaje) ==="
docker compose logs --tail=5000 web celery_worker 2>&1 | grep -iE 'campo estado fichaje|estado draft|estado_odoo|no se encontró campo estado' | tail -80 || true

echo "=== ODOO FIELD PROBE (web container) ==="
docker compose exec -T web python /app/_diag_odoo_probe.py
docker compose exec -T web python /app/_diag_odoo_probe2.py
docker compose exec -T web python /app/_diag_odoo_probe3.py

echo "=== DONE ==="
