-- =============================================================================
-- SignaPlan - Migracion MAIN (monolito) -> tenant SaaS (transformaciones)
-- =============================================================================
-- Variables psql: tenant_schema, tenant_subdominio, tenant_nombre, import_db,
--                 alembic_head (default e5f6a7b8c9d0)
-- import_db = cadena conninfo dblink (ej: dbname=gestion_obra_main_import user=postgres)
-- =============================================================================

\set ON_ERROR_STOP on

\if :{?import_db}
\else
\set import_db 'dbname=gestion_obra_main_import user=postgres'
\endif

\if :{?alembic_head}
\else
\set alembic_head 'e5f6a7b8c9d0'
\endif

SELECT set_config('migration.tenant_schema', :'tenant_schema', false);
SELECT set_config('migration.tenant_subdominio', :'tenant_subdominio', false);
SELECT set_config('migration.tenant_nombre', :'tenant_nombre', false);
SELECT set_config('migration.import_conn', :'import_db', false);
SELECT set_config('migration.alembic_head', :'alembic_head', false);

CREATE EXTENSION IF NOT EXISTS dblink;

DO $migrate$
DECLARE
    v_schema text := current_setting('migration.tenant_schema');
    v_sub text := current_setting('migration.tenant_subdominio');
    v_name text := current_setting('migration.tenant_nombre');
    v_conn text := current_setting('migration.import_conn');
    v_head text := current_setting('migration.alembic_head');
    v_has_solicitud_notas boolean;
    v_has_nota_odoo boolean;
    v_has_system_log_targets boolean;
    truncate_tables text;
    t_name text;
BEGIN
    IF v_schema IS NULL OR v_schema = '' THEN
        RAISE EXCEPTION 'tenant_schema requerido';
    END IF;
    IF v_sub IS NULL OR v_sub = '' THEN
        RAISE EXCEPTION 'tenant_subdominio requerido';
    END IF;

    -- 1) Registro tenant en public
    INSERT INTO public.tenants (nombre, subdominio, schema_name, is_active, modulos_activos)
    VALUES (
        v_name,
        v_sub,
        v_schema,
        true,
        '{"odoo": true, "odoo_alta": true, "odoo_adapter": "odoo_soltec", "chat": false}'::json
    )
    ON CONFLICT (subdominio) DO UPDATE SET
        nombre = EXCLUDED.nombre,
        schema_name = EXCLUDED.schema_name,
        is_active = true,
        modulos_activos = EXCLUDED.modulos_activos;

    -- 2) Esquema + clon estructura desde public
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', v_schema);
    FOR t_name IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename NOT IN ('tenants', 'alembic_version')
        ORDER BY tablename
    LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I.%I (LIKE public.%I INCLUDING ALL)',
            v_schema, t_name, t_name
        );
    END LOOP;
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I.alembic_version (LIKE public.alembic_version INCLUDING ALL)',
        v_schema
    );

    -- 3) Vaciar tablas tenant (sin disparar FK)
    SELECT string_agg(format('%I.%I', v_schema, tablename), ', ')
    INTO truncate_tables
    FROM pg_tables
    WHERE schemaname = v_schema;

    IF truncate_tables IS NOT NULL THEN
        EXECUTE 'SET session_replication_role = replica';
        EXECUTE format('TRUNCATE TABLE %s RESTART IDENTITY CASCADE', truncate_tables);
        EXECUTE 'SET session_replication_role = origin';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM dblink(
            v_conn,
            $$SELECT 1 FROM information_schema.columns
              WHERE table_schema = 'public' AND table_name = 'solicitudes' AND column_name = 'notas'$$
        ) AS t(c int)
    ) INTO v_has_solicitud_notas;

    SELECT EXISTS (
        SELECT 1
        FROM dblink(
            v_conn,
            $$SELECT 1 FROM information_schema.columns
              WHERE table_schema = 'public' AND table_name = 'registros_fichajes' AND column_name = 'nota_odoo'$$
        ) AS t(c int)
    ) INTO v_has_nota_odoo;

    SELECT EXISTS (
        SELECT 1
        FROM dblink(
            v_conn,
            $$SELECT 1 FROM information_schema.columns
              WHERE table_schema = 'public' AND table_name = 'system_logs' AND column_name = 'target_user_id'$$
        ) AS t(c int)
    ) INTO v_has_system_log_targets;

    -- 4) Copia con transformaciones (orden FK)
    EXECUTE format($q$
        INSERT INTO %1$I.companies (
            id, code, nombre, nif, external_ids, descripcion, gremio, email, color, is_internal
        )
        SELECT
            id, code, nombre, nif,
            COALESCE(
                CASE WHEN odoo_id IS NOT NULL THEN jsonb_build_object('odoo', odoo_id::text) END,
                '{}'::jsonb
            ),
            descripcion, gremio, email, color, is_internal
        FROM dblink(%2$L,
            'SELECT id, code, nombre, nif, odoo_id, descripcion, gremio, email, color, is_internal FROM public.companies ORDER BY id'
        ) AS r(
            id int, code varchar, nombre varchar, nif varchar, odoo_id int,
            descripcion text, gremio varchar, email varchar, color varchar, is_internal boolean
        )
    $q$, v_schema, v_conn);

    EXECUTE format($q$
        INSERT INTO %1$I.users (
            id, external_ids, email, password_hash, role, name, lastname, dni, company_id,
            categoria_profesional, active, is_deleted, receive_emails, timezone,
            especialidad, scheduled_activation_date, scheduled_deactivation_date
        )
        SELECT
            id,
            COALESCE(
                CASE WHEN odoo_id IS NOT NULL THEN jsonb_build_object('odoo', odoo_id::text) END,
                '{}'::jsonb
            ),
            email, password_hash, role, name, lastname, dni, company_id,
            categoria_profesional, active, is_deleted, receive_emails,
            NULL::varchar(64),
            especialidad, scheduled_activation_date, scheduled_deactivation_date
        FROM dblink(%2$L,
            'SELECT id, odoo_id, email, password_hash, role, name, lastname, dni, company_id,
                    categoria_profesional, active, is_deleted, receive_emails, timezone,
                    especialidad, scheduled_activation_date, scheduled_deactivation_date
             FROM public.users ORDER BY id'
        ) AS r(
            id int, odoo_id int, email varchar, password_hash varchar, role varchar,
            name varchar, lastname varchar, dni varchar, company_id int,
            categoria_profesional varchar, active boolean, is_deleted boolean, receive_emails boolean,
            timezone varchar, especialidad varchar,
            scheduled_activation_date date, scheduled_deactivation_date date
        )
    $q$, v_schema, v_conn);

    EXECUTE format($q$
        INSERT INTO %1$I.festivos (id, fecha, descripcion)
        SELECT id, fecha, descripcion
        FROM dblink(%2$L, 'SELECT id, fecha, descripcion FROM public.festivos ORDER BY id') AS r(
            id int, fecha date, descripcion varchar
        )
    $q$, v_schema, v_conn);

    EXECUTE format($q$
        INSERT INTO %1$I.configuracion_global (id, clave, valor)
        SELECT
            id,
            clave,
            CASE WHEN clave = 'motor_sincronizacion' THEN 'odoo_soltec' ELSE valor END
        FROM dblink(%2$L, 'SELECT id, clave, valor FROM public.configuracion_global ORDER BY id') AS r(
            id int, clave varchar, valor varchar
        )
    $q$, v_schema, v_conn);

    EXECUTE format($q$
        INSERT INTO %1$I.log_preferences (id, user_id, category, is_active, last_read_at)
        SELECT id, user_id, category, is_active, last_read_at
        FROM dblink(%2$L,
            'SELECT id, user_id, category, is_active, last_read_at FROM public.log_preferences ORDER BY id'
        ) AS r(id int, user_id int, category varchar, is_active boolean, last_read_at timestamp)
    $q$, v_schema, v_conn);

    EXECUTE format($q$
        INSERT INTO %1$I.obras (
            id, codigo, nombre, descripcion, cliente, ubicacion, fecha_sincronizacion, external_ids,
            fecha_inicio, fecha_fin, fecha_importacion, estado, limite_trabajadores, url_prl,
            jefe_obra_id, encargado_id, color, is_deleted
        )
        SELECT
            id, codigo, nombre, descripcion, cliente, ubicacion, fecha_sincronizacion,
            COALESCE(
                CASE WHEN odoo_id IS NOT NULL THEN jsonb_build_object('odoo', odoo_id::text) END,
                '{}'::jsonb
            ),
            fecha_inicio, fecha_fin, fecha_importacion, estado, limite_trabajadores, url_prl,
            jefe_obra_id, encargado_id, color, is_deleted
        FROM dblink(%2$L,
            'SELECT id, codigo, nombre, descripcion, cliente, ubicacion, fecha_sincronizacion, odoo_id,
                    fecha_inicio, fecha_fin, fecha_importacion, estado, limite_trabajadores, url_prl,
                    jefe_obra_id, encargado_id, color, is_deleted
             FROM public.obras ORDER BY id'
        ) AS r(
            id int, codigo varchar, nombre varchar, descripcion text, cliente varchar, ubicacion varchar,
            fecha_sincronizacion timestamp, odoo_id int, fecha_inicio date, fecha_fin date,
            fecha_importacion timestamp, estado varchar, limite_trabajadores int, url_prl varchar,
            jefe_obra_id int, encargado_id int, color varchar, is_deleted boolean
        )
    $q$, v_schema, v_conn);

    IF v_has_solicitud_notas THEN
        EXECUTE format($q$
            INSERT INTO %1$I.solicitudes (
                id, tipo, accion, obra_id, requested_by_id, empleado_id, fecha_inicio, fecha_fin,
                perfil_categoria, perfil_empresa_id, cantidad_solicitada, cantidad_cubierta, estado,
                auto_fulfilled, comentarios, notas, created_at, updated_at, resolved_by_id, resolved_at
            )
            SELECT
                id, tipo, accion, obra_id, requested_by_id, empleado_id, fecha_inicio, fecha_fin,
                perfil_categoria, perfil_empresa_id, cantidad_solicitada, cantidad_cubierta, estado,
                auto_fulfilled, comentarios, notas, created_at, updated_at, resolved_by_id, resolved_at
            FROM dblink(%2$L,
                'SELECT id, tipo, accion, obra_id, requested_by_id, empleado_id, fecha_inicio, fecha_fin,
                        perfil_categoria, perfil_empresa_id, cantidad_solicitada, cantidad_cubierta, estado,
                        auto_fulfilled, comentarios, notas, created_at, updated_at, resolved_by_id, resolved_at
                 FROM public.solicitudes ORDER BY id'
            ) AS r(
                id int, tipo varchar, accion varchar, obra_id int, requested_by_id int, empleado_id int,
                fecha_inicio date, fecha_fin date, perfil_categoria varchar, perfil_empresa_id int,
                cantidad_solicitada int, cantidad_cubierta int, estado varchar, auto_fulfilled boolean,
                comentarios text, notas text, created_at timestamp, updated_at timestamp,
                resolved_by_id int, resolved_at timestamp
            )
        $q$, v_schema, v_conn);
    ELSE
        EXECUTE format($q$
            INSERT INTO %1$I.solicitudes (
                id, tipo, accion, obra_id, requested_by_id, empleado_id, fecha_inicio, fecha_fin,
                perfil_categoria, perfil_empresa_id, cantidad_solicitada, cantidad_cubierta, estado,
                auto_fulfilled, comentarios, notas, created_at, updated_at, resolved_by_id, resolved_at
            )
            SELECT
                id, tipo, accion, obra_id, requested_by_id, empleado_id, fecha_inicio, fecha_fin,
                perfil_categoria, perfil_empresa_id, cantidad_solicitada, cantidad_cubierta, estado,
                auto_fulfilled, comentarios, NULL::text, created_at, updated_at, resolved_by_id, resolved_at
            FROM dblink(%2$L,
                'SELECT id, tipo, accion, obra_id, requested_by_id, empleado_id, fecha_inicio, fecha_fin,
                        perfil_categoria, perfil_empresa_id, cantidad_solicitada, cantidad_cubierta, estado,
                        auto_fulfilled, comentarios, created_at, updated_at, resolved_by_id, resolved_at
                 FROM public.solicitudes ORDER BY id'
            ) AS r(
                id int, tipo varchar, accion varchar, obra_id int, requested_by_id int, empleado_id int,
                fecha_inicio date, fecha_fin date, perfil_categoria varchar, perfil_empresa_id int,
                cantidad_solicitada int, cantidad_cubierta int, estado varchar, auto_fulfilled boolean,
                comentarios text, created_at timestamp, updated_at timestamp,
                resolved_by_id int, resolved_at timestamp
            )
        $q$, v_schema, v_conn);
    END IF;

    EXECUTE format($q$
        INSERT INTO %1$I.user_obra_config (user_id, obra_id, is_pinned, position)
        SELECT user_id, obra_id, is_pinned, position
        FROM dblink(%2$L,
            'SELECT user_id, obra_id, is_pinned, position FROM public.user_obra_config'
        ) AS r(user_id int, obra_id int, is_pinned boolean, position int)
    $q$, v_schema, v_conn);

    EXECUTE format($q$
        INSERT INTO %1$I.asignaciones (
            id, obra_id, user_id, fecha, company_id, created_at, solicitud_id
        )
        SELECT id, obra_id, user_id, fecha, company_id, created_at, solicitud_id
        FROM dblink(%2$L,
            'SELECT id, obra_id, user_id, fecha, company_id, created_at, solicitud_id FROM public.asignaciones ORDER BY id'
        ) AS r(
            id int, obra_id int, user_id int, fecha date, company_id int,
            created_at timestamp, solicitud_id int
        )
    $q$, v_schema, v_conn);

    EXECUTE format($q$
        INSERT INTO %1$I.historial_asignaciones (id, asignacion_id, accion, timestamp, realizado_por)
        SELECT id, asignacion_id, accion, timestamp, realizado_por
        FROM dblink(%2$L,
            'SELECT id, asignacion_id, accion, timestamp, realizado_por FROM public.historial_asignaciones ORDER BY id'
        ) AS r(id int, asignacion_id int, accion varchar, timestamp timestamp, realizado_por int)
    $q$, v_schema, v_conn);

    EXECUTE format($q$
        INSERT INTO %1$I.sync_logs (
            id, fecha, tipo, modo, nuevos, actualizados, finalizados, errores, detalles,
            estado, duracion_ms, mensaje_error
        )
        SELECT
            id, fecha, tipo, modo, nuevos, actualizados, finalizados, errores, detalles,
            'ok', NULL::integer, NULL::text
        FROM dblink(%2$L,
            'SELECT id, fecha, tipo, modo, nuevos, actualizados, finalizados, errores, detalles FROM public.sync_logs ORDER BY id'
        ) AS r(
            id int, fecha timestamp, tipo varchar, modo varchar,
            nuevos int, actualizados int, finalizados int, errores int, detalles text
        )
    $q$, v_schema, v_conn);

    IF v_has_nota_odoo THEN
        EXECUTE format($q$
            INSERT INTO %1$I.registros_fichajes (
                id, user_id, fecha, check_in, check_out, nota_odoo,
                obra_planificada_id, obra_real_id, estado, notas_resolucion, fecha_auditoria, resuelto_por_id
            )
            SELECT
                id, user_id, fecha, check_in, check_out, nota_odoo,
                obra_planificada_id, obra_real_id,
                CASE
                    WHEN estado = 'Sin_Registro' AND (check_in IS NOT NULL OR check_out IS NOT NULL)
                    THEN 'Correcto_Automatico'
                    ELSE estado
                END,
                notas_resolucion, fecha_auditoria, resuelto_por_id
            FROM dblink(%2$L,
                'SELECT id, user_id, fecha, check_in, check_out, nota_odoo,
                        obra_planificada_id, obra_real_id, estado, notas_resolucion, fecha_auditoria, resuelto_por_id
                 FROM public.registros_fichajes ORDER BY id'
            ) AS r(
                id int, user_id int, fecha date, check_in timestamp, check_out timestamp, nota_odoo text,
                obra_planificada_id int, obra_real_id int, estado varchar, notas_resolucion text,
                fecha_auditoria timestamp, resuelto_por_id int
            )
        $q$, v_schema, v_conn);
    ELSE
        EXECUTE format($q$
            INSERT INTO %1$I.registros_fichajes (
                id, user_id, fecha, check_in, check_out, nota_odoo,
                obra_planificada_id, obra_real_id, estado, notas_resolucion, fecha_auditoria, resuelto_por_id
            )
            SELECT
                id, user_id, fecha, check_in, check_out, NULL::text,
                obra_planificada_id, obra_real_id,
                CASE
                    WHEN estado = 'Sin_Registro' AND (check_in IS NOT NULL OR check_out IS NOT NULL)
                    THEN 'Correcto_Automatico'
                    ELSE estado
                END,
                notas_resolucion, fecha_auditoria, resuelto_por_id
            FROM dblink(%2$L,
                'SELECT id, user_id, fecha, check_in, check_out,
                        obra_planificada_id, obra_real_id, estado, notas_resolucion, fecha_auditoria, resuelto_por_id
                 FROM public.registros_fichajes ORDER BY id'
            ) AS r(
                id int, user_id int, fecha date, check_in timestamp, check_out timestamp,
                obra_planificada_id int, obra_real_id int, estado varchar, notas_resolucion text,
                fecha_auditoria timestamp, resuelto_por_id int
            )
        $q$, v_schema, v_conn);
    END IF;

    EXECUTE format($q$
        INSERT INTO %1$I.ratings (id, user_id, created_by_id, score, reason, created_at, is_active)
        SELECT id, user_id, created_by_id, score, reason, created_at, is_active
        FROM dblink(%2$L,
            'SELECT id, user_id, created_by_id, score, reason, created_at, is_active FROM public.ratings ORDER BY id'
        ) AS r(
            id int, user_id int, created_by_id int, score int, reason text,
            created_at timestamp, is_active boolean
        )
    $q$, v_schema, v_conn);

    EXECUTE format($q$
        INSERT INTO %1$I.notas (id, titulo, contenido, fecha, es_privada, autor_id, created_at)
        SELECT id, titulo, contenido, fecha, es_privada, autor_id, created_at
        FROM dblink(%2$L,
            'SELECT id, titulo, contenido, fecha, es_privada, autor_id, created_at FROM public.notas ORDER BY id'
        ) AS r(
            id int, titulo varchar, contenido text, fecha date,
            es_privada boolean, autor_id int, created_at timestamp
        )
    $q$, v_schema, v_conn);

    EXECUTE format($q$
        INSERT INTO %1$I.nota_obra (nota_id, obra_id)
        SELECT nota_id, obra_id
        FROM dblink(%2$L, 'SELECT nota_id, obra_id FROM public.nota_obra') AS r(nota_id int, obra_id int)
    $q$, v_schema, v_conn);

    EXECUTE format($q$
        INSERT INTO %1$I.nota_user (nota_id, user_id)
        SELECT nota_id, user_id
        FROM dblink(%2$L, 'SELECT nota_id, user_id FROM public.nota_user') AS r(nota_id int, user_id int)
    $q$, v_schema, v_conn);

    IF v_has_system_log_targets THEN
        EXECUTE format($q$
            INSERT INTO %1$I.system_logs (
                id, timestamp, user_id, category, action, detail, target_user_id, target_date
            )
            SELECT id, timestamp, user_id, category, action, detail, target_user_id, target_date
            FROM dblink(%2$L,
                'SELECT id, timestamp, user_id, category, action, detail, target_user_id, target_date
                 FROM public.system_logs ORDER BY id'
            ) AS r(
                id int, timestamp timestamp, user_id int, category varchar, action varchar, detail text,
                target_user_id int, target_date date
            )
        $q$, v_schema, v_conn);
    ELSE
        EXECUTE format($q$
            INSERT INTO %1$I.system_logs (
                id, timestamp, user_id, category, action, detail, target_user_id, target_date
            )
            SELECT id, timestamp, user_id, category, action, detail, NULL::integer, NULL::date
            FROM dblink(%2$L,
                'SELECT id, timestamp, user_id, category, action, detail FROM public.system_logs ORDER BY id'
            ) AS r(
                id int, timestamp timestamp, user_id int, category varchar, action varchar, detail text
            )
        $q$, v_schema, v_conn);

        -- Monolitos sin columnas de auditoria: reconstruir target para timeline persona/dia.
        EXECUTE format($q$
            UPDATE %1$I.system_logs sl
            SET
                target_user_id = rf.user_id,
                target_date = rf.fecha
            FROM %1$I.registros_fichajes rf
            WHERE sl.target_user_id IS NULL
              AND sl.category IN ('fichaje_app', 'fichajes')
              AND rf.user_id IS NOT NULL
              AND rf.fecha IS NOT NULL
              AND sl.timestamp::date = rf.fecha
              AND (
                  sl.detail ILIKE '%%' || rf.user_id::text || '%%'
                  OR EXISTS (
                      SELECT 1 FROM %1$I.users u
                      WHERE u.id = rf.user_id
                        AND (
                            sl.detail ILIKE '%%' || u.name || '%%'
                            OR sl.detail ILIKE '%%' || u.lastname || '%%'
                        )
                  )
              )
        $q$, v_schema);

        EXECUTE format($q$
            UPDATE %1$I.system_logs sl
            SET
                target_user_id = COALESCE(sl.target_user_id, sl.user_id),
                target_date = COALESCE(sl.target_date, sl.timestamp::date)
            WHERE sl.target_user_id IS NULL
              AND sl.category = 'planificacion'
              AND sl.user_id IS NOT NULL
        $q$, v_schema);
    END IF;

    EXECUTE format($q$
        INSERT INTO %1$I.alembic_version (version_num) VALUES (%2$L)
    $q$, v_schema, v_head);

    -- 5) Secuencias
    FOR t_name IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = v_schema
          AND c.relkind = 'r'
          AND EXISTS (
              SELECT 1 FROM information_schema.columns ic
              WHERE ic.table_schema = v_schema AND ic.table_name = c.relname AND ic.column_name = 'id'
          )
    LOOP
        EXECUTE format(
            $q$SELECT setval(pg_get_serial_sequence(%L, 'id'), COALESCE((SELECT MAX(id) FROM %I.%I), 1), true)$q$,
            v_schema || '.' || t_name, v_schema, t_name
        );
    END LOOP;

    -- Tras copiar filas con id explicito la secuencia queda desfasada; el upsert va despues del setval.
    EXECUTE format($q$
        INSERT INTO %1$I.configuracion_global (clave, valor)
        VALUES ('motor_sincronizacion', 'odoo_soltec')
        ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor
    $q$, v_schema);

    RAISE NOTICE 'Migracion completada: schema=% subdominio=% alembic=%', v_schema, v_sub, v_head;
END;
$migrate$;

\echo '--- migrate_main_to_tenant.sql finalizado ---'