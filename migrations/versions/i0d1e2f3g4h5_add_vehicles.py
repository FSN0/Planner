"""add vehicles tables (vehiculos, asignaciones, solicitudes)

Revision ID: i0d1e2f3g4h5
Revises: h9c0d1e2f3g4
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import JSONB


revision = 'i0d1e2f3g4h5'
down_revision = 'h9c0d1e2f3g4'
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

    # Solo esquemas de tenant con users
    if not _table_exists(bind, 'users', schema):
        return

    if not _table_exists(bind, 'vehiculos', schema):
        op.create_table(
            'vehiculos',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('external_ids', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column('nombre', sa.String(120), nullable=False),
            sa.Column('matricula', sa.String(40), nullable=True),
            sa.Column('marca', sa.String(80), nullable=True),
            sa.Column('modelo', sa.String(80), nullable=True),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('odoo_driver_partner_id', sa.Integer(), nullable=True),
            sa.Column('odoo_driver_name', sa.String(160), nullable=True),
            sa.Column('odoo_odometer_date', sa.Date(), nullable=True),
            sa.Column('odoo_odometer_value', sa.Float(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('matricula', name='uq_vehiculos_matricula'),
            schema=schema,
        )

    if not _table_exists(bind, 'solicitudes_vehiculo', schema):
        op.create_table(
            'solicitudes_vehiculo',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('accion', sa.String(20), nullable=False, server_default='ASIGNAR'),
            sa.Column('requested_by_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=False),
            sa.Column('empleado_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=False),
            sa.Column('vehiculo_id', sa.Integer(), sa.ForeignKey(f'{schema}.vehiculos.id'), nullable=True),
            sa.Column('fecha_inicio', sa.Date(), nullable=False),
            sa.Column('fecha_fin', sa.Date(), nullable=False),
            sa.Column('estado', sa.String(20), nullable=False, server_default='PENDIENTE'),
            sa.Column('notas', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('resolved_by_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
            schema=schema,
        )

    if not _table_exists(bind, 'asignaciones_vehiculo', schema):
        op.create_table(
            'asignaciones_vehiculo',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('vehiculo_id', sa.Integer(), sa.ForeignKey(f'{schema}.vehiculos.id'), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=False),
            sa.Column('fecha', sa.Date(), nullable=False),
            sa.Column(
                'solicitud_id',
                sa.Integer(),
                sa.ForeignKey(f'{schema}.solicitudes_vehiculo.id', ondelete='SET NULL'),
                nullable=True,
            ),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('vehiculo_id', 'fecha', name='uq_vehiculo_fecha'),
            sa.UniqueConstraint('user_id', 'fecha', name='uq_user_vehiculo_fecha'),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return

    if _table_exists(bind, 'asignaciones_vehiculo', schema):
        op.drop_table('asignaciones_vehiculo', schema=schema)
    if _table_exists(bind, 'solicitudes_vehiculo', schema):
        op.drop_table('solicitudes_vehiculo', schema=schema)
    if _table_exists(bind, 'vehiculos', schema):
        op.drop_table('vehiculos', schema=schema)
