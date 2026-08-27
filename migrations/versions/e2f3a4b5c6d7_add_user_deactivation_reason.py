"""Store reason when a user is inactive (pending / baja / deleted)

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
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
    if not schema or not _table_exists(bind, 'users', schema):
        return
    if not _column_exists(bind, 'users', 'deactivation_reason', schema):
        op.add_column(
            'users',
            sa.Column('deactivation_reason', sa.String(length=40), nullable=True),
            schema=schema,
        )
    if not _column_exists(bind, 'users', 'deactivated_at', schema):
        op.add_column(
            'users',
            sa.Column('deactivated_at', sa.DateTime(), nullable=True),
            schema=schema,
        )
    # Heurística para datos existentes sin motivo:
    # - eliminados → deleted
    # - con vínculo Odoo → odoo (no son altas pendientes)
    # - resto → pending
    if _column_exists(bind, 'users', 'deactivation_reason', schema):
        bind.execute(text(
            f"""
            UPDATE "{schema}".users
            SET deactivation_reason = CASE
                WHEN COALESCE(is_deleted, false) THEN 'deleted'
                WHEN external_ids ? 'odoo'
                     AND NULLIF(TRIM(external_ids->>'odoo'), '') IS NOT NULL
                  THEN 'odoo'
                ELSE 'pending'
            END,
            deactivated_at = CASE
                WHEN COALESCE(is_deleted, false)
                  OR (
                    external_ids ? 'odoo'
                    AND NULLIF(TRIM(external_ids->>'odoo'), '') IS NOT NULL
                  )
                THEN COALESCE(deactivated_at, NOW())
                ELSE deactivated_at
            END
            WHERE COALESCE(active, false) = false
              AND (deactivation_reason IS NULL OR deactivation_reason = '')
            """
        ))


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    if _column_exists(bind, 'users', 'deactivated_at', schema):
        op.drop_column('users', 'deactivated_at', schema=schema)
    if _column_exists(bind, 'users', 'deactivation_reason', schema):
        op.drop_column('users', 'deactivation_reason', schema=schema)
