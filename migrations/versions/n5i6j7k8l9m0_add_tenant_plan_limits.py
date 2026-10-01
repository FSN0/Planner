"""Plan freemium en tenants (cupo de plantilla)

Añade plan y limite_empleados en public.tenants. Los clientes ya provisionados
pasan a 'paid' para no cortarles el servicio al desplegar el freemium.

Revision ID: n5i6j7k8l9m0
Revises: m4h5i6j7k8l9
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'n5i6j7k8l9m0'
down_revision = 'm4h5i6j7k8l9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in inspect(bind).get_columns('tenants', schema='public')}

    if 'plan' not in columns:
        op.add_column(
            'tenants',
            sa.Column('plan', sa.String(length=20), nullable=False, server_default='free'),
            schema='public',
        )
    if 'limite_empleados' not in columns:
        op.add_column(
            'tenants',
            sa.Column('limite_empleados', sa.Integer(), nullable=True),
            schema='public',
        )

    # Quien ya estaba en producción no se queda bloqueado en free.
    bind.execute(text(
        "UPDATE public.tenants "
        "SET plan = 'paid', limite_empleados = NULL "
        "WHERE COALESCE(plan, 'free') = 'free'"
    ))


def downgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in inspect(bind).get_columns('tenants', schema='public')}
    if 'limite_empleados' in columns:
        op.drop_column('tenants', 'limite_empleados', schema='public')
    if 'plan' in columns:
        op.drop_column('tenants', 'plan', schema='public')
