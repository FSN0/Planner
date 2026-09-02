"""add registros_fichajes odoo metric columns (UD, MOD, Total HH, MOE)

Revision ID: h1i2j3k4l5m6
Revises: c2d3e4f5a6b7
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'h1i2j3k4l5m6'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None

_COLUMNS = (
    ('odoo_ud', 'UD'),
    ('odoo_mod', 'MOD'),
    ('odoo_total_hh', 'Total HH'),
    ('odoo_moe', 'MOE'),
)


def upgrade():
    bind = op.get_bind()
    if 'registros_fichajes' not in inspect(bind).get_table_names():
        return

    existing = {col['name'] for col in inspect(bind).get_columns('registros_fichajes')}
    with op.batch_alter_table('registros_fichajes', schema=None) as batch_op:
        for name, _label in _COLUMNS:
            if name in existing:
                continue
            batch_op.add_column(sa.Column(name, sa.Numeric(12, 4), nullable=True))


def downgrade():
    bind = op.get_bind()
    if 'registros_fichajes' not in inspect(bind).get_table_names():
        return

    existing = {col['name'] for col in inspect(bind).get_columns('registros_fichajes')}
    with op.batch_alter_table('registros_fichajes', schema=None) as batch_op:
        for name, _label in reversed(_COLUMNS):
            if name not in existing:
                continue
            batch_op.drop_column(name)
