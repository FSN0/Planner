"""CertificacionPropuesta: una por empresa + obra + mes + dirección.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-10-06
"""
from collections import defaultdict

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'e9f0a1b2c3d4'
down_revision = 'd8e9f0a1b2c3'
branch_labels = None
depends_on = None


def _schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _tables(bind, schema):
    return set(inspect(bind).get_table_names(schema=schema))


def _cols(bind, table, schema):
    return {c['name'] for c in inspect(bind).get_columns(table, schema=schema)}


def _uq_names(bind, table, schema):
    return {u['name'] for u in inspect(bind).get_unique_constraints(table, schema=schema)}


def upgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    tables = _tables(bind, schema)
    if 'certificacion_propuestas' not in tables:
        return

    cols = _cols(bind, 'certificacion_propuestas', schema)
    uqs = _uq_names(bind, 'certificacion_propuestas', schema)

    if 'uq_cert_propuesta_periodo' in uqs:
        with op.batch_alter_table('certificacion_propuestas', schema=schema) as batch:
            batch.drop_constraint('uq_cert_propuesta_periodo', type_='unique')

    if 'obra_id' not in cols:
        with op.batch_alter_table('certificacion_propuestas', schema=schema) as batch:
            batch.add_column(sa.Column('obra_id', sa.Integer(), nullable=True))

    props = bind.execute(text(
        'SELECT id, company_id, anio, mes, direccion, estado, comentario_rechazo, '
        'enviada_at, aceptada_at, enviada_por_id, respondida_por_id, created_at '
        'FROM certificacion_propuestas'
    )).mappings().all()

    for prop in props:
        lineas = bind.execute(text(
            'SELECT id, obra_id FROM certificacion_lineas WHERE propuesta_id = :pid'
        ), {'pid': prop['id']}).mappings().all()
        by_obra = defaultdict(list)
        for ln in lineas:
            if ln['obra_id'] is None:
                continue
            by_obra[int(ln['obra_id'])].append(int(ln['id']))

        if not by_obra:
            bind.execute(text('DELETE FROM certificacion_propuestas WHERE id = :pid'), {
                'pid': prop['id'],
            })
            continue

        obra_ids = sorted(by_obra.keys())
        first_obra = obra_ids[0]
        bind.execute(text(
            'UPDATE certificacion_propuestas SET obra_id = :oid WHERE id = :pid'
        ), {'oid': first_obra, 'pid': prop['id']})

        for oid in obra_ids[1:]:
            new_id = bind.execute(text(
                """
                INSERT INTO certificacion_propuestas (
                    company_id, obra_id, anio, mes, direccion, estado,
                    comentario_rechazo, enviada_at, aceptada_at,
                    enviada_por_id, respondida_por_id, created_at
                ) VALUES (
                    :company_id, :obra_id, :anio, :mes, :direccion, :estado,
                    :comentario_rechazo, :enviada_at, :aceptada_at,
                    :enviada_por_id, :respondida_por_id, :created_at
                ) RETURNING id
                """
            ), {
                'company_id': prop['company_id'],
                'obra_id': oid,
                'anio': prop['anio'],
                'mes': prop['mes'],
                'direccion': prop['direccion'],
                'estado': prop['estado'],
                'comentario_rechazo': prop['comentario_rechazo'],
                'enviada_at': prop['enviada_at'],
                'aceptada_at': prop['aceptada_at'],
                'enviada_por_id': prop['enviada_por_id'],
                'respondida_por_id': prop['respondida_por_id'],
                'created_at': prop['created_at'],
            }).scalar()
            ids = by_obra[oid]
            for lid in ids:
                bind.execute(text(
                    'UPDATE certificacion_lineas SET propuesta_id = :nid WHERE id = :lid'
                ), {'nid': new_id, 'lid': lid})

    # Huérfanas / sin obra tras split
    bind.execute(text('DELETE FROM certificacion_propuestas WHERE obra_id IS NULL'))

    uqs_after = _uq_names(bind, 'certificacion_propuestas', schema)
    fks_after = {
        fk['name'] for fk in inspect(bind).get_foreign_keys(
            'certificacion_propuestas', schema=schema,
        )
    }
    with op.batch_alter_table('certificacion_propuestas', schema=schema) as batch:
        batch.alter_column('obra_id', existing_type=sa.Integer(), nullable=False)
        if 'uq_cert_propuesta_obra_periodo' not in uqs_after:
            batch.create_unique_constraint(
                'uq_cert_propuesta_obra_periodo',
                ['company_id', 'obra_id', 'anio', 'mes', 'direccion'],
            )
        if 'fk_cert_propuesta_obra' not in fks_after:
            batch.create_foreign_key(
                'fk_cert_propuesta_obra', 'obras',
                ['obra_id'], ['id'], ondelete='CASCADE',
            )


def downgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    if 'certificacion_propuestas' not in _tables(bind, schema):
        return
    if 'obra_id' not in _cols(bind, 'certificacion_propuestas', schema):
        return

    # Fusionar de nuevo por (company, anio, mes, direccion): se queda la de menor id.
    rows = bind.execute(text(
        'SELECT id, company_id, anio, mes, direccion, obra_id '
        'FROM certificacion_propuestas ORDER BY id'
    )).mappings().all()
    keep = {}
    for row in rows:
        key = (row['company_id'], row['anio'], row['mes'], row['direccion'])
        if key not in keep:
            keep[key] = row['id']
            continue
        keeper = keep[key]
        bind.execute(text(
            'UPDATE certificacion_lineas SET propuesta_id = :kid '
            'WHERE propuesta_id = :pid'
        ), {'kid': keeper, 'pid': row['id']})
        bind.execute(text('DELETE FROM certificacion_propuestas WHERE id = :pid'), {
            'pid': row['id'],
        })

    with op.batch_alter_table('certificacion_propuestas', schema=schema) as batch:
        fks = {fk['name'] for fk in inspect(bind).get_foreign_keys(
            'certificacion_propuestas', schema=schema,
        )}
        if 'fk_cert_propuesta_obra' in fks:
            batch.drop_constraint('fk_cert_propuesta_obra', type_='foreignkey')
        uqs = _uq_names(bind, 'certificacion_propuestas', schema)
        if 'uq_cert_propuesta_obra_periodo' in uqs:
            batch.drop_constraint('uq_cert_propuesta_obra_periodo', type_='unique')
        batch.drop_column('obra_id')
        batch.create_unique_constraint(
            'uq_cert_propuesta_periodo',
            ['company_id', 'anio', 'mes', 'direccion'],
        )
