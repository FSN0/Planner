"""Motivo de inactividad en vehículos (manual / odoo).

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'e1f2a3b4c5d6'
down_revision = 'd0e1f2a3b4c5'
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


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'vehiculos', schema):
        return

    if not _column_exists(bind, 'vehiculos', 'deactivation_reason', schema):
        op.add_column(
            'vehiculos',
            sa.Column('deactivation_reason', sa.String(length=40), nullable=True),
            schema=schema,
        )
    if not _column_exists(bind, 'vehiculos', 'deactivated_at', schema):
        op.add_column(
            'vehiculos',
            sa.Column('deactivated_at', sa.DateTime(), nullable=True),
            schema=schema,
        )
    if not _column_exists(bind, 'vehiculos', 'deactivated_by_id', schema):
        op.add_column(
            'vehiculos',
            sa.Column('deactivated_by_id', sa.Integer(), nullable=True),
            schema=schema,
        )
        try:
            op.create_foreign_key(
                'fk_vehiculos_deactivated_by',
                'vehiculos',
                'users',
                ['deactivated_by_id'],
                ['id'],
                source_schema=schema,
                referent_schema=schema,
                ondelete='SET NULL',
            )
        except Exception:
            pass

    # Heurística: inactivos con vínculo Odoo → motivo odoo
    bind.execute(text(f"""
        UPDATE {schema}.vehiculos
        SET deactivation_reason = 'odoo'
        WHERE active IS FALSE
          AND (deactivation_reason IS NULL OR deactivation_reason = '')
          AND COALESCE(external_ids->>'odoo', '') <> ''
    """))


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'vehiculos', schema):
        return
    for col in ('deactivated_by_id', 'deactivated_at', 'deactivation_reason'):
        if _column_exists(bind, 'vehiculos', col, schema):
            if col == 'deactivated_by_id':
                try:
                    op.drop_constraint(
                        'fk_vehiculos_deactivated_by',
                        'vehiculos',
                        schema=schema,
                        type_='foreignkey',
                    )
                except Exception:
                    pass
            op.drop_column('vehiculos', col, schema=schema)
