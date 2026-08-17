"""Atribuir al auditor los logs de cuadrante creados al aceptar un fichaje

«Añadir» en auditoría grababa la asignación como Actualización de Cuadrante
(Auto) sin user_id. El autor está en la resolución de fichaje hermana.

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-08-17
"""
from alembic import op
from sqlalchemy import inspect, text


revision = 'b1c2d3e4f5a6'
down_revision = 'a0b1c2d3e4f5'
branch_labels = None
depends_on = None

_ACTION_LEGACY = 'Actualización de Cuadrante (Auto)'
_ACTION_ANADIR = 'Resolución de Fichaje: Añadir'


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or schema == 'public':
        return
    if not _table_exists(bind, 'system_logs', schema):
        return

    bind.execute(text("""
        WITH matched AS (
            SELECT DISTINCT ON (auto.id)
                auto.id AS auto_id,
                res.user_id AS autor_id
            FROM system_logs auto
            JOIN system_logs res
              ON res.category = 'fichajes'
             AND res.action = :action_anadir
             AND res.target_user_id IS NOT DISTINCT FROM auto.target_user_id
             AND res.target_date IS NOT DISTINCT FROM auto.target_date
             AND res.user_id IS NOT NULL
             AND abs(extract(epoch FROM (auto.timestamp - res.timestamp))) <= 30
            WHERE auto.action = :action_legacy
              AND auto.user_id IS NULL
              AND auto.category = 'planificacion'
            ORDER BY auto.id,
                     abs(extract(epoch FROM (auto.timestamp - res.timestamp)))
        )
        UPDATE system_logs sl
        SET user_id = matched.autor_id,
            action = :action_anadir
        FROM matched
        WHERE sl.id = matched.auto_id
    """), {'action_legacy': _ACTION_LEGACY, 'action_anadir': _ACTION_ANADIR})

    if not _table_exists(bind, 'registros_fichajes', schema):
        return

    bind.execute(text("""
        WITH matched AS (
            SELECT DISTINCT ON (sl.id)
                sl.id AS log_id,
                rf.resuelto_por_id AS autor_id
            FROM system_logs sl
            JOIN registros_fichajes rf
              ON rf.user_id = sl.target_user_id
             AND rf.fecha = sl.target_date
             AND rf.resuelto_por_id IS NOT NULL
             AND rf.estado IN ('Resuelto_Asignado', 'Resuelto_Dividido')
            WHERE sl.action = :action_legacy
              AND sl.user_id IS NULL
              AND sl.category = 'planificacion'
            ORDER BY sl.id, rf.fecha_auditoria DESC NULLS LAST, rf.id DESC
        )
        UPDATE system_logs sl
        SET user_id = matched.autor_id,
            action = :action_anadir
        FROM matched
        WHERE sl.id = matched.log_id
    """), {'action_legacy': _ACTION_LEGACY, 'action_anadir': _ACTION_ANADIR})


def downgrade():
    # No se deshace: los logs nuevos de Añadir usan la misma acción y
    # categoría; revertir los mezclaría con asignaciones ya correctas.
    pass
