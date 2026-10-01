"""Tabla role_permissions: matriz Rol × Módulo × R/W/X por tenant

Revision ID: x5e6f7g8h9i0
Revises: w4d5e6f7g8h9
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'x5e6f7g8h9i0'
down_revision = 'w4d5e6f7g8h9'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    # Matriz por tenant (esquemas de cliente). En public no aplica.
    if schema == 'public':
        return
    if _table_exists(bind, 'role_permissions', schema):
        return

    op.create_table(
        'role_permissions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('role', sa.String(length=30), nullable=False),
        sa.Column('module', sa.String(length=50), nullable=False),
        sa.Column('can_read', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('can_write', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('can_execute', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.UniqueConstraint('role', 'module', name='uq_role_permissions_role_module'),
        schema=schema,
    )
    op.create_index(
        'ix_role_permissions_role',
        'role_permissions',
        ['role'],
        schema=schema,
    )
    op.create_index(
        'ix_role_permissions_module',
        'role_permissions',
        ['module'],
        schema=schema,
    )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or schema == 'public':
        return
    if not _table_exists(bind, 'role_permissions', schema):
        return
    op.drop_index('ix_role_permissions_module', table_name='role_permissions', schema=schema)
    op.drop_index('ix_role_permissions_role', table_name='role_permissions', schema=schema)
    op.drop_table('role_permissions', schema=schema)
