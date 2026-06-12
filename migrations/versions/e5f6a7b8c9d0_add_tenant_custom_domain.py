"""add tenant custom_domain

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'tenants',
        sa.Column('custom_domain', sa.String(length=255), nullable=True),
        schema='public',
    )
    op.create_index(
        'ix_tenants_custom_domain',
        'tenants',
        ['custom_domain'],
        unique=True,
        schema='public',
    )


def downgrade():
    op.drop_index('ix_tenants_custom_domain', table_name='tenants', schema='public')
    op.drop_column('tenants', 'custom_domain', schema='public')
