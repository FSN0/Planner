"""add tenant custom_domain

Revision ID: a8f3c2b1d0e9
Revises: e5f6a7b8c9d0
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'a8f3c2b1d0e9'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {col['name'] for col in inspect(bind).get_columns('tenants', schema='public')}
    if 'custom_domain' not in columns:
        op.add_column(
            'tenants',
            sa.Column('custom_domain', sa.String(length=255), nullable=True),
            schema='public',
        )

    op.execute(
        sa.text(
            'CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_custom_domain '
            'ON public.tenants (custom_domain)'
        )
    )


def downgrade():
    bind = op.get_bind()
    columns = {col['name'] for col in inspect(bind).get_columns('tenants', schema='public')}
    if 'custom_domain' not in columns:
        return

    op.drop_index('ix_tenants_custom_domain', table_name='tenants', schema='public')
    op.drop_column('tenants', 'custom_domain', schema='public')