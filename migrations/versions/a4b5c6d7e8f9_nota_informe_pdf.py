"""notas: columnas para PDF de informe adjunto

Revision ID: a4b5c6d7e8f9
Revises: z3a4b5c6d7e8
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'a4b5c6d7e8f9'
down_revision = 'z3a4b5c6d7e8'
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
    if not schema or not _table_exists(bind, 'notas', schema):
        return

    if not _column_exists(bind, 'notas', 'informe_pdf_path', schema):
        op.add_column(
            'notas',
            sa.Column('informe_pdf_path', sa.String(500), nullable=True),
            schema=schema,
        )
    if not _column_exists(bind, 'notas', 'informe_pdf_nombre', schema):
        op.add_column(
            'notas',
            sa.Column('informe_pdf_nombre', sa.String(255), nullable=True),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'notas', schema):
        return

    if _column_exists(bind, 'notas', 'informe_pdf_nombre', schema):
        op.drop_column('notas', 'informe_pdf_nombre', schema=schema)
    if _column_exists(bind, 'notas', 'informe_pdf_path', schema):
        op.drop_column('notas', 'informe_pdf_path', schema=schema)
