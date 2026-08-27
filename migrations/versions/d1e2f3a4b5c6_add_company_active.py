"""Add companies.active for archival without losing history

Permite dar de baja una subcontrata (sin personal activo) sin borrar
el historial de asignaciones ni los usuarios vinculados.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-08-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'd1e2f3a4b5c6'
down_revision = 'c0d1e2f3a4b5'
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
    if not schema:
        return
    if not _table_exists(bind, 'companies', schema):
        return
    if _column_exists(bind, 'companies', 'active', schema):
        return
    op.add_column(
        'companies',
        sa.Column(
            'active',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        ),
        schema=schema,
    )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    if _column_exists(bind, 'companies', 'active', schema):
        op.drop_column('companies', 'active', schema=schema)
