"""obras geolocalizadas + validación geo en fichajes_eventos

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6b7
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'c1d2e3f4a5b6'
down_revision = 'b2c3d4e5f6b7'
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
    if not schema or not _table_exists(bind, 'obras', schema):
        return

    if not _column_exists(bind, 'obras', 'latitud', schema):
        op.add_column('obras', sa.Column('latitud', sa.Float(), nullable=True))
    if not _column_exists(bind, 'obras', 'longitud', schema):
        op.add_column('obras', sa.Column('longitud', sa.Float(), nullable=True))
    if not _column_exists(bind, 'obras', 'radio_metros', schema):
        op.add_column('obras', sa.Column('radio_metros', sa.Integer(), nullable=True))

    if _table_exists(bind, 'fichajes_eventos', schema):
        if not _column_exists(bind, 'fichajes_eventos', 'geo_estado', schema):
            op.add_column(
                'fichajes_eventos',
                sa.Column('geo_estado', sa.String(length=20), nullable=True),
            )
        if not _column_exists(bind, 'fichajes_eventos', 'distancia_obra_metros', schema):
            op.add_column(
                'fichajes_eventos',
                sa.Column('distancia_obra_metros', sa.Float(), nullable=True),
            )
        if not _column_exists(bind, 'fichajes_eventos', 'nota_ubicacion', schema):
            op.add_column(
                'fichajes_eventos',
                sa.Column('nota_ubicacion', sa.Text(), nullable=True),
            )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return

    if _table_exists(bind, 'fichajes_eventos', schema):
        for col in ('nota_ubicacion', 'distancia_obra_metros', 'geo_estado'):
            if _column_exists(bind, 'fichajes_eventos', col, schema):
                op.drop_column('fichajes_eventos', col)

    if _table_exists(bind, 'obras', schema):
        for col in ('radio_metros', 'longitud', 'latitud'):
            if _column_exists(bind, 'obras', col, schema):
                op.drop_column('obras', col)
