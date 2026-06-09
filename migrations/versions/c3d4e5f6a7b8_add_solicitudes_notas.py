"""add solicitudes notas

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-09 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'solicitudes' not in inspector.get_table_names():
        return
    columns = {col['name'] for col in inspector.get_columns('solicitudes')}
    if 'notas' not in columns:
        op.add_column('solicitudes', sa.Column('notas', sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'solicitudes' not in inspector.get_table_names():
        return
    columns = {col['name'] for col in inspector.get_columns('solicitudes')}
    if 'notas' in columns:
        op.drop_column('solicitudes', 'notas')
