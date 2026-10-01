"""create ausencias tables in tenant schemas (fix public-only create)

Revision ID: g8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'g8b9c0d1e2f3'
down_revision = 'f7a8b9c0d1e2'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return

    # Solo esquemas de tenant (no public): las ausencias viven por cliente
    if schema == 'public':
        return

    if not _table_exists(bind, 'ausencias_planificadas', schema):
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

    if not _table_exists(bind, 'ausencias_conflictos', schema):
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
    schema = _current_schema(bind)
    if not schema or schema == 'public':
        return
    if _table_exists(bind, 'ausencias_conflictos', schema):
        op.drop_table('ausencias_conflictos', schema=schema)
    if _table_exists(bind, 'ausencias_planificadas', schema):
        op.drop_table('ausencias_planificadas', schema=schema)
