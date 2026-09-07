"""Acks de desvío plan→ficha en registros_fichajes.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
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
    if not schema or not _table_exists(bind, 'registros_fichajes', schema):
        return
    cols = [
        ('desvio_ack_plan_at', sa.DateTime(), True),
        ('desvio_ack_plan_by_id', sa.Integer(), True),
        ('desvio_ack_real_at', sa.DateTime(), True),
        ('desvio_ack_real_by_id', sa.Integer(), True),
    ]
    for name, col_type, nullable in cols:
        if not _column_exists(bind, 'registros_fichajes', name, schema):
            op.add_column(
                'registros_fichajes',
                sa.Column(name, col_type, nullable=nullable),
                schema=schema,
            )
    # FKs opcionales (users vive en el mismo schema de tenant)
    if _table_exists(bind, 'users', schema):
        for col in ('desvio_ack_plan_by_id', 'desvio_ack_real_by_id'):
            fk_name = f'fk_registros_fichajes_{col}'
            try:
                op.create_foreign_key(
                    fk_name,
                    'registros_fichajes',
                    'users',
                    [col],
                    ['id'],
                    source_schema=schema,
                    referent_schema=schema,
                )
            except Exception:
                pass


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'registros_fichajes', schema):
        return
    for col in ('desvio_ack_plan_by_id', 'desvio_ack_real_by_id'):
        fk_name = f'fk_registros_fichajes_{col}'
        try:
            op.drop_constraint(fk_name, 'registros_fichajes', schema=schema, type_='foreignkey')
        except Exception:
            pass
    for name in (
        'desvio_ack_real_by_id',
        'desvio_ack_real_at',
        'desvio_ack_plan_by_id',
        'desvio_ack_plan_at',
    ):
        if _column_exists(bind, 'registros_fichajes', name, schema):
            op.drop_column('registros_fichajes', name, schema=schema)
