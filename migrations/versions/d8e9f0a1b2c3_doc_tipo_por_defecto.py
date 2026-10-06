"""DocumentoTipo: por_defecto (plantilla) separado de activo.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'd8e9f0a1b2c3'
down_revision = 'c7d8e9f0a1b2'
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
    if 'por_defecto' not in cols:
        with op.batch_alter_table('documento_tipos', schema=schema) as batch:
            batch.add_column(sa.Column(
                'por_defecto', sa.Boolean(), nullable=False, server_default='true',
            ))
        # Lo que ya estaba activo sigue siendo plantilla por defecto.
        bind.execute(text(
            "UPDATE documento_tipos SET por_defecto = activo"
        ))
    cols = _cols(bind, 'documento_tipos', schema)
    if 'created_at' not in cols:
        with op.batch_alter_table('documento_tipos', schema=schema) as batch:
            batch.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    if 'documento_tipos' not in _tables(bind, schema):
        return
    cols = _cols(bind, 'documento_tipos', schema)
    if 'por_defecto' in cols:
        with op.batch_alter_table('documento_tipos', schema=schema) as batch:
            batch.drop_column('por_defecto')
