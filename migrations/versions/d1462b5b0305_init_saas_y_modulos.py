"""Init SaaS y Modulos

Revision ID: d1462b5b0305
Revises: 
Create Date: 2026-06-03 12:08:19.446270

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'd1462b5b0305'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # === TABLA TENANTS (esquema public, gestion multi-tenant) ===
    op.create_table('tenants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=100), nullable=False),
        sa.Column('subdominio', sa.String(length=50), nullable=False),
        sa.Column('schema_name', sa.String(length=50), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('modulos_activos', sa.JSON(), nullable=False, server_default='{}'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('subdominio'),
        sa.UniqueConstraint('schema_name'),
        schema='public'
    )

    # === TABLA COMPANIES ===
    op.create_table('companies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=True),
        sa.Column('nombre', sa.String(length=100), nullable=False),
        sa.Column('nif', sa.String(length=20), nullable=True),
        sa.Column('external_ids', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('gremio', sa.String(length=100), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('color', sa.String(length=7), nullable=True),
        sa.Column('is_internal', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )

    # === TABLA USERS ===
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('external_ids', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('password_hash', sa.String(length=128), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('lastname', sa.String(length=100), nullable=False),
        sa.Column('dni', sa.String(length=20), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=True),
        sa.Column('categoria_profesional', sa.String(length=100), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('is_deleted', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('receive_emails', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('especialidad', sa.String(length=100), nullable=True),
        sa.Column('scheduled_activation_date', sa.Date(), nullable=True),
        sa.Column('scheduled_deactivation_date', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('dni')
    )

    # === TABLA OBRAS ===
    op.create_table('obras',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('codigo', sa.String(length=20), nullable=True),
        sa.Column('nombre', sa.String(length=100), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('cliente', sa.String(length=100), nullable=True),
        sa.Column('ubicacion', sa.String(length=100), nullable=True),
        sa.Column('fecha_sincronizacion', sa.DateTime(), nullable=True),
        sa.Column('external_ids', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('fecha_inicio', sa.Date(), nullable=True),
        sa.Column('fecha_fin', sa.Date(), nullable=True),
        sa.Column('fecha_importacion', sa.DateTime(), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=True, server_default='PLANIFICADA'),
        sa.Column('limite_trabajadores', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('url_prl', sa.String(length=255), nullable=True),
        sa.Column('jefe_obra_id', sa.Integer(), nullable=True),
        sa.Column('encargado_id', sa.Integer(), nullable=True),
        sa.Column('color', sa.String(length=7), nullable=False, server_default='#a8d5ba'),
        sa.Column('is_deleted', sa.Boolean(), nullable=True, server_default='false'),
        sa.ForeignKeyConstraint(['jefe_obra_id'], ['users.id']),
        sa.ForeignKeyConstraint(['encargado_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('codigo')
    )

    # === TABLA SOLICITUDES ===
    op.create_table('solicitudes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('accion', sa.String(length=20), nullable=False, server_default='ASIGNAR'),
        sa.Column('obra_id', sa.Integer(), nullable=False),
        sa.Column('requested_by_id', sa.Integer(), nullable=False),
        sa.Column('empleado_id', sa.Integer(), nullable=True),
        sa.Column('fecha_inicio', sa.Date(), nullable=False),
        sa.Column('fecha_fin', sa.Date(), nullable=False),
        sa.Column('perfil_categoria', sa.String(length=50), nullable=True),
        sa.Column('perfil_empresa_id', sa.Integer(), nullable=True),
        sa.Column('cantidad_solicitada', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('cantidad_cubierta', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('estado', sa.String(length=20), nullable=False, server_default='PENDIENTE'),
        sa.Column('auto_fulfilled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('comentarios', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_by_id', sa.Integer(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id']),
        sa.ForeignKeyConstraint(['requested_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['empleado_id'], ['users.id']),
        sa.ForeignKeyConstraint(['perfil_empresa_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # === TABLA ASIGNACIONES ===
    op.create_table('asignaciones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('obra_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('solicitud_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['solicitud_id'], ['solicitudes.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('obra_id', 'user_id', 'fecha', name='uq_obra_user_fecha')
    )

    # === TABLA HISTORIAL ASIGNACIONES ===
    op.create_table('historial_asignaciones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asignacion_id', sa.Integer(), nullable=True),
        sa.Column('accion', sa.String(length=100), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('realizado_por', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['asignacion_id'], ['asignaciones.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['realizado_por'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # === TABLA SYNC LOGS ===
    op.create_table('sync_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.DateTime(), nullable=True),
        sa.Column('tipo', sa.String(length=50), nullable=True),
        sa.Column('modo', sa.String(length=50), nullable=True),
        sa.Column('nuevos', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('actualizados', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('finalizados', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('errores', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('detalles', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # === TABLA REGISTROS FICHAJES ===
    op.create_table('registros_fichajes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('fecha', sa.Date(), nullable=True),
        sa.Column('check_in', sa.DateTime(), nullable=True),
        sa.Column('check_out', sa.DateTime(), nullable=True),
        sa.Column('obra_planificada_id', sa.Integer(), nullable=True),
        sa.Column('obra_real_id', sa.Integer(), nullable=True),
        sa.Column('estado', sa.String(length=50), nullable=True, server_default='Pendiente'),
        sa.Column('notas_resolucion', sa.Text(), nullable=True),
        sa.Column('fecha_auditoria', sa.DateTime(), nullable=True),
        sa.Column('resuelto_por_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['obra_planificada_id'], ['obras.id']),
        sa.ForeignKeyConstraint(['obra_real_id'], ['obras.id']),
        sa.ForeignKeyConstraint(['resuelto_por_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # === TABLA RATINGS ===
    op.create_table('ratings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # === TABLA FESTIVOS ===
    op.create_table('festivos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('descripcion', sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fecha')
    )

    # === TABLA CONFIGURACION GLOBAL ===
    op.create_table('configuracion_global',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clave', sa.String(length=50), nullable=False),
        sa.Column('valor', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clave')
    )

    # === TABLA USER OBRA CONFIG ===
    op.create_table('user_obra_config',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('obra_id', sa.Integer(), nullable=False),
        sa.Column('is_pinned', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('position', sa.Integer(), nullable=True, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id']),
        sa.PrimaryKeyConstraint('user_id', 'obra_id')
    )

    # === TABLA SYSTEM LOGS ===
    op.create_table('system_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=150), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # === TABLA LOG PREFERENCES ===
    op.create_table('log_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('last_read_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # === TABLA NOTAS ===
    op.create_table('notas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('titulo', sa.String(length=200), nullable=False),
        sa.Column('contenido', sa.Text(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('es_privada', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('autor_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['autor_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # === TABLA NOTA_OBRA (M2M) ===
    op.create_table('nota_obra',
        sa.Column('nota_id', sa.Integer(), nullable=False),
        sa.Column('obra_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['nota_id'], ['notas.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('nota_id', 'obra_id')
    )

    # === TABLA NOTA_USER (M2M) ===
    op.create_table('nota_user',
        sa.Column('nota_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['nota_id'], ['notas.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('nota_id', 'user_id')
    )


def downgrade():
    op.drop_table('nota_user')
    op.drop_table('nota_obra')
    op.drop_table('notas')
    op.drop_table('log_preferences')
    op.drop_table('system_logs')
    op.drop_table('user_obra_config')
    op.drop_table('configuracion_global')
    op.drop_table('festivos')
    op.drop_table('ratings')
    op.drop_table('registros_fichajes')
    op.drop_table('sync_logs')
    op.drop_table('historial_asignaciones')
    op.drop_table('asignaciones')
    op.drop_table('solicitudes')
    op.drop_table('obras')
    op.drop_table('users')
    op.drop_table('companies')
    op.execute('DROP TABLE IF EXISTS public.tenants')
