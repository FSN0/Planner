"""Campos de facturación en tenants (preparado para Stripe)

billing_exempt: premium sin cobro (Soltec, demos, cortesías).
stripe_*: huecos para cuando exista entidad legal y cuenta Stripe.

Revision ID: o6j7k8l9m0n1
Revises: n5i6j7k8l9m0
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'o6j7k8l9m0n1'
down_revision = 'n5i6j7k8l9m0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in inspect(bind).get_columns('tenants', schema='public')}

    if 'billing_exempt' not in columns:
        op.add_column(
            'tenants',
            sa.Column('billing_exempt', sa.Boolean(), nullable=False, server_default='false'),
            schema='public',
        )
    if 'stripe_customer_id' not in columns:
        op.add_column(
            'tenants',
            sa.Column('stripe_customer_id', sa.String(length=120), nullable=True),
            schema='public',
        )
    if 'stripe_subscription_id' not in columns:
        op.add_column(
            'tenants',
            sa.Column('stripe_subscription_id', sa.String(length=120), nullable=True),
            schema='public',
        )

    # Quien ya está en paid no debe quedar pendiente de cobro al activar Stripe.
    bind.execute(text(
        "UPDATE public.tenants SET billing_exempt = true "
        "WHERE plan = 'paid' AND COALESCE(billing_exempt, false) = false"
    ))


def downgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in inspect(bind).get_columns('tenants', schema='public')}
    for col in ('stripe_subscription_id', 'stripe_customer_id', 'billing_exempt'):
        if col in columns:
            op.drop_column('tenants', col, schema='public')
