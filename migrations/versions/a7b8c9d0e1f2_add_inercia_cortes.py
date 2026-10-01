"""Cortes de inercia: la casa se corta sin filas fantasma en asignaciones.

Revision ID: a7b8c9d0e1f2
Revises: m6n7o8p9q0r1
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'a7b8c9d0e1f2'
down_revision = 'm6n7o8p9q0r1'
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
    if _table_exists(bind, 'inercia_cortes', schema):
        return

    op.create_table(
        'inercia_cortes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('autor_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('user_id', 'fecha', name='uq_inercia_corte_user_fecha'),
        schema=schema,
    )
    op.create_index(
        'ix_inercia_cortes_user_id',
        'inercia_cortes',
        ['user_id'],
        schema=schema,
    )
    op.create_index(
        'ix_inercia_cortes_fecha',
        'inercia_cortes',
        ['fecha'],
        schema=schema,
    )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    if not _table_exists(bind, 'inercia_cortes', schema):
        return
    op.drop_index('ix_inercia_cortes_fecha', table_name='inercia_cortes', schema=schema)
    op.drop_index('ix_inercia_cortes_user_id', table_name='inercia_cortes', schema=schema)
    op.drop_table('inercia_cortes', schema=schema)
