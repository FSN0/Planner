"""add visto flag to sync_logs (dismiss errors in Odoo panel)

Revision ID: c2d3e4f5a6b7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'c2d3e4f5a6b7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def _column_exists(bind, table_name, column_name, schema):
    if not _table_exists(bind, table_name, schema):
        return False
    columnas = {c['name'] for c in inspect(bind).get_columns(table_name, schema=schema)}
    return column_name in columnas


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'sync_logs', schema):
        return
    if not _column_exists(bind, 'sync_logs', 'visto', schema):
        op.add_column(
            'sync_logs',
            sa.Column('visto', sa.Boolean(), server_default=sa.text('false'), nullable=False),
            schema=schema,
        )
    if not _column_exists(bind, 'sync_logs', 'visto_en', schema):
        op.add_column(
            'sync_logs',
            sa.Column('visto_en', sa.DateTime(), nullable=True),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    if _column_exists(bind, 'sync_logs', 'visto_en', schema):
        op.drop_column('sync_logs', 'visto_en', schema=schema)
    if _column_exists(bind, 'sync_logs', 'visto', schema):
        op.drop_column('sync_logs', 'visto', schema=schema)
