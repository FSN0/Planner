"""Decisiones a favor/en contra en desvío de fichaje.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def _column_exists(bind, table_name, column_name, schema):
    columnas = {c['name'] for c in inspect(bind).get_columns(table_name, schema=schema)}
    return column_name in columnas


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'registros_fichajes', schema):
        return
    for name in ('desvio_decision_plan', 'desvio_decision_real'):
        if not _column_exists(bind, 'registros_fichajes', name, schema):
            op.add_column(
                'registros_fichajes',
                sa.Column(name, sa.String(length=20), nullable=True),
                schema=schema,
            )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'registros_fichajes', schema):
        return
    for name in ('desvio_decision_real', 'desvio_decision_plan'):
        if _column_exists(bind, 'registros_fichajes', name, schema):
            op.drop_column('registros_fichajes', name, schema=schema)
