"""add log_acknowledgements for laboral unread tracking

Revision ID: h9c0d1e2f3g4
Revises: g8b9c0d1e2f3
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'h9c0d1e2f3g4'
down_revision = 'g8b9c0d1e2f3'
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

    # Solo donde existen users + system_logs (esquemas de tenant; public suele no tenerlos)
    if not _table_exists(bind, 'users', schema):
        return
    if not _table_exists(bind, 'system_logs', schema):
        return
    if _table_exists(bind, 'log_acknowledgements', schema):
        return

    op.create_table(
        'log_acknowledgements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey(f'{schema}.users.id'), nullable=False),
        sa.Column('log_id', sa.Integer(), sa.ForeignKey(f'{schema}.system_logs.id'), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'log_id', name='uq_log_ack_user_log'),
        schema=schema,
    )
    op.create_index(
        'ix_log_acknowledgements_user_id',
        'log_acknowledgements',
        ['user_id'],
        schema=schema,
    )
    op.create_index(
        'ix_log_acknowledgements_log_id',
        'log_acknowledgements',
        ['log_id'],
        schema=schema,
    )


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema:
        return
    if not _table_exists(bind, 'log_acknowledgements', schema):
        return
    op.drop_index('ix_log_acknowledgements_log_id', table_name='log_acknowledgements', schema=schema)
    op.drop_index('ix_log_acknowledgements_user_id', table_name='log_acknowledgements', schema=schema)
    op.drop_table('log_acknowledgements', schema=schema)
