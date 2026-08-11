"""Índices en system_logs para badges de no leídos

Revision ID: z7g8h9i0j1k2
Revises: y6f7g8h9i0j1
Create Date: 2026-08-10
"""
from alembic import op
from sqlalchemy import inspect, text


revision = 'z7g8h9i0j1k2'
down_revision = 'y6f7g8h9i0j1'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def _index_exists(bind, index_name, schema):
    rows = bind.execute(text(
        "SELECT 1 FROM pg_indexes WHERE schemaname = :schema AND indexname = :name LIMIT 1"
    ), {'schema': schema, 'name': index_name}).fetchone()
    return rows is not None


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'system_logs', schema):
        return
    if not _index_exists(bind, 'ix_system_logs_category_timestamp', schema):
        op.create_index(
            'ix_system_logs_category_timestamp',
            'system_logs',
            ['category', 'timestamp'],
            schema=schema,
        )
    if not _index_exists(bind, 'ix_system_logs_timestamp', schema):
        op.create_index(
            'ix_system_logs_timestamp',
            'system_logs',
            ['timestamp'],
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'system_logs', schema):
        return
    if _index_exists(bind, 'ix_system_logs_category_timestamp', schema):
        op.drop_index('ix_system_logs_category_timestamp', table_name='system_logs', schema=schema)
    if _index_exists(bind, 'ix_system_logs_timestamp', schema):
        op.drop_index('ix_system_logs_timestamp', table_name='system_logs', schema=schema)
