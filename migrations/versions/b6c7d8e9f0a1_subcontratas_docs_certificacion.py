"""Portal subcontrata, documentación, certificación y contratación.

Revision ID: b6c7d8e9f0a1
Revises: w5x6y7z8a9b0
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = 'b6c7d8e9f0a1'
down_revision = 'w5x6y7z8a9b0'
branch_labels = None
depends_on = None


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
    if 'users' not in tables:
        return

    user_cols = _cols(bind, 'users', schema)
    with op.batch_alter_table('users', schema=schema) as batch:
        if 'visible_en_cuadrante' not in user_cols:
            batch.add_column(sa.Column(
                'visible_en_cuadrante', sa.Boolean(), nullable=False, server_default='false',
            ))
        if 'hiring_state' not in user_cols:
            batch.add_column(sa.Column('hiring_state', sa.String(20), nullable=True))
        if 'fecha_inicio' not in user_cols:
            batch.add_column(sa.Column('fecha_inicio', sa.Date(), nullable=True))
        if 'telefono' not in user_cols:
            batch.add_column(sa.Column('telefono', sa.String(40), nullable=True))
        if 'talla_ropa' not in user_cols:
            batch.add_column(sa.Column('talla_ropa', sa.String(40), nullable=True))
        if 'numero_cuenta' not in user_cols:
            batch.add_column(sa.Column('numero_cuenta', sa.String(64), nullable=True))
        if 'firma_contrato_estado' not in user_cols:
            batch.add_column(sa.Column(
                'firma_contrato_estado', sa.String(20), nullable=False, server_default='pendiente',
            ))

    bind.execute(text(
        """
        UPDATE users
        SET visible_en_cuadrante = TRUE
        WHERE role IN ('operario', 'admin_subcontrata')
        """
    ))

    if 'companies' in tables and 'precio_hora' not in _cols(bind, 'companies', schema):
        with op.batch_alter_table('companies', schema=schema) as batch:
            batch.add_column(sa.Column('precio_hora', sa.Numeric(10, 2), nullable=True))

    if 'registros_fichajes' in tables and 'estado_odoo' not in _cols(bind, 'registros_fichajes', schema):
        with op.batch_alter_table('registros_fichajes', schema=schema) as batch:
            batch.add_column(sa.Column('estado_odoo', sa.String(20), nullable=True))

    tables = _tables(bind, schema)
    if 'documento_tipos' not in tables:
        op.create_table(
            'documento_tipos',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('codigo', sa.String(60), nullable=True),
            sa.Column('nombre', sa.String(200), nullable=False),
            sa.Column('categoria', sa.String(80), nullable=False),
            sa.Column('ambito', sa.String(20), nullable=False),
            sa.Column('audiencia', sa.String(20), nullable=False),
            sa.Column('regla_renovacion', sa.String(20), nullable=False, server_default='ninguna'),
            sa.Column('dia_renovacion', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('mes_renovacion', sa.Integer(), nullable=True),
            sa.Column('es_sistema', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('fase_contratacion', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('bloquea_fase', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('obligatorio', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('es_certificacion', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('orden', sa.Integer(), nullable=False, server_default='100'),
            sa.Column('activo', sa.Boolean(), nullable=False, server_default='true'),
            sa.UniqueConstraint('codigo', name='uq_documento_tipos_codigo'),
            schema=schema,
        )
    if 'documento_exigencias' not in tables:
        op.create_table(
            'documento_exigencias',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tipo_id', sa.Integer(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=True),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('destino', sa.String(20), nullable=False),
            sa.Column('modo', sa.String(20), nullable=False),
            sa.ForeignKeyConstraint(['tipo_id'], [f'{schema}.documento_tipos.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['company_id'], [f'{schema}.companies.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], [f'{schema}.users.id'], ondelete='CASCADE'),
            schema=schema,
        )
    if 'documento_aportes' not in tables:
        op.create_table(
            'documento_aportes',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tipo_id', sa.Integer(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=True),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('archivo_path', sa.String(300), nullable=True),
            sa.Column('nombre_original', sa.String(255), nullable=True),
            sa.Column('nota', sa.Text(), nullable=True),
            sa.Column('estado', sa.String(20), nullable=False, server_default='subido'),
            sa.Column('nota_oficina', sa.Text(), nullable=True),
            sa.Column('caduca_el', sa.Date(), nullable=True),
            sa.Column('aceptado_caducado', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('validado_por_id', sa.Integer(), nullable=True),
            sa.Column('validado_at', sa.DateTime(), nullable=True),
            sa.Column('subido_por_id', sa.Integer(), nullable=True),
            sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('vigente', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['tipo_id'], [f'{schema}.documento_tipos.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['company_id'], [f'{schema}.companies.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], [f'{schema}.users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['validado_por_id'], [f'{schema}.users.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['subido_por_id'], [f'{schema}.users.id'], ondelete='SET NULL'),
            schema=schema,
        )
    if 'certificacion_propuestas' not in tables:
        op.create_table(
            'certificacion_propuestas',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('anio', sa.Integer(), nullable=False),
            sa.Column('mes', sa.Integer(), nullable=False),
            sa.Column('direccion', sa.String(32), nullable=False),
            sa.Column('estado', sa.String(20), nullable=False, server_default='borrador'),
            sa.Column('comentario_rechazo', sa.Text(), nullable=True),
            sa.Column('enviada_at', sa.DateTime(), nullable=True),
            sa.Column('aceptada_at', sa.DateTime(), nullable=True),
            sa.Column('enviada_por_id', sa.Integer(), nullable=True),
            sa.Column('respondida_por_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['company_id'], [f'{schema}.companies.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['enviada_por_id'], [f'{schema}.users.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['respondida_por_id'], [f'{schema}.users.id'], ondelete='SET NULL'),
            sa.UniqueConstraint('company_id', 'anio', 'mes', 'direccion', name='uq_cert_propuesta_periodo'),
            schema=schema,
        )
    if 'certificacion_lineas' not in tables:
        op.create_table(
            'certificacion_lineas',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('propuesta_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('obra_id', sa.Integer(), nullable=False),
            sa.Column('fecha', sa.Date(), nullable=False),
            sa.Column('hora_inicio', sa.Time(), nullable=True),
            sa.Column('hora_fin', sa.Time(), nullable=True),
            sa.Column('horas', sa.Numeric(8, 2), nullable=True),
            sa.Column('precio_hora', sa.Numeric(10, 2), nullable=True),
            sa.Column('origen_horas', sa.String(20), nullable=False, server_default='vacio'),
            sa.Column('estado_fichaje', sa.String(20), nullable=True),
            sa.Column('solape', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('discrepancia', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('nota_discrepancia', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['propuesta_id'], [f'{schema}.certificacion_propuestas.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], [f'{schema}.users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['obra_id'], [f'{schema}.obras.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('propuesta_id', 'user_id', 'obra_id', 'fecha', name='uq_cert_linea'),
            schema=schema,
        )


def downgrade():
    bind = op.get_bind()
    schema = _schema(bind)
    if not schema or schema == 'public':
        return
    tables = _tables(bind, schema)
    for name in (
        'certificacion_lineas',
        'certificacion_propuestas',
        'documento_aportes',
        'documento_exigencias',
        'documento_tipos',
    ):
        if name in tables:
            op.drop_table(name, schema=schema)
