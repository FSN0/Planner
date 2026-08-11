"""configuracion_global.valor: String(255) → Text

La Academia guarda JSON de progreso por capítulo; 255 chars no bastan.

Revision ID: a0b1c2d3e4f5
Revises: z7g8h9i0j1k2
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'a0b1c2d3e4f5'
down_revision = 'z7g8h9i0j1k2'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def _column_type_name(bind, table_name, column_name, schema):
    for col in inspect(bind).get_columns(table_name, schema=schema):
        if col['name'] == column_name:
            t = col.get('type')
            return (str(t) if t is not None else '').lower()
    return ''


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'configuracion_global', schema):
        return
    type_name = _column_type_name(bind, 'configuracion_global', 'valor', schema)
    if type_name and 'text' not in type_name:
        op.alter_column(
            'configuracion_global',
            'valor',
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=False,
            schema=schema,
        )


def downgrade():
    # No reducir a VARCHAR(255): truncaría datos ya guardados.
    pass
