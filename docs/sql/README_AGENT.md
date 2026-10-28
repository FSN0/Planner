# Bridge SignaPlan → Corporate AI Agent (todo Soltec)

El rol `agent_readonly` tiene **SELECT sobre todas** las tablas y vistas de `tenant_soltec`.
No hay filtro a 4 vistas: el agente puede leer absolutamente todos los datos del tenant Soltec.

## Deploy

En cada `make prod-deploy`:

1. Crea/actualiza `agent_readonly` (password en `.env`).
2. `GRANT SELECT` a todo `tenant_soltec` + `search_path` apuntando ahí.
3. Regenera `docs/sql/planner_agent_streams.json` (un stream por tabla).
4. Escribe `docs/sql/CONECTOR_AGENTE.txt` (gitignored).

También: `make agent-readonly`.

## `.env` SignaPlan

```bash
AGENT_READONLY_PASSWORD=
AGENT_READONLY_DB_BIND=0.0.0.0
AGENT_READONLY_DB_PORT=54329
```

Firewall: `54329/tcp` solo a la IP del servidor del agente.

## Conector en el agente

Tras el deploy, copia de `docs/sql/CONECTOR_AGENTE.txt`:

| Campo | Valor |
|-------|--------|
| host | DNS/IP pública del servidor SignaPlan |
| port | `54329` |
| database | `gestion_obra_saas` |
| user | `agent_readonly` |
| password | `AGENT_READONLY_PASSWORD` |
| sslmode | `disable` |
| streams_json | contenido de `planner_agent_streams.json` |

`.env` del agente: `ALLOW_INSECURE_CONNECTORS=true`.
