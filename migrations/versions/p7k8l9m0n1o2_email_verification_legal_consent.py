"""Verificación de correo (users) y consentimiento legal (tenants)

User.email_verified: el admin del alta pública no entra hasta confirmar el enlace.
Tenant.legal_*: guarda cuándo y qué versión de privacidad/condiciones aceptó.

Revision ID: p7k8l9m0n1o2
Revises: q8l9m0n1o2p3
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'p7k8l9m0n1o2'
down_revision = 'q8l9m0n1o2p3'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def _column_exists(bind, table_name, column_name, schema):
    columnas = {c['name'] for c in inspect(bind).get_columns(table_name, schema=schema)}
    return column_name in columnas


def upgrade():
    bind = op.get_bind()

    # --- public.tenants: consentimiento legal del alta ---
    tenant_cols = {c['name'] for c in inspect(bind).get_columns('tenants', schema='public')}
    if 'legal_aceptado_at' not in tenant_cols:
        op.add_column(
            'tenants',
            sa.Column('legal_aceptado_at', sa.DateTime(), nullable=True),
            schema='public',
        )
    if 'legal_privacidad_version' not in tenant_cols:
        op.add_column(
            'tenants',
            sa.Column('legal_privacidad_version', sa.String(length=32), nullable=True),
            schema='public',
        )
    if 'legal_condiciones_version' not in tenant_cols:
        op.add_column(
            'tenants',
            sa.Column('legal_condiciones_version', sa.String(length=32), nullable=True),
            schema='public',
        )

    # --- users por tenant (env.py cambia search_path en cada esquema) ---
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'users', schema):
        return
    if _column_exists(bind, 'users', 'email_verified', schema):
        return

    op.add_column(
        'users',
        sa.Column(
            'email_verified',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
        schema=schema,
    )
    # Cuentas ya en producción se consideran verificadas (no pasaron por el alta).
    # El alta pública crea el admin con email_verified=False vía provision.
    bind.execute(text(
        f'UPDATE "{schema}".users SET email_verified = true'
    ))


def downgrade():
    bind = op.get_bind()

    tenant_cols = {c['name'] for c in inspect(bind).get_columns('tenants', schema='public')}
    for col in (
        'legal_condiciones_version',
        'legal_privacidad_version',
        'legal_aceptado_at',
    ):
        if col in tenant_cols:
            op.drop_column('tenants', col, schema='public')

    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'users', schema):
        return
    if not _column_exists(bind, 'users', 'email_verified', schema):
        return

    op.drop_column('users', 'email_verified', schema=schema)
