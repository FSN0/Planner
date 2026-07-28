"""add registros_odometro for vehicle audit

Revision ID: j1e2f3g4h5i6
Revises: i0d1e2f3g4h5
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'j1e2f3g4h5i6'
down_revision = 'i0d1e2f3g4h5'
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

    if not _table_exists(bind, 'vehiculos', schema):
        return

    if not _table_exists(bind, 'registros_odometro', schema):
        op.create_table(
            'registros_odometro',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('vehiculo_id', sa.Integer(), sa.ForeignKey(f'{schema}.vehiculos.id'), nullable=False),
            sa.Column('fecha', sa.Date(), nullable=False),
            sa.Column('valor', sa.Float(), nullable=True),
            sa.Column('odoo_driver_partner_id', sa.Integer(), nullable=True),
            sa.Column('odoo_driver_name', sa.String(160), nullable=True),
            sa.Column('planned_user_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=True),
            sa.Column('estado', sa.String(40), nullable=False, server_default='ok'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('vehiculo_id', 'fecha', name='uq_odometro_vehiculo_fecha'),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return

    if _table_exists(bind, 'registros_odometro', schema):
        op.drop_table('registros_odometro', schema=schema)
