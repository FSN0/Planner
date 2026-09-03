"""add nota_audio_jobs table for voice notes

Revision ID: d3e4f5a6b7c8
Revises: h1i2j3k4l5m6
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'd3e4f5a6b7c8'
down_revision = 'h1i2j3k4l5m6'
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
    if not _table_exists(bind, 'users', schema):
        return
    if _table_exists(bind, 'nota_audio_jobs', schema):
        return

    op.create_table(
        'nota_audio_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('autor_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=False),
        sa.Column('estado', sa.String(20), nullable=False, server_default='pendiente'),
        sa.Column('archivo_path', sa.String(500), nullable=True),
        sa.Column('archivo_nombre', sa.String(255), nullable=True),
        sa.Column('duracion_segundos', sa.Float(), nullable=True),
        sa.Column('nota_id', sa.Integer(), sa.ForeignKey(f'{schema}.notas.id'), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('meta_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        schema=schema,
    )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    if _table_exists(bind, 'nota_audio_jobs', schema):
        op.drop_table('nota_audio_jobs', schema=schema)
