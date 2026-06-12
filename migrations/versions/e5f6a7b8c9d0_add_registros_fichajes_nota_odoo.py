"""add registros_fichajes.nota_odoo

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if 'registros_fichajes' not in inspect(bind).get_table_names():
        return

    columns = {col['name'] for col in inspect(bind).get_columns('registros_fichajes')}
    if 'nota_odoo' in columns:
        return

    with op.batch_alter_table('registros_fichajes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('nota_odoo', sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if 'registros_fichajes' not in inspect(bind).get_table_names():
        return

    columns = {col['name'] for col in inspect(bind).get_columns('registros_fichajes')}
    if 'nota_odoo' not in columns:
        return

    with op.batch_alter_table('registros_fichajes', schema=None) as batch_op:
        batch_op.drop_column('nota_odoo')
