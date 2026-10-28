#!/bin/bash
# Compat: redirige al script canónico usado por prod-deploy.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
exec bash "$ROOT/scripts/ensure_agent_readonly.sh"
