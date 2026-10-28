#!/bin/bash
set -euo pipefail
cd /opt/soltec/planner
echo "=== tenant_soltec counts ==="
docker compose exec -T db psql -U postgres -d gestion_obra_saas -Atc \
  "SELECT 'obras', count(*) FROM tenant_soltec.obras
   UNION ALL SELECT 'asignaciones', count(*) FROM tenant_soltec.asignaciones
   UNION ALL SELECT 'fichajes', count(*) FROM tenant_soltec.registros_fichajes
   UNION ALL SELECT 'users', count(*) FROM tenant_soltec.users;"
echo "=== public counts ==="
docker compose exec -T db psql -U postgres -d gestion_obra_saas -Atc \
  "SELECT 'obras', count(*) FROM public.obras
   UNION ALL SELECT 'asignaciones', count(*) FROM public.asignaciones
   UNION ALL SELECT 'fichajes', count(*) FROM public.registros_fichajes;"
echo "=== agent -> planner host resolve ==="
docker compose -f /opt/corporate-ai-agent/docker-compose.yml exec -T app \
  python -c "import socket; print('host.docker.internal', socket.gethostbyname('host.docker.internal'))" 2>/dev/null || echo "no host.docker.internal"
docker inspect planner-db-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{.NetworkID}}{{end}}' 2>/dev/null
docker inspect corporate-ai-agent-app-1 --format '{{range \$k, \$v := .NetworkSettings.Networks}}{{\$k}}={{\$v.IPAddress}} {{end}}' 2>/dev/null
echo "=== existing agent_readonly? ==="
docker compose exec -T db psql -U postgres -d gestion_obra_saas -Atc \
  "SELECT rolname FROM pg_roles WHERE rolname='agent_readonly';"
