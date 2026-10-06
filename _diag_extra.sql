-- extra diagnostics
\echo === tenant_soltec.registros_fichajes columns related ===
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema='tenant_soltec' AND table_name='registros_fichajes'
  AND column_name ILIKE ANY (ARRAY['%estado%','%odoo%','%partner%','%emple%','%origen%','%fuente%'])
ORDER BY 1;

\echo === tenant_soltec totals null estado_odoo ===
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE estado_odoo IS NULL) AS null_estado,
       COUNT(*) FILTER (WHERE estado_odoo IS NOT NULL) AS not_null_estado
FROM tenant_soltec.registros_fichajes;

\echo === alembic all schemas ===
SELECT 'public' AS schema, version_num FROM public.alembic_version
UNION ALL SELECT 'tenant_soltec', version_num FROM tenant_soltec.alembic_version;

\echo === certificacion_lineas soltec ===
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE estado_fichaje IS NULL) AS null_ef,
       COUNT(*) FILTER (WHERE estado_fichaje IS NOT NULL) AS not_null_ef
FROM tenant_soltec.certificacion_lineas;
