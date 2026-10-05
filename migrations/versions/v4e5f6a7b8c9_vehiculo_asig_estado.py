"""AsignacionVehiculo: estado efectiva/no_usada + notas; unicidad parcial.

Revision ID: v4e5f6a7b8c9
Revises: a9b0c1d2e3f4
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'v4e5f6a7b8c9'
down_revision = 'a9b0c1d2e3f4'
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


def _index_exists(bind, schema, index_name):
    row = bind.execute(text(
        "SELECT 1 FROM pg_indexes WHERE schemaname = :s AND indexname = :i"
    ), {'s': schema, 'i': index_name}).scalar()
    return bool(row)


def _constraint_exists(bind, schema, table_name, constraint_name):
    row = bind.execute(text(
        """
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = :s AND table_name = :t AND constraint_name = :c
        """
    ), {'s': schema, 't': table_name, 'c': constraint_name}).scalar()
    return bool(row)


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'asignaciones_vehiculo', schema):
        return

    if not _column_exists(bind, 'asignaciones_vehiculo', 'estado', schema):
        op.add_column(
            'asignaciones_vehiculo',
            sa.Column('estado', sa.String(length=20), nullable=False, server_default='efectiva'),
            schema=schema,
        )
    if not _column_exists(bind, 'asignaciones_vehiculo', 'notas', schema):
        op.add_column(
            'asignaciones_vehiculo',
            sa.Column('notas', sa.Text(), nullable=True),
            schema=schema,
        )

    for cname in ('uq_vehiculo_fecha', 'uq_user_vehiculo_fecha'):
        if _constraint_exists(bind, schema, 'asignaciones_vehiculo', cname):
            op.drop_constraint(cname, 'asignaciones_vehiculo', schema=schema, type_='unique')

    if not _index_exists(bind, schema, 'uq_vehiculo_fecha_efectiva'):
        bind.execute(text(
            f'CREATE UNIQUE INDEX uq_vehiculo_fecha_efectiva '
            f'ON {schema}.asignaciones_vehiculo (vehiculo_id, fecha) '
            f"WHERE estado = 'efectiva'"
        ))
    if not _index_exists(bind, schema, 'uq_user_vehiculo_fecha_efectiva'):
        bind.execute(text(
            f'CREATE UNIQUE INDEX uq_user_vehiculo_fecha_efectiva '
            f'ON {schema}.asignaciones_vehiculo (user_id, fecha) '
            f"WHERE estado = 'efectiva'"
        ))


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'asignaciones_vehiculo', schema):
        return

    bind.execute(text(
        f"DELETE FROM {schema}.asignaciones_vehiculo WHERE estado = 'no_usada'"
    ))

    for iname in ('uq_vehiculo_fecha_efectiva', 'uq_user_vehiculo_fecha_efectiva'):
        if _index_exists(bind, schema, iname):
            bind.execute(text(f'DROP INDEX IF EXISTS {schema}.{iname}'))

    if not _constraint_exists(bind, schema, 'asignaciones_vehiculo', 'uq_vehiculo_fecha'):
        op.create_unique_constraint(
            'uq_vehiculo_fecha', 'asignaciones_vehiculo',
            ['vehiculo_id', 'fecha'], schema=schema,
        )
    if not _constraint_exists(bind, schema, 'asignaciones_vehiculo', 'uq_user_vehiculo_fecha'):
        op.create_unique_constraint(
            'uq_user_vehiculo_fecha', 'asignaciones_vehiculo',
            ['user_id', 'fecha'], schema=schema,
        )

    if _column_exists(bind, 'asignaciones_vehiculo', 'notas', schema):
        op.drop_column('asignaciones_vehiculo', 'notas', schema=schema)
    if _column_exists(bind, 'asignaciones_vehiculo', 'estado', schema):
        op.drop_column('asignaciones_vehiculo', 'estado', schema=schema)
