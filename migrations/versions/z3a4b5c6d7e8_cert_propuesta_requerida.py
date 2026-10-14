"""Certificación: requerir acción a la subcontrata (obra+mes).

Revision ID: z3a4b5c6d7e8
Revises: y2z3a4b5c6d7
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'z3a4b5c6d7e8'
down_revision = 'y2z3a4b5c6d7'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def _column_exists(bind, table_name, column_name, schema):
    columnas = {c['name'] for c in inspect(bind).get_columns(table_name, schema=schema)}
    return column_name in columnas


def _fk_exists(bind, table_name, fk_name, schema):
    for fk in inspect(bind).get_foreign_keys(table_name, schema=schema):
        if fk.get('name') == fk_name:
            return True
    return False


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'certificacion_propuestas', schema):
        return

    if not _column_exists(bind, 'certificacion_propuestas', 'requerida_at', schema):
        op.add_column(
            'certificacion_propuestas',
            sa.Column('requerida_at', sa.DateTime(), nullable=True),
            schema=schema,
        )
    if not _column_exists(bind, 'certificacion_propuestas', 'requerida_por_id', schema):
        op.add_column(
            'certificacion_propuestas',
            sa.Column('requerida_por_id', sa.Integer(), nullable=True),
            schema=schema,
        )

    fk_name = 'fk_cert_propuesta_requerida_por_users'
    if (
        _column_exists(bind, 'certificacion_propuestas', 'requerida_por_id', schema)
        and not _fk_exists(bind, 'certificacion_propuestas', fk_name, schema)
    ):
        op.create_foreign_key(
            fk_name,
            'certificacion_propuestas',
            'users',
            ['requerida_por_id'],
            ['id'],
            source_schema=schema,
            referent_schema=schema,
            ondelete='SET NULL',
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'certificacion_propuestas', schema):
        return
    fk_name = 'fk_cert_propuesta_requerida_por_users'
    if _fk_exists(bind, 'certificacion_propuestas', fk_name, schema):
        op.drop_constraint(fk_name, 'certificacion_propuestas', schema=schema, type_='foreignkey')
    if _column_exists(bind, 'certificacion_propuestas', 'requerida_por_id', schema):
        op.drop_column('certificacion_propuestas', 'requerida_por_id', schema=schema)
    if _column_exists(bind, 'certificacion_propuestas', 'requerida_at', schema):
        op.drop_column('certificacion_propuestas', 'requerida_at', schema=schema)
