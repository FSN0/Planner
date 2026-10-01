"""PIN de fichaje en users (DNI + PIN para la PWA)

Añade pin_hash a la tabla de usuarios de cada tenant. El correo y la contraseña
siguen valiendo para oficina; el PIN es el acceso pensado para obra.

Revision ID: m4h5i6j7k8l9
Revises: l3g4h5i6j7k8
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'm4h5i6j7k8l9'
down_revision = 'l3g4h5i6j7k8'
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
    if _column_exists(bind, 'users', 'pin_hash', schema):
        return

    op.add_column(
        'users',
        sa.Column('pin_hash', sa.String(length=255), nullable=True),
        schema=schema,
    )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'users', schema):
        return
    if not _column_exists(bind, 'users', 'pin_hash', schema):
        return

    op.drop_column('users', 'pin_hash', schema=schema)
