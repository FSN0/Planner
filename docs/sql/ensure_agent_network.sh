#!/bin/bash
# Une Postgres del Planner y app/worker del agente en una red Docker compartida.
set -euo pipefail

NET=soltec-shared
docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET"

for c in planner-db-1 corporate-ai-agent-app-1 corporate-ai-agent-worker-1; do
  if docker inspect "$c" >/dev/null 2>&1; then
    if docker inspect "$c" -f '{{json .NetworkSettings.Networks}}' | grep -q "\"$NET\""; then
      echo "ya en $NET: $c"
    else
      docker network connect "$NET" "$c"
      echo "conectado: $c → $NET"
    fi
  else
    echo "omitido (no existe): $c"
  fi
done

echo ""
echo "Host del conector Planner:  planner-db-1"
echo "Puerto:                     5432"
echo "(misma red Docker $NET; no hace falta host.docker.internal)"
