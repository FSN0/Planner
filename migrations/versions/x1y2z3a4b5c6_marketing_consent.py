"""Consentimiento de comunicaciones comerciales (alta + leads contacto)

Revision ID: x1y2z3a4b5c6
Revises: k5e6f7g8h9i0
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'x1y2z3a4b5c6'
down_revision = 'k5e6f7g8h9i0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tenant_cols = {c['name'] for c in inspect(bind).get_columns('tenants', schema='public')}
    if 'marketing_consent_at' not in tenant_cols:
        op.add_column(
            'tenants',
            sa.Column('marketing_consent_at', sa.DateTime(), nullable=True),
            schema='public',
        )
    if 'marketing_consent_ip' not in tenant_cols:
        op.add_column(
            'tenants',
            sa.Column('marketing_consent_ip', sa.String(length=64), nullable=True),
            schema='public',
        )
    if 'marketing_consent_source' not in tenant_cols:
        op.add_column(
            'tenants',
            sa.Column('marketing_consent_source', sa.String(length=40), nullable=True),
            schema='public',
        )

    res_cols = {
        c['name'] for c in inspect(bind).get_columns('signup_reservations', schema='public')
    }
    if 'marketing_consent_at' not in res_cols:
        op.add_column(
            'signup_reservations',
            sa.Column('marketing_consent_at', sa.DateTime(), nullable=True),
            schema='public',
        )
    if 'marketing_consent_ip' not in res_cols:
        op.add_column(
            'signup_reservations',
            sa.Column('marketing_consent_ip', sa.String(length=64), nullable=True),
            schema='public',
        )
    if 'marketing_consent_source' not in res_cols:
        op.add_column(
            'signup_reservations',
            sa.Column('marketing_consent_source', sa.String(length=40), nullable=True),
            schema='public',
        )

    tables = set(inspect(bind).get_table_names(schema='public'))
    if 'marketing_leads' not in tables:
        op.create_table(
            'marketing_leads',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('email', sa.String(length=120), nullable=False),
            sa.Column('nombre', sa.String(length=120), nullable=True),
            sa.Column('empresa', sa.String(length=160), nullable=True),
            sa.Column('source', sa.String(length=40), nullable=False),
            sa.Column('locale', sa.String(length=8), nullable=True),
            sa.Column('mensaje', sa.Text(), nullable=True),
            sa.Column('marketing_consent', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('marketing_consent_at', sa.DateTime(), nullable=True),
            sa.Column('marketing_consent_ip', sa.String(length=64), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
            schema='public',
        )
        op.create_index(
            'ix_marketing_leads_email',
            'marketing_leads',
            ['email'],
            schema='public',
        )
        op.create_index(
            'ix_marketing_leads_consent',
            'marketing_leads',
            ['marketing_consent', 'created_at'],
            schema='public',
        )


def downgrade():
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names(schema='public'))
    if 'marketing_leads' in tables:
        op.drop_index('ix_marketing_leads_consent', table_name='marketing_leads', schema='public')
        op.drop_index('ix_marketing_leads_email', table_name='marketing_leads', schema='public')
        op.drop_table('marketing_leads', schema='public')

    res_cols = {
        c['name'] for c in inspect(bind).get_columns('signup_reservations', schema='public')
    }
    for col in ('marketing_consent_source', 'marketing_consent_ip', 'marketing_consent_at'):
        if col in res_cols:
            op.drop_column('signup_reservations', col, schema='public')

    tenant_cols = {c['name'] for c in inspect(bind).get_columns('tenants', schema='public')}
    for col in ('marketing_consent_source', 'marketing_consent_ip', 'marketing_consent_at'):
        if col in tenant_cols:
            op.drop_column('tenants', col, schema='public')
