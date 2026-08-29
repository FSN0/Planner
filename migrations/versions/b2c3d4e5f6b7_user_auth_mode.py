"""users.auth_mode — pin, password o ambos

Revision ID: b2c3d4e5f6b7
Revises: a1b2c3d4e5f7
Create Date: 2026-08-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'b2c3d4e5f6b7'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _column_exists(bind, table_name, column_name, schema):
    columnas = {c['name'] for c in inspect(bind).get_columns(table_name, schema=schema)}
    return column_name in columnas


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or 'users' not in inspect(bind).get_table_names(schema=schema):
        return
    if not _column_exists(bind, 'users', 'auth_mode', schema):
        op.add_column(
            'users',
            sa.Column(
                'auth_mode',
                sa.String(length=16),
                nullable=False,
                server_default='password',
            ),
            schema=schema,
        )
        bind.execute(text(
            f"UPDATE \"{schema}\".users "
            f"SET auth_mode = 'pin' "
            f"WHERE role = 'operario'"
        ))


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _column_exists(bind, 'users', 'auth_mode', schema):
        return
    op.drop_column('users', 'auth_mode', schema=schema)
