"""Plantillas con varios ficheros (DNI anverso/reverso).

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'c7d8e9f0a1b2'
down_revision = 'b6c7d8e9f0a1'
branch_labels = None
depends_on = None

SLOTS_DNI = (
    '[{"codigo":"anverso","nombre":"Por delante"},'
    '{"codigo":"reverso","nombre":"Por detrás"}]'
)


def _schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _tables(bind, schema):
    return set(inspect(bind).get_table_names(schema=schema))


def _cols(bind, table, schema):
    return {c['name'] for c in inspect(bind).get_columns(table, schema=schema)}


def upgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    tables = _tables(bind, schema)
    if 'documento_tipos' not in tables:
        return

    tipo_cols = _cols(bind, 'documento_tipos', schema)
    if 'slots_json' not in tipo_cols:
        with op.batch_alter_table('documento_tipos', schema=schema) as batch:
            batch.add_column(sa.Column('slots_json', sa.Text(), nullable=True))

    if 'documento_aportes' in tables:
        aporte_cols = _cols(bind, 'documento_aportes', schema)
        if 'slot' not in aporte_cols:
            with op.batch_alter_table('documento_aportes', schema=schema) as batch:
                batch.add_column(sa.Column('slot', sa.String(40), nullable=True))

    # Unifica DNI anverso + reverso en una sola plantilla con dos huecos.
    anverso = bind.execute(text(
        "SELECT id FROM documento_tipos WHERE codigo = 'dni_anverso' LIMIT 1"
    )).first()
    reverso = bind.execute(text(
        "SELECT id FROM documento_tipos WHERE codigo = 'dni_reverso' LIMIT 1"
    )).first()
    dni = bind.execute(text(
        "SELECT id FROM documento_tipos WHERE codigo = 'dni' LIMIT 1"
    )).first()

    if anverso and not dni:
        bind.execute(text(
            "UPDATE documento_tipos SET codigo = 'dni', nombre = 'DNI/NIE', "
            "slots_json = :slots WHERE id = :id"
        ), {'slots': SLOTS_DNI, 'id': anverso[0]})
        dni_id = anverso[0]
        bind.execute(text(
            "UPDATE documento_aportes SET slot = 'anverso' "
            "WHERE tipo_id = :id AND (slot IS NULL OR slot = '')"
        ), {'id': dni_id})
    elif dni:
        dni_id = dni[0]
        bind.execute(text(
            "UPDATE documento_tipos SET slots_json = :slots, nombre = COALESCE(NULLIF(nombre, ''), 'DNI/NIE') "
            "WHERE id = :id"
        ), {'slots': SLOTS_DNI, 'id': dni_id})
    else:
        dni_id = None

    if reverso and dni_id:
        rev_id = reverso[0]
        bind.execute(text(
            "UPDATE documento_aportes SET tipo_id = :dni, slot = 'reverso' WHERE tipo_id = :rev"
        ), {'dni': dni_id, 'rev': rev_id})
        bind.execute(text(
            "UPDATE documento_exigencias SET tipo_id = :dni WHERE tipo_id = :rev"
        ), {'dni': dni_id, 'rev': rev_id})
        bind.execute(text(
            "UPDATE documento_tipos SET activo = false, codigo = 'dni_reverso_legacy' WHERE id = :rev"
        ), {'rev': rev_id})


def downgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    tables = _tables(bind, schema)
    if 'documento_tipos' not in tables:
        return
    tipo_cols = _cols(bind, 'documento_tipos', schema)
    if 'slots_json' in tipo_cols:
        with op.batch_alter_table('documento_tipos', schema=schema) as batch:
            batch.drop_column('slots_json')
    if 'documento_aportes' in tables:
        aporte_cols = _cols(bind, 'documento_aportes', schema)
        if 'slot' in aporte_cols:
            with op.batch_alter_table('documento_aportes', schema=schema) as batch:
                batch.drop_column('slot')
