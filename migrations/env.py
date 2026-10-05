from __future__ import with_statement

import logging
from logging.config import fileConfig

from flask import current_app

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
config.set_main_option(
    'sqlalchemy.url',
    str(current_app.extensions['migrate'].db.get_engine().url).replace(
        '%', '%%'))
target_metadata = current_app.extensions['migrate'].db.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.
def run_migrations_online():
    """Run migrations in 'online' mode."""
    
    # ---> 1. AÑADIMOS ESTE FILTRO PARA IGNORAR LA TABLA DE ALEMBIC <---
    def include_object(object, name, type_, reflected, compare_to):
        if type_ == "table" and name == "alembic_version":
            return False
        return True
    # -----------------------------------------------------------------

    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    connectable = current_app.extensions['migrate'].db.engine

    with connectable.connect() as connection:
        from sqlalchemy import text
        
        # 1. MIGRAR ESQUEMA PUBLIC PRIMERO
        connection.execute(text("SET search_path TO public"))
        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            version_table_schema='public',
            include_object=include_object,  # <--- LE PASAMOS EL FILTRO AQUÍ
            process_revision_directives=process_revision_directives,
            **current_app.extensions['migrate'].configure_args
        )
        with context.begin_transaction():
            context.run_migrations()

        # Si estamos generando el archivo de migración, paramos aquí.
        if getattr(config.cmd_opts, 'autogenerate', False):
            return

        # 2. OBTENER INQUILINOS Y MIGRAR CADA UNO (Solo ocurre al hacer Upgrade)
        try:
            result = connection.execute(text("SELECT schema_name FROM tenants"))
            tenant_schemas = [row[0] for row in result]
        except Exception:
            tenant_schemas = []

        for schema in tenant_schemas:
            print(f"🚀 Aplicando migraciones al inquilino: {schema}")
            connection.execute(text(f"SET search_path TO {schema}"))
            
            context.configure(
                connection=connection, 
                target_metadata=target_metadata,
                version_table_schema=schema,
                include_object=include_object,  # <--- LE PASAMOS EL FILTRO AQUÍ TAMBIÉN
                process_revision_directives=process_revision_directives,
                **current_app.extensions['migrate'].configure_args
            )
            with context.begin_transaction():
                context.run_migrations()
                

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()