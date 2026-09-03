"""Registro tenant_roles: etiquetas y alta de roles personalizados por tenant

Revision ID: f5a6b7c8d9e0
Revises: d3e4f5a6b7c8
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'f5a6b7c8d9e0'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None

_BUILTIN_ROWS = (
    ('admin', 'Administrador', True, True, 10),
    ('jefe_obra', 'Jefe de obra', True, True, 20),
    ('laboral', 'Laboral', True, False, 30),
    ('rrhh', 'RRHH', True, False, 40),
    ('operario', 'Operario', True, True, 50),
)


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    if schema == 'public':
        return

    if not _table_exists(bind, 'tenant_roles', schema):
        op.create_table(
            'tenant_roles',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('key', sa.String(length=40), nullable=False),
            sa.Column('label', sa.String(length=80), nullable=False),
            sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('is_locked', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('100')),
            sa.Column('clone_from', sa.String(length=40), nullable=True),
            sa.UniqueConstraint('key', name='uq_tenant_roles_key'),
            schema=schema,
        )
        op.create_index(
            'ix_tenant_roles_key',
            'tenant_roles',
            ['key'],
            unique=True,
            schema=schema,
        )

    for key, label, is_system, is_locked, sort_order in _BUILTIN_ROWS:
        bind.execute(
            text(
                f"""
                INSERT INTO {schema}.tenant_roles
                    (key, label, is_system, is_locked, sort_order, clone_from)
                VALUES
                    (:key, :label, :is_system, :is_locked, :sort_order, NULL)
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {
                'key': key,
                'label': label,
                'is_system': is_system,
                'is_locked': is_locked,
                'sort_order': sort_order,
            },
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or schema == 'public':
        return
    if not _table_exists(bind, 'tenant_roles', schema):
        return
    op.drop_index('ix_tenant_roles_key', table_name='tenant_roles', schema=schema)
    op.drop_table('tenant_roles', schema=schema)
