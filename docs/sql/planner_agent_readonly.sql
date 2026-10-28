-- SignaPlan → Corporate AI Agent: SOLO LECTURA de TODO tenant_soltec.
-- Idempotente. Password: CAMBIAR_PASSWORD_RO (lo sustituye ensure_agent_readonly.sh).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_readonly') THEN
    CREATE ROLE agent_readonly LOGIN PASSWORD 'CAMBIAR_PASSWORD_RO';
  END IF;
END
$$;

-- Solo lectura a nivel de sesión.
ALTER ROLE agent_readonly SET default_transaction_read_only = on;
-- Tablas sin schema: resuelven a Soltec.
ALTER ROLE agent_readonly SET search_path = tenant_soltec, public;

GRANT CONNECT ON DATABASE gestion_obra_saas TO agent_readonly;
GRANT USAGE ON SCHEMA public TO agent_readonly;
GRANT USAGE ON SCHEMA tenant_soltec TO agent_readonly;

-- TODO el tenant Soltec (tablas + vistas).
GRANT SELECT ON ALL TABLES IN SCHEMA tenant_soltec TO agent_readonly;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA tenant_soltec TO agent_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA tenant_soltec
  GRANT SELECT ON TABLES TO agent_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA tenant_soltec
  GRANT SELECT ON SEQUENCES TO agent_readonly;

-- Por si un deploy antiguo concedió otros tenants: revocar.
DO $$
DECLARE sch text;
BEGIN
  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname LIKE 'tenant_%' AND nspname <> 'tenant_soltec'
  LOOP
    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM agent_readonly', sch);
    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM agent_readonly', sch);
    EXECUTE format('REVOKE USAGE ON SCHEMA %I FROM agent_readonly', sch);
  END LOOP;
END
$$;

-- Quitar vistas agent_* antiguas (ahora el agente lee las tablas reales).
DROP VIEW IF EXISTS public.agent_obras CASCADE;
DROP VIEW IF EXISTS public.agent_asignaciones CASCADE;
DROP VIEW IF EXISTS public.agent_fichajes CASCADE;
DROP VIEW IF EXISTS public.agent_empleados CASCADE;
