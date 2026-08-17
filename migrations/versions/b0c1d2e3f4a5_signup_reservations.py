"""Reservas de alta pública (tenant al confirmar el correo)

Revision ID: b0c1d2e3f4a5
Revises: b1c2d3e4f5a6
Create Date: 2026-08-17
"""
from alembic import op
from sqlalchemy import inspect, text


revision = 'b0c1d2e3f4a5'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if schema != 'public':
        return
    if _table_exists(bind, 'signup_reservations', 'public'):
        return

    bind.execute(text("""
        CREATE TABLE public.signup_reservations (
            id SERIAL PRIMARY KEY,
            subdominio VARCHAR(50) NOT NULL,
            nombre_empresa VARCHAR(100) NOT NULL,
            admin_email VARCHAR(120) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            locale VARCHAR(8),
            legal_privacidad_version VARCHAR(32),
            legal_condiciones_version VARCHAR(32),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            tenant_id INTEGER REFERENCES public.tenants(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE,
            updated_at TIMESTAMP WITHOUT TIME ZONE,
            expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            error_message VARCHAR(255)
        )
    """))
    bind.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_signup_reservations_subdominio_live "
        "ON public.signup_reservations (subdominio) "
        "WHERE status IN ('pending', 'provisioning', 'ready')"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_signup_reservations_admin_email "
        "ON public.signup_reservations (admin_email)"
    ))


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if schema != 'public':
        return
    if not _table_exists(bind, 'signup_reservations', 'public'):
        return
    bind.execute(text('DROP TABLE IF EXISTS public.signup_reservations'))
