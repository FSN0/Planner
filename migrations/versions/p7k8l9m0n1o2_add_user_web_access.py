"""web_access, email_verified y locale en users + legal_* en tenants

web_access     → login web del operario (independiente del PIN de fichaje).
email_verified → confirmación de correo en el alta autoservicio.
locale         → preferencia de idioma (es/en/pt/fr).
legal_*        → registro de consentimiento RGPD en la tabla pública de tenants.

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

    # --- public.tenants: registro de consentimiento legal del alta ---
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

    if not _column_exists(bind, 'users', 'web_access', schema):
        op.add_column(
            'users',
            sa.Column(
                'web_access',
                sa.Boolean(),
                nullable=False,
                server_default='false',
            ),
            schema=schema,
        )

    if not _column_exists(bind, 'users', 'email_verified', schema):
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
        # Cuentas existentes se consideran verificadas (no pasaron por el alta pública).
        bind.execute(text(f'UPDATE "{schema}".users SET email_verified = true'))

    if not _column_exists(bind, 'users', 'locale', schema):
        op.add_column(
            'users',
            sa.Column('locale', sa.String(length=8), nullable=True),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()

    tenant_cols = {c['name'] for c in inspect(bind).get_columns('tenants', schema='public')}
    for col in ('legal_condiciones_version', 'legal_privacidad_version', 'legal_aceptado_at'):
        if col in tenant_cols:
            op.drop_column('tenants', col, schema='public')

    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'users', schema):
        return

    for col in ('locale', 'email_verified', 'web_access'):
        if _column_exists(bind, 'users', col, schema):
            op.drop_column('users', col, schema=schema)
