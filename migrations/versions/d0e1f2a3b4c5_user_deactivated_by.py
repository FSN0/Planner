"""Quién dio de baja / eliminó al usuario.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'd0e1f2a3b4c5'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def _column_exists(bind, table_name, column_name, schema):
    if not _table_exists(bind, table_name, schema):
        return False
    columnas = {c['name'] for c in inspect(bind).get_columns(table_name, schema=schema)}
    return column_name in columnas


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'users', schema):
        return
    if _column_exists(bind, 'users', 'deactivated_by_id', schema):
        return
    op.add_column(
        'users',
        sa.Column('deactivated_by_id', sa.Integer(), nullable=True),
        schema=schema,
    )
    try:
        op.create_foreign_key(
            'fk_users_deactivated_by_id',
            'users',
            'users',
            ['deactivated_by_id'],
            ['id'],
            source_schema=schema,
            referent_schema=schema,
            ondelete='SET NULL',
        )
    except Exception:
        pass


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _column_exists(bind, 'users', 'deactivated_by_id', schema):
        return
    try:
        op.drop_constraint(
            'fk_users_deactivated_by_id',
            'users',
            schema=schema,
            type_='foreignkey',
        )
    except Exception:
        pass
    op.drop_column('users', 'deactivated_by_id', schema=schema)
