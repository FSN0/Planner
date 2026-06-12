"""add registros_fichajes.nota_odoo

Revision ID: b4c5d6e7f8a9
Revises: a8f3c2b1d0e9
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'b4c5d6e7f8a9'
down_revision = 'a8f3c2b1d0e9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('registros_fichajes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('nota_odoo', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('registros_fichajes', schema=None) as batch_op:
        batch_op.drop_column('nota_odoo')
