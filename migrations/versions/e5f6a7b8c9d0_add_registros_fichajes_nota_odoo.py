"""add registros_fichajes nota_odoo

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
    inspector = inspect(bind)
    if 'registros_fichajes' not in inspector.get_table_names():
        return
    columns = {col['name'] for col in inspector.get_columns('registros_fichajes')}
    if 'nota_odoo' not in columns:
        op.add_column('registros_fichajes', sa.Column('nota_odoo', sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'registros_fichajes' not in inspector.get_table_names():
        return
    columns = {col['name'] for col in inspector.get_columns('registros_fichajes')}
    if 'nota_odoo' in columns:
        op.drop_column('registros_fichajes', 'nota_odoo')
