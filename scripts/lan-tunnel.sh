#!/usr/bin/env bash
# Tunel Cloudflare rapido -> Caddy: solo llega a la landing (sin tenant por defecto).
# Para probar un tenant en LAN, usa sslip.io (ej. http://paquito.192.168.1.141.sslip.io/).
# El tunel sigue siendo util para comprobar la landing publica.
set -euo pipefail

NETWORK="$(docker inspect planner-caddy-1 --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null | head -1)"
if [ -z "${NETWORK}" ]; then
  echo "planner-caddy-1 container or Docker network not found" >&2
  exit 1
fi

exec docker run --rm -it --network "$NETWORK" \
  cloudflare/cloudflared:latest \
  tunnel --url http://caddy:80
