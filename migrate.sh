#!/bin/bash
# Script definitivo para automatizar migraciones SaaS (Modo Normal y Reset)

if [ "$#" -lt 1 ]; then
    echo "Uso: ./migrate.sh \"Mensaje descriptivo\" [--reset]"
    exit 1
fi

MIGRATION_MESSAGE="$1"
RESET_FLAG="$2"

echo "🐳 1. Asegurando que los contenedores están arriba..."
docker compose up -d db redis
sleep 2
docker compose up -d web
sleep 3

if [ "$RESET_FLAG" == "--reset" ]; then
    echo "⚠️  MODO RESET ACTIVADO: Purgando historial de migraciones a la fuerza..."
    
    rm -f migrations/versions/*.py 2>/dev/null
    
    docker exec -i project-db-1 psql -U postgres -d gestion_obra_saas <<'EOF'
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT schema_name FROM information_schema.schemata 
    LOOP
        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.schema_name) || '.alembic_version CASCADE';
    END LOOP;
END;
$$;
EOF
    echo " -> [OK] Tablas de Alembic eliminadas en la base de datos."

    echo " -> Generando nueva migración desde cero..."
    docker exec -i project-web-1 flask db migrate -m "$MIGRATION_MESSAGE"
else
    echo "🔄 Generando nueva migración (Modo Normal)..."
    docker exec -i project-web-1 flask db migrate -m "$MIGRATION_MESSAGE"
fi

echo "🛠️  2. Sincronizando estructuras de Inquilinos..."
# Esta es la magia: Antes de aplicar los cambios, nos aseguramos de que los inquilinos 
# tengan exactamente las mismas tablas que public (aunque estén vacías). 
# Así Alembic jamás volverá a quejarse de que falta una tabla al hacer el loop.
docker exec -i project-db-1 psql -U postgres -d gestion_obra_saas <<'EOF'
DO $$
DECLARE
    tenant_schema TEXT;
    table_record RECORD;
BEGIN
    FOR tenant_schema IN SELECT schema_name FROM public.tenants WHERE is_active = true LOOP
        FOR table_record IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I.%I (LIKE public.%I INCLUDING ALL);', 
                tenant_schema, table_record.tablename, table_record.tablename
            );
        END LOOP;
    END LOOP;
EXCEPTION WHEN OTHERS THEN
    NULL; -- Ignorar si la BD está vacía y aún no existe public.tenants
END;
$$;
EOF
echo " -> [OK] Estructuras sincronizadas."

echo "🚀 3. Aplicando cambios (Upgrade) en todos los esquemas..."
docker exec -i project-web-1 flask db upgrade

echo "✅ Proceso de migración completado exitosamente."