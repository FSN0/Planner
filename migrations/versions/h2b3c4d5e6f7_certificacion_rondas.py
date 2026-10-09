"""CertificacionRonda: historial de envíos (mesa / baraja).

Revision ID: h2b3c4d5e6f7
Revises: g1a2b3c4d5e6
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'h2b3c4d5e6f7'
down_revision = 'g1a2b3c4d5e6'
branch_labels = None
depends_on = None


def _schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _tables(bind, schema):
    return set(inspect(bind).get_table_names(schema=schema))


def upgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    if 'certificacion_rondas' in _tables(bind, schema):
        return
    op.create_table(
        'certificacion_rondas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('obra_id', sa.Integer(), sa.ForeignKey('obras.id', ondelete='CASCADE'), nullable=False),
        sa.Column('anio', sa.Integer(), nullable=False),
        sa.Column('mes', sa.Integer(), nullable=False),
        sa.Column('direccion', sa.String(32), nullable=False),
        sa.Column('secuencia', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('resultado', sa.String(20), nullable=False, server_default='en_mesa'),
        sa.Column('propuesta_id', sa.Integer(), sa.ForeignKey('certificacion_propuestas.id', ondelete='SET NULL'), nullable=True),
        sa.Column('enviada_at', sa.DateTime(), nullable=False),
        sa.Column('enviada_por_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('respondida_at', sa.DateTime(), nullable=True),
        sa.Column('respondida_por_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('comentario_rechazo', sa.Text(), nullable=True),
        sa.Column('horas_total', sa.Numeric(10, 2), nullable=True),
        sa.Column('importe_total', sa.Numeric(12, 2), nullable=True),
        sa.Column('lineas_json', sa.JSON(), nullable=False),
        schema=schema,
    )
    op.create_index(
        'ix_cert_ronda_obra_periodo',
        'certificacion_rondas',
        ['company_id', 'obra_id', 'anio', 'mes'],
        schema=schema,
    )


def downgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    if 'certificacion_rondas' not in _tables(bind, schema):
        return
    op.drop_index('ix_cert_ronda_obra_periodo', table_name='certificacion_rondas', schema=schema)
    op.drop_table('certificacion_rondas', schema=schema)
