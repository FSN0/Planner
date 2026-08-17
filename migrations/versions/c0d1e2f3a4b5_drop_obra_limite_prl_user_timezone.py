"""Drop obras.limite_trabajadores, obras.url_prl and users.timezone

El cupo por obra, la URL de PRL y la zona horaria por usuario ya no existen
en el producto: un huso por tenant, sin tope de plantilla en la obra.

Revision ID: c0d1e2f3a4b5
Revises: b0c1d2e3f4a5
Create Date: 2026-08-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'c0d1e2f3a4b5'
down_revision = 'b0c1d2e3f4a5'
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


def _drop_if_exists(table_name, column_name, schema):
    bind = op.get_bind()
    if _column_exists(bind, table_name, column_name, schema):
        op.drop_column(table_name, column_name, schema=schema)


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    _drop_if_exists('obras', 'limite_trabajadores', schema)
    _drop_if_exists('obras', 'url_prl', schema)
    _drop_if_exists('users', 'timezone', schema)


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    if _table_exists(bind, 'obras', schema):
        if not _column_exists(bind, 'obras', 'limite_trabajadores', schema):
            op.add_column(
                'obras',
                sa.Column(
                    'limite_trabajadores',
                    sa.Integer(),
                    nullable=False,
                    server_default='0',
                ),
                schema=schema,
            )
        if not _column_exists(bind, 'obras', 'url_prl', schema):
            op.add_column(
                'obras',
                sa.Column('url_prl', sa.String(length=255), nullable=True),
                schema=schema,
            )
    if _table_exists(bind, 'users', schema) and not _column_exists(bind, 'users', 'timezone', schema):
        op.add_column(
            'users',
            sa.Column('timezone', sa.String(length=64), nullable=True),
            schema=schema,
        )
