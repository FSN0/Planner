"""add tms.shipment fields to registros_odometro

Revision ID: k2f3g4h5i6j7
Revises: j1e2f3g4h5i6
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'k2f3g4h5i6j7'
down_revision = 'j1e2f3g4h5i6'
branch_labels = None
depends_on = None


_COLS = (
    ('km_start', sa.Float()),
    ('qty_km', sa.Float()),
    ('km_previsto', sa.Float()),
    ('desvio', sa.Float()),
    ('viaje_code', sa.String(64)),
    ('viaje_odoo_id', sa.Integer()),
)


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'registros_odometro', schema):
        return

    columns = {col['name'] for col in inspect(bind).get_columns('registros_odometro', schema=schema)}
    for name, col_type in _COLS:
        if name not in columns:
            op.add_column(
                'registros_odometro',
                sa.Column(name, col_type, nullable=True),
                schema=schema,
            )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'registros_odometro', schema):
        return

    columns = {col['name'] for col in inspect(bind).get_columns('registros_odometro', schema=schema)}
    for name, _ in reversed(_COLS):
        if name in columns:
            op.drop_column('registros_odometro', name, schema=schema)
