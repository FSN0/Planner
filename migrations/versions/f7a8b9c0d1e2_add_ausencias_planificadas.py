"""add ausencias_planificadas and ausencias_conflictos

Revision ID: f7a8b9c0d1e2
Revises: a8f3c2b1d0e9
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'f7a8b9c0d1e2'
down_revision = 'a8f3c2b1d0e9'
branch_labels = None
depends_on = None


def upgrade():
    """
    Primera versión creó las tablas solo en public (inspect veía public vía search_path
    y saltaba los tenants). Las tablas de ausencias son por-tenant; no crear en public.
    La corrección está en g8b9c0d1e2f3.
    """
    bind = op.get_bind()
    schema = bind.execute(sa.text('SELECT current_schema()')).scalar()
    # No crear nada en public; tenants los cubre la migración siguiente.
    if schema == 'public':
        return
    # Si un tenant aún no tiene tablas (p.ej. migrate a medias), crearlas aquí también.
    tables = set(inspect(bind).get_table_names(schema=schema))

    if 'ausencias_planificadas' not in tables:
        op.create_table(
            'ausencias_planificadas',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=False),
            sa.Column('fecha_inicio', sa.Date(), nullable=False),
            sa.Column('fecha_fin', sa.Date(), nullable=False),
            sa.Column('dias', sa.Float(), nullable=True),
            sa.Column('tipo', sa.String(length=120), nullable=False, server_default='Ausencia'),
            sa.Column('tipo_external_id', sa.String(length=64), nullable=True),
            sa.Column('estado', sa.String(length=20), nullable=False, server_default='aprobada'),
            sa.Column('origen', sa.String(length=20), nullable=False, server_default='manual'),
            sa.Column('external_id', sa.String(length=64), nullable=True),
            sa.Column('descripcion', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('created_by_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=True),
            schema=schema,
        )
        op.create_index(
            'ix_ausencias_user_fechas',
            'ausencias_planificadas',
            ['user_id', 'fecha_inicio', 'fecha_fin'],
            schema=schema,
        )
        op.create_index(
            'ix_ausencias_external',
            'ausencias_planificadas',
            ['origen', 'external_id'],
            schema=schema,
        )

    tables = set(inspect(bind).get_table_names(schema=schema))
    if 'ausencias_conflictos' not in tables:
        op.create_table(
            'ausencias_conflictos',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=False),
            sa.Column('fecha', sa.Date(), nullable=False),
            sa.Column('obra_id', sa.Integer(), sa.ForeignKey(f'{schema}.obras.id'), nullable=False),
            sa.Column(
                'ausencia_id',
                sa.Integer(),
                sa.ForeignKey(f'{schema}.ausencias_planificadas.id'),
                nullable=False,
            ),
            sa.Column(
                'asignacion_id',
                sa.Integer(),
                sa.ForeignKey(f'{schema}.asignaciones.id', ondelete='SET NULL'),
                nullable=True,
            ),
            sa.Column('estado', sa.String(length=30), nullable=False, server_default='pendiente'),
            sa.Column('resolved_by_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                'user_id', 'fecha', 'obra_id', 'ausencia_id',
                name='uq_ausencia_conflicto_dia',
            ),
            schema=schema,
        )
        op.create_index(
            'ix_ausencias_conflictos_estado',
            'ausencias_conflictos',
            ['estado'],
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = bind.execute(sa.text('SELECT current_schema()')).scalar()
    if not schema or schema == 'public':
        return
    tables = set(inspect(bind).get_table_names(schema=schema))
    if 'ausencias_conflictos' in tables:
        op.drop_table('ausencias_conflictos', schema=schema)
    if 'ausencias_planificadas' in tables:
        op.drop_table('ausencias_planificadas', schema=schema)
