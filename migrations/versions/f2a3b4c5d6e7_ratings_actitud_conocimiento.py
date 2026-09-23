"""Valoraciones: actitud y conocimiento 0–5.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def _column_exists(bind, table_name, column_name, schema):
    columnas = {c['name'] for c in inspect(bind).get_columns(table_name, schema=schema)}
    return column_name in columnas


def _column_type(bind, table_name, column_name, schema):
    for col in inspect(bind).get_columns(table_name, schema=schema):
        if col['name'] == column_name:
            return col['type']
    return None


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'ratings', schema):
        return

    if not _column_exists(bind, 'ratings', 'actitud', schema):
        op.add_column(
            'ratings',
            sa.Column('actitud', sa.Integer(), nullable=True),
            schema=schema,
        )
    if not _column_exists(bind, 'ratings', 'conocimiento', schema):
        op.add_column(
            'ratings',
            sa.Column('conocimiento', sa.Integer(), nullable=True),
            schema=schema,
        )

    # score pasa a Float para medias 0–5 (legacy −3…+3 se conserva)
    col_type = _column_type(bind, 'ratings', 'score', schema)
    type_name = type(col_type).__name__.lower() if col_type is not None else ''
    if 'float' not in type_name and 'double' not in type_name and 'numeric' not in type_name:
        op.alter_column(
            'ratings',
            'score',
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
            schema=schema,
            postgresql_using='score::double precision',
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'ratings', schema):
        return

    if _column_exists(bind, 'ratings', 'conocimiento', schema):
        op.drop_column('ratings', 'conocimiento', schema=schema)
    if _column_exists(bind, 'ratings', 'actitud', schema):
        op.drop_column('ratings', 'actitud', schema=schema)

    col_type = _column_type(bind, 'ratings', 'score', schema)
    type_name = type(col_type).__name__.lower() if col_type is not None else ''
    if 'float' in type_name or 'double' in type_name or 'numeric' in type_name:
        op.alter_column(
            'ratings',
            'score',
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
            schema=schema,
            postgresql_using='ROUND(score)::integer',
        )
