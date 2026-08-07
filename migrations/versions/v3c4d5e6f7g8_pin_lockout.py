"""pin_failed_attempts + pin_locked_until

Revision ID: v3c4d5e6f7g8
Revises: u2b3c4d5e6f7
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'v3c4d5e6f7g8'
down_revision = 'u2b3c4d5e6f7'
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
    if not _column_exists(bind, 'users', 'pin_failed_attempts', schema):
        op.add_column(
            'users',
            sa.Column(
                'pin_failed_attempts',
                sa.Integer(),
                nullable=False,
                server_default='0',
            ),
            schema=schema,
        )
    if not _column_exists(bind, 'users', 'pin_locked_until', schema):
        op.add_column(
            'users',
            sa.Column('pin_locked_until', sa.DateTime(), nullable=True),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'users', schema):
        return
    if _column_exists(bind, 'users', 'pin_locked_until', schema):
        op.drop_column('users', 'pin_locked_until', schema=schema)
    if _column_exists(bind, 'users', 'pin_failed_attempts', schema):
        op.drop_column('users', 'pin_failed_attempts', schema=schema)
