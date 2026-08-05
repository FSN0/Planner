"""users.locale (stub)

Esta revisión existió como migración aparte y algunas BDs quedaron
stampadas en r9s0t1u2v3w4. El contenido real (columna locale) ya está en
p7k8l9m0n1o2; este archivo solo mantiene la cadena de Alembic y es no-op.

Revision ID: r9s0t1u2v3w4
Revises: p7k8l9m0n1o2
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'r9s0t1u2v3w4'
down_revision = 'p7k8l9m0n1o2'
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
    if _column_exists(bind, 'users', 'locale', schema):
        return
    op.add_column(
        'users',
        sa.Column('locale', sa.String(length=8), nullable=True),
        schema=schema,
    )


def downgrade():
    # No borrar locale: la columna “oficial” sigue siendo responsabilidad de p7.
    pass
