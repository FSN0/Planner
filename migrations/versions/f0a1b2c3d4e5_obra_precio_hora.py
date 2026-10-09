"""Obra.precio_hora: tarifa opcional por obra para certificación.

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-10-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'f0a1b2c3d4e5'
down_revision = 'e9f0a1b2c3d4'
branch_labels = None
depends_on = None


def _schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _tables(bind, schema):
    return set(inspect(bind).get_table_names(schema=schema))


def _cols(bind, table, schema):
    return {c['name'] for c in inspect(bind).get_columns(table, schema=schema)}


def upgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    if 'obras' not in _tables(bind, schema):
        return
    cols = _cols(bind, 'obras', schema)
    if 'precio_hora' not in cols:
        with op.batch_alter_table('obras', schema=schema) as batch:
            batch.add_column(sa.Column('precio_hora', sa.Numeric(10, 2), nullable=True))


def downgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    if 'obras' not in _tables(bind, schema):
        return
    cols = _cols(bind, 'obras', schema)
    if 'precio_hora' in cols:
        with op.batch_alter_table('obras', schema=schema) as batch:
            batch.drop_column('precio_hora')
