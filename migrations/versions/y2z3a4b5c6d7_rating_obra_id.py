"""Valoraciones: obra_id opcional (contexto en historial).

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'y2z3a4b5c6d7'
down_revision = 'x1y2z3a4b5c6'
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


def _index_exists(bind, table_name, index_name, schema):
    for ix in inspect(bind).get_indexes(table_name, schema=schema):
        if ix.get('name') == index_name:
            return True
    return False


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'ratings', schema):
        return
    if not _table_exists(bind, 'obras', schema):
        return

    if not _column_exists(bind, 'ratings', 'obra_id', schema):
        op.add_column(
            'ratings',
            sa.Column('obra_id', sa.Integer(), nullable=True),
            schema=schema,
        )

    fk_name = 'fk_ratings_obra_id_obras'
    if not _fk_exists(bind, 'ratings', fk_name, schema):
        op.create_foreign_key(
            fk_name,
            'ratings',
            'obras',
            ['obra_id'],
            ['id'],
            source_schema=schema,
            referent_schema=schema,
            ondelete='SET NULL',
        )

    ix_name = 'ix_ratings_obra_id'
    if not _index_exists(bind, 'ratings', ix_name, schema):
        op.create_index(ix_name, 'ratings', ['obra_id'], unique=False, schema=schema)


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'ratings', schema):
        return

    ix_name = 'ix_ratings_obra_id'
    if _index_exists(bind, 'ratings', ix_name, schema):
        op.drop_index(ix_name, table_name='ratings', schema=schema)

    fk_name = 'fk_ratings_obra_id_obras'
    if _fk_exists(bind, 'ratings', fk_name, schema):
        op.drop_constraint(fk_name, 'ratings', type_='foreignkey', schema=schema)

    if _column_exists(bind, 'ratings', 'obra_id', schema):
        op.drop_column('ratings', 'obra_id', schema=schema)
