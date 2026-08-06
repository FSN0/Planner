"""external auth fields for Odoo fallback

Revision ID: u2b3c4d5e6f7
Revises: t1a2b3c4d5e6
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'u2b3c4d5e6f7'
down_revision = 't1a2b3c4d5e6'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def _column_exists(bind, table_name, column_name, schema):
    columns = {c['name'] for c in inspect(bind).get_columns(table_name, schema=schema)}
    return column_name in columns


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'users', schema):
        return

    if not _column_exists(bind, 'users', 'auth_source_last', schema):
        op.add_column(
            'users',
            sa.Column('auth_source_last', sa.String(length=20), nullable=True),
            schema=schema,
        )
    if not _column_exists(bind, 'users', 'odoo_verified_at', schema):
        op.add_column(
            'users',
            sa.Column('odoo_verified_at', sa.DateTime(), nullable=True),
            schema=schema,
        )
    if not _column_exists(bind, 'users', 'odoo_password_sig', schema):
        op.add_column(
            'users',
            sa.Column('odoo_password_sig', sa.String(length=64), nullable=True),
            schema=schema,
        )
    if not _column_exists(bind, 'users', 'odoo_fallback_disabled', schema):
        op.add_column(
            'users',
            sa.Column(
                'odoo_fallback_disabled',
                sa.Boolean(),
                nullable=False,
                server_default='false',
            ),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'users', schema):
        return

    for column_name in (
        'odoo_fallback_disabled',
        'odoo_password_sig',
        'odoo_verified_at',
        'auth_source_last',
    ):
        if _column_exists(bind, 'users', column_name, schema):
            op.drop_column('users', column_name, schema=schema)
