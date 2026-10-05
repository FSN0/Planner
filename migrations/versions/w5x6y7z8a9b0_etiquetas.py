"""Etiquetas: catálogo empleado/subcontrata + M2M.

Revision ID: w5x6y7z8a9b0
Revises: v4e5f6a7b8c9
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'w5x6y7z8a9b0'
down_revision = 'v4e5f6a7b8c9'
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
    if not _table_exists(bind, 'users', schema):
        return

    if not _table_exists(bind, 'etiquetas', schema):
        op.create_table(
            'etiquetas',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('nombre', sa.String(length=80), nullable=False),
            sa.Column('color', sa.String(length=7), nullable=True),
            sa.Column('tipo', sa.String(length=20), nullable=False),
            sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            schema=schema,
        )
        op.create_index(
            'ix_etiquetas_tipo_nombre',
            'etiquetas',
            ['tipo', 'nombre'],
            unique=False,
            schema=schema,
        )

    if not _table_exists(bind, 'etiqueta_user', schema):
        op.create_table(
            'etiqueta_user',
            sa.Column('etiqueta_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['etiqueta_id'], [f'{schema}.etiquetas.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], [f'{schema}.users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('etiqueta_id', 'user_id'),
            schema=schema,
        )

    if not _table_exists(bind, 'etiqueta_company', schema):
        op.create_table(
            'etiqueta_company',
            sa.Column('etiqueta_id', sa.Integer(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['etiqueta_id'], [f'{schema}.etiquetas.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['company_id'], [f'{schema}.companies.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('etiqueta_id', 'company_id'),
            schema=schema,
        )

    if not _table_exists(bind, 'solicitud_etiqueta', schema):
        op.create_table(
            'solicitud_etiqueta',
            sa.Column('solicitud_id', sa.Integer(), nullable=False),
            sa.Column('etiqueta_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['solicitud_id'], [f'{schema}.solicitudes.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['etiqueta_id'], [f'{schema}.etiquetas.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('solicitud_id', 'etiqueta_id'),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or schema == 'public':
        return
    for table in ('solicitud_etiqueta', 'etiqueta_company', 'etiqueta_user', 'etiquetas'):
        if _table_exists(bind, table, schema):
            op.drop_table(table, schema=schema)
