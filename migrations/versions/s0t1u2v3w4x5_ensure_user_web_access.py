"""ensure users.web_access (and email_verified/locale) exist

p7k8l9m0n1o2 was originally email_verification_legal_consent and was later
rewritten to also add web_access. Schemas already stamped at r9s0t1u2v3w4
never received web_access. This revision is idempotent.

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 's0t1u2v3w4x5'
down_revision = 'r9s0t1u2v3w4'
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
        bind.execute(text(f'UPDATE "{schema}".users SET email_verified = true'))

    if not _column_exists(bind, 'users', 'locale', schema):
        op.add_column(
            'users',
            sa.Column('locale', sa.String(length=8), nullable=True),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'users', schema):
        return
    # Only drop web_access (the gap this revision closes). Leave email_verified/locale.
    if _column_exists(bind, 'users', 'web_access', schema):
        op.drop_column('users', 'web_access', schema=schema)
