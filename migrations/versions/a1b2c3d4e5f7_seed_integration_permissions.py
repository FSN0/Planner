"""Seed integration permission modules; collapse X into W; jefe defaults

- Añade sync_odoo, soltec_alta_odoo, soltec_portal si faltan
- can_execute → can_write (X unificado con Escritura)
- Jefe: quita integraciones R legado; da Alta/Portal R

Revision ID: a1b2c3d4e5f7
Revises: f3a4b5c6d7e8
Create Date: 2026-08-27
"""
from alembic import op
from sqlalchemy import inspect, text


revision = 'a1b2c3d4e5f7'
down_revision = 'f3a4b5c6d7e8'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or schema == 'public':
        return
    if not _table_exists(bind, 'role_permissions', schema):
        return

    # Unificar X → Escritura
    bind.execute(text(
        f"""
        UPDATE "{schema}".role_permissions
        SET can_write = TRUE
        WHERE can_execute = TRUE AND can_write = FALSE
        """
    ))
    bind.execute(text(
        f"""
        UPDATE "{schema}".role_permissions
        SET can_execute = can_write
        """
    ))

    roles = ('admin', 'jefe_obra', 'laboral', 'rrhh', 'operario')
    new_modules = {
        'sync_odoo': {'admin': ('r', 'w'), 'jefe_obra': (), 'laboral': (), 'rrhh': (), 'operario': ()},
        'soltec_alta_odoo': {
            'admin': ('r', 'w'),
            'jefe_obra': ('r',),
            'laboral': (),
            'rrhh': (),
            'operario': (),
        },
        'soltec_portal': {
            'admin': ('r', 'w'),
            'jefe_obra': ('r',),
            'laboral': (),
            'rrhh': (),
            'operario': (),
        },
    }

    for module, per_role in new_modules.items():
        for role in roles:
            exists = bind.execute(text(
                f"""
                SELECT 1 FROM "{schema}".role_permissions
                WHERE role = :role AND module = :module
                LIMIT 1
                """
            ), {'role': role, 'module': module}).scalar()
            if exists:
                continue
            flags = per_role.get(role) or ()
            can_r = 'r' in flags or 'w' in flags
            can_w = 'w' in flags
            bind.execute(text(
                f"""
                INSERT INTO "{schema}".role_permissions
                    (role, module, can_read, can_write, can_execute)
                VALUES (:role, :module, :r, :w, :w)
                """
            ), {'role': role, 'module': module, 'r': can_r, 'w': can_w})

    # Admin: asegurar sync_odoo + hub RW
    for module in ('integraciones', 'sync_odoo', 'soltec_alta_odoo', 'soltec_portal'):
        bind.execute(text(
            f"""
            UPDATE "{schema}".role_permissions
            SET can_read = TRUE, can_write = TRUE, can_execute = TRUE
            WHERE role = 'admin' AND module = :module
            """
        ), {'module': module})

    # Jefe: ya no necesita hub Integraciones por el alta; atajos SSO sí
    bind.execute(text(
        f"""
        UPDATE "{schema}".role_permissions
        SET can_read = FALSE, can_write = FALSE, can_execute = FALSE
        WHERE role = 'jefe_obra' AND module = 'integraciones'
        """
    ))
    for module in ('soltec_alta_odoo', 'soltec_portal'):
        bind.execute(text(
            f"""
            UPDATE "{schema}".role_permissions
            SET can_read = TRUE, can_write = FALSE, can_execute = FALSE
            WHERE role = 'jefe_obra' AND module = :module
            """
        ), {'module': module})


def downgrade():
    pass
