"""add anomalias_vehiculo_vista (ack informativo de anomalías de flota)

Revision ID: q8l9m0n1o2p3
Revises: o6j7k8l9m0n1
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'q8l9m0n1o2p3'
down_revision = 'o6j7k8l9m0n1'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return

    if not _table_exists(bind, 'users', schema):
        return
    if _table_exists(bind, 'anomalias_vehiculo_vista', schema):
        return

    op.create_table(
        'anomalias_vehiculo_vista',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('clave', sa.String(160), nullable=False),
        sa.Column('visto_por_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=False),
        sa.Column('visto_en', sa.DateTime(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.UniqueConstraint('kind', 'clave', name='uq_anomalia_vehiculo_vista_kind_clave'),
        schema=schema,
    )
    op.create_index(
        'ix_anomalias_vehiculo_vista_kind',
        'anomalias_vehiculo_vista',
        ['kind'],
        schema=schema,
    )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    if not _table_exists(bind, 'anomalias_vehiculo_vista', schema):
        return
    op.drop_index(
        'ix_anomalias_vehiculo_vista_kind',
        table_name='anomalias_vehiculo_vista',
        schema=schema,
    )
    op.drop_table('anomalias_vehiculo_vista', schema=schema)
