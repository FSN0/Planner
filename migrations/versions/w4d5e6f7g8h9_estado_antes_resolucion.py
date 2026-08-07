"""estado_antes_resolucion on registros_fichajes (reabrir auditoría)

Revision ID: w4d5e6f7g8h9
Revises: v3c4d5e6f7g8
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'w4d5e6f7g8h9'
down_revision = 'v3c4d5e6f7g8'
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
    if not _column_exists(bind, 'registros_fichajes', 'estado_antes_resolucion', schema):
        op.add_column(
            'registros_fichajes',
            sa.Column('estado_antes_resolucion', sa.String(length=50), nullable=True),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'registros_fichajes', schema):
        return
    if _column_exists(bind, 'registros_fichajes', 'estado_antes_resolucion', schema):
        op.drop_column('registros_fichajes', 'estado_antes_resolucion', schema=schema)
