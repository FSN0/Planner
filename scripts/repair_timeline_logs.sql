-- =============================================================================
-- Reparar timeline persona/dia (system_logs.target_user_id / target_date)
-- Ejecutar sobre tenant ya migrado, leyendo datos del backup import.
-- =============================================================================
-- Variables: tenant_schema, import_db
-- =============================================================================

\set ON_ERROR_STOP on

\if :{?import_db}
\else
\set import_db 'dbname=gestion_obra_main_import user=postgres'
\endif

SELECT set_config('repair.tenant_schema', :'tenant_schema', false);
SELECT set_config('repair.import_conn', :'import_db', false);

CREATE EXTENSION IF NOT EXISTS dblink;

DO $repair$
DECLARE
    v_schema text := current_setting('repair.tenant_schema');
    v_conn text := current_setting('repair.import_conn');
    v_has_targets boolean;
    v_updated int;
BEGIN
    IF v_schema IS NULL OR v_schema = '' THEN
        RAISE EXCEPTION 'tenant_schema requerido';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM dblink(
            v_conn,
            $$SELECT 1 FROM information_schema.columns
              WHERE table_schema = 'public' AND table_name = 'system_logs' AND column_name = 'target_user_id'$$
        ) AS t(c int)
    ) INTO v_has_targets;

    IF NOT v_has_targets THEN
        RAISE NOTICE 'El backup MAIN no tiene target_user_id/target_date en system_logs';
        RETURN;
    END IF;

    EXECUTE format($q$
        UPDATE %1$I.system_logs AS dst
        SET
            target_user_id = src.target_user_id,
            target_date = src.target_date
        FROM dblink(%2$L,
            'SELECT id, target_user_id, target_date FROM public.system_logs ORDER BY id'
        ) AS src(id int, target_user_id int, target_date date)
        WHERE dst.id = src.id
          AND (
              dst.target_user_id IS DISTINCT FROM src.target_user_id
              OR dst.target_date IS DISTINCT FROM src.target_date
          )
    $q$, v_schema, v_conn);

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RAISE NOTICE 'Timeline reparado en %: % filas actualizadas', v_schema, v_updated;
END;
$repair$;

\echo '--- repair_timeline_logs.sql finalizado ---'
