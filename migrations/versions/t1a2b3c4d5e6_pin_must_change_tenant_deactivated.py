"""pin_must_change + tenant.deactivated_at

Revision ID: t1a2b3c4d5e6
Revises: s0t1u2v3w4x5
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 't1a2b3c4d5e6'
down_revision = 's0t1u2v3w4x5'
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
    if not schema:
        return

    if schema == 'public' and _table_exists(bind, 'tenants', schema):
        if not _column_exists(bind, 'tenants', 'deactivated_at', schema):
            op.add_column(
                'tenants',
                sa.Column('deactivated_at', sa.DateTime(), nullable=True),
                schema=schema,
            )

    if _table_exists(bind, 'users', schema):
        if not _column_exists(bind, 'users', 'pin_must_change', schema):
            op.add_column(
                'users',
                sa.Column(
                    'pin_must_change',
                    sa.Boolean(),
                    nullable=False,
                    server_default='false',
                ),
                schema=schema,
            )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return

    if _table_exists(bind, 'users', schema) and _column_exists(
        bind, 'users', 'pin_must_change', schema
    ):
        op.drop_column('users', 'pin_must_change', schema=schema)

    if schema == 'public' and _table_exists(bind, 'tenants', schema):
        if _column_exists(bind, 'tenants', 'deactivated_at', schema):
            op.drop_column('tenants', 'deactivated_at', schema=schema)
