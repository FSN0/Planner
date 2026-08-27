"""Fix mis-labelled Odoo bajas marked as pending activation

La migración e2f3a4b5c6d7 etiquetó a todos los inactivos sin motivo como
«pending». Quienes tienen vínculo Odoo y están inactivos casi siempre son
baja ERP, no alta pendiente.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-08-27
"""
from alembic import op
from sqlalchemy import inspect, text


revision = 'f3a4b5c6d7e8'
down_revision = 'e2f3a4b5c6d7'
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
    if not schema or schema == 'public':
        return
    if not _column_exists(bind, 'users', 'deactivation_reason', schema):
        return

    # Inactivo + vínculo Odoo + motivo pending/vacío → baja Odoo
    bind.execute(text(
        f"""
        UPDATE "{schema}".users
        SET deactivation_reason = 'odoo',
            deactivated_at = COALESCE(deactivated_at, NOW())
        WHERE COALESCE(active, false) = false
          AND COALESCE(is_deleted, false) = false
          AND (
            deactivation_reason IS NULL
            OR deactivation_reason = ''
            OR deactivation_reason = 'pending'
          )
          AND external_ids ? 'odoo'
          AND NULLIF(TRIM(external_ids->>'odoo'), '') IS NOT NULL
        """
    ))

    # También: solicitudes de baja automática Odoo ya cumplidas
    if _table_exists(bind, 'solicitudes', schema):
        bind.execute(text(
            f"""
            UPDATE "{schema}".users u
            SET deactivation_reason = 'odoo',
                deactivated_at = COALESCE(u.deactivated_at, s.resolved_at, NOW())
            FROM "{schema}".solicitudes s
            WHERE u.id = s.empleado_id
              AND COALESCE(u.active, false) = false
              AND COALESCE(u.is_deleted, false) = false
              AND (u.deactivation_reason IS NULL OR u.deactivation_reason IN ('', 'pending'))
              AND s.accion = 'DESASIGNAR'
              AND s.estado = 'CUMPLIDA'
              AND s.notas ILIKE '%sincronización Odoo%'
            """
        ))


def downgrade():
    # No revertimos la corrección de datos.
    pass
