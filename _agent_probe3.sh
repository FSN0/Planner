#!/bin/bash
set -euo pipefail
PASS=$(cat /opt/soltec/planner/docs/sql/.agent_readonly_password)
echo "=== agent container -> planner postgres ==="
docker compose -f /opt/corporate-ai-agent/docker-compose.yml exec -T app \
  python - <<PY
import socket, os
host = "host.docker.internal"
print("resolve", host, "->", socket.gethostbyname(host))
try:
    import asyncpg, asyncio
    async def main():
        conn = await asyncpg.connect(
            host=host, port=5432, user="agent_readonly",
            password=os.environ["PASS"], database="gestion_obra_saas",
            ssl=False, timeout=5,
        )
        n = await conn.fetchval("select count(*) from agent_obras")
        ver = await conn.fetchval("select version()")
        print("ok obras=", n)
        print("pg=", ver.split(",")[0])
        await conn.close()
    asyncio.run(main())
except Exception as e:
    print("FAIL", type(e).__name__, e)
PY
echo "=== ALLOW_INSECURE in agent .env ==="
grep -E 'ALLOW_INSECURE|POSTGRES' /opt/corporate-ai-agent/.env 2>/dev/null | sed 's/PASSWORD=.*/PASSWORD=***/' || echo "(sin .env o sin matches)"
rm -f /opt/soltec/planner/_agent_probe.sh /opt/soltec/planner/_agent_probe2.sh /opt/soltec/planner/_agent_probe3.sh
