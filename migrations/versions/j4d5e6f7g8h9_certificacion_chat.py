"""CertificacionChatMensaje: chat/notas de certificación.

Revision ID: j4d5e6f7g8h9
Revises: i3c4d5e6f7g8
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'j4d5e6f7g8h9'
down_revision = 'i3c4d5e6f7g8'
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
    if 'certificacion_chat_mensajes' in _tables(bind, schema):
        return
    op.create_table(
        'certificacion_chat_mensajes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('obra_id', sa.Integer(), sa.ForeignKey('obras.id', ondelete='CASCADE'), nullable=False),
        sa.Column('anio', sa.Integer(), nullable=False),
        sa.Column('mes', sa.Integer(), nullable=False),
        sa.Column('direccion', sa.String(32), nullable=False, server_default='sistema'),
        sa.Column('tipo', sa.String(20), nullable=False, server_default='nota'),
        sa.Column('texto', sa.Text(), nullable=False),
        sa.Column('autor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        schema=schema,
    )
    op.create_index(
        'ix_cert_chat_obra_periodo',
        'certificacion_chat_mensajes',
        ['company_id', 'obra_id', 'anio', 'mes'],
        schema=schema,
    )


def downgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    if 'certificacion_chat_mensajes' not in _tables(bind, schema):
        return
    op.drop_index('ix_cert_chat_obra_periodo', table_name='certificacion_chat_mensajes', schema=schema)
    op.drop_table('certificacion_chat_mensajes', schema=schema)
