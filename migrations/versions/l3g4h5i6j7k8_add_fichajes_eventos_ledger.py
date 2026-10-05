"""libro de eventos de fichaje inalterable (append-only + cadena de hash)

Crea la tabla 'fichajes_eventos' y los disparadores que impiden modificar o
borrar filas. A partir de aquí el registro de jornada deja de ser una fila que
se sobrescribe y pasa a ser un libro que solo crece.

El relleno con el histórico existente no se hace aquí: se ejecuta después con
`flask fichajes backfill`, que es idempotente y emite un informe.

Revision ID: l3g4h5i6j7k8
Revises: k2f3g4h5i6j7
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

from app.ddl import desproteger_libro_fichajes, proteger_libro_fichajes


revision = 'l3g4h5i6j7k8'
down_revision = 'k2f3g4h5i6j7'
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

    # El esquema 'public' no aloja datos de tenant: allí no hay fichajes.
    if not _table_exists(bind, 'users', schema):
        return

    if not _table_exists(bind, 'fichajes_eventos', schema):
        op.create_table(
            'fichajes_eventos',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('secuencia', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('tipo', sa.String(length=20), nullable=False),
            sa.Column('origen', sa.String(length=20), nullable=False),
            sa.Column('fecha_laboral', sa.Date(), nullable=False),
            sa.Column('ocurrido_en', sa.DateTime(), nullable=False),
            sa.Column('registrado_en', sa.DateTime(), nullable=False),
            sa.Column('zona_horaria', sa.String(length=64), nullable=True),
            sa.Column('autor_id', sa.Integer(), nullable=True),
            sa.Column('obra_id', sa.Integer(), nullable=True),
            sa.Column('latitud', sa.Float(), nullable=True),
            sa.Column('longitud', sa.Float(), nullable=True),
            sa.Column('precision_metros', sa.Float(), nullable=True),
            sa.Column('dispositivo', sa.String(length=255), nullable=True),
            sa.Column('ip', sa.String(length=45), nullable=True),
            sa.Column('motivo', sa.Text(), nullable=True),
            sa.Column('evento_anulado_id', sa.Integer(), nullable=True),
            sa.Column('external_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column('hash_previo', sa.String(length=64), nullable=True),
            sa.Column('hash', sa.String(length=64), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('secuencia', name='uq_fichajes_eventos_secuencia'),
            sa.ForeignKeyConstraint(['user_id'], [f'{schema}.users.id']),
            sa.ForeignKeyConstraint(['autor_id'], [f'{schema}.users.id']),
            sa.ForeignKeyConstraint(['obra_id'], [f'{schema}.obras.id']),
            sa.ForeignKeyConstraint(
                ['evento_anulado_id'], [f'{schema}.fichajes_eventos.id']
            ),
            schema=schema,
        )
        op.create_index(
            'ix_fichajes_eventos_user_fecha',
            'fichajes_eventos',
            ['user_id', 'fecha_laboral'],
            schema=schema,
        )
        op.create_index(
            'ix_fichajes_eventos_ocurrido',
            'fichajes_eventos',
            ['ocurrido_en'],
            schema=schema,
        )

    proteger_libro_fichajes(op.execute, schema)


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'fichajes_eventos', schema):
        return

    desproteger_libro_fichajes(op.execute, schema)
    op.drop_index('ix_fichajes_eventos_ocurrido', 'fichajes_eventos', schema=schema)
    op.drop_index('ix_fichajes_eventos_user_fecha', 'fichajes_eventos', schema=schema)
    op.drop_table('fichajes_eventos', schema=schema)
