"""add users timezone

Revision ID: a1b2c3d4e5f6
Revises: d1462b5b0305
Create Date: 2026-06-09 14:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'a1b2c3d4e5f6'
down_revision = 'd1462b5b0305'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'users' not in inspector.get_table_names():
        return
    columns = {col['name'] for col in inspector.get_columns('users')}
    if 'timezone' not in columns:
        op.add_column('users', sa.Column('timezone', sa.String(length=64), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'users' not in inspector.get_table_names():
        return
    columns = {col['name'] for col in inspector.get_columns('users')}
    if 'timezone' in columns:
        op.drop_column('users', 'timezone')
