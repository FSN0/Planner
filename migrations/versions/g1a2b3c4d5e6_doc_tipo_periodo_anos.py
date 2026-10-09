"""DocumentoTipo.periodo_anos: caducidad cada X años.

Revision ID: g1a2b3c4d5e6
Revises: f0a1b2c3d4e5
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'g1a2b3c4d5e6'
down_revision = 'f0a1b2c3d4e5'
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
    if 'documento_tipos' not in _tables(bind, schema):
        return
    cols = _cols(bind, 'documento_tipos', schema)
    if 'periodo_anos' not in cols:
        with op.batch_alter_table('documento_tipos', schema=schema) as batch:
            batch.add_column(sa.Column('periodo_anos', sa.Integer(), nullable=True))


def downgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    if 'documento_tipos' not in _tables(bind, schema):
        return
    cols = _cols(bind, 'documento_tipos', schema)
    if 'periodo_anos' in cols:
        with op.batch_alter_table('documento_tipos', schema=schema) as batch:
            batch.drop_column('periodo_anos')
