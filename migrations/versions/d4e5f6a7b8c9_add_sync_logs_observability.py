"""add sync_logs observability columns

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sync_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('estado', sa.String(length=20), server_default='ok', nullable=True))
        batch_op.add_column(sa.Column('duracion_ms', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('mensaje_error', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('sync_logs', schema=None) as batch_op:
        batch_op.drop_column('mensaje_error')
        batch_op.drop_column('duracion_ms')
        batch_op.drop_column('estado')
