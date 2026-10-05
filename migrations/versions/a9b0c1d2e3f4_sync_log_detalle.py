"""sync_logs: detalle JSON + quién lanzó la sync

Revision ID: a9b0c1d2e3f4
Revises: f2a3b4c5d6e7
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import JSONB


revision = 'a9b0c1d2e3f4'
down_revision = 'f2a3b4c5d6e7'
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
    if not _column_exists(bind, 'sync_logs', 'detalle_json', schema):
        op.add_column(
            'sync_logs',
            sa.Column('detalle_json', JSONB(), nullable=True),
            schema=schema,
        )
    if not _column_exists(bind, 'sync_logs', 'lanzado_por_id', schema):
        op.add_column(
            'sync_logs',
            sa.Column('lanzado_por_id', sa.Integer(), nullable=True),
            schema=schema,
        )
    if not _column_exists(bind, 'sync_logs', 'lanzado_por_label', schema):
        op.add_column(
            'sync_logs',
            sa.Column('lanzado_por_label', sa.String(length=120), nullable=True),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    for col in ('lanzado_por_label', 'lanzado_por_id', 'detalle_json'):
        if _column_exists(bind, 'sync_logs', col, schema):
            op.drop_column('sync_logs', col, schema=schema)
