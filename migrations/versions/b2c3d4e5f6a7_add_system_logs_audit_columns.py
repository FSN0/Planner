"""add system_logs audit columns

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-09 14:25:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'system_logs' not in inspector.get_table_names():
        return

    columns = {col['name'] for col in inspector.get_columns('system_logs')}

    if 'target_user_id' not in columns:
        op.add_column(
            'system_logs',
            sa.Column('target_user_id', sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            'fk_system_logs_target_user_id_users',
            'system_logs',
            'users',
            ['target_user_id'],
            ['id'],
        )

    if 'target_date' not in columns:
        op.add_column(
            'system_logs',
            sa.Column('target_date', sa.Date(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'system_logs' not in inspector.get_table_names():
        return

    columns = {col['name'] for col in inspector.get_columns('system_logs')}

    if 'target_date' in columns:
        op.drop_column('system_logs', 'target_date')

    if 'target_user_id' in columns:
        op.drop_constraint('fk_system_logs_target_user_id_users', 'system_logs', type_='foreignkey')
        op.drop_column('system_logs', 'target_user_id')
