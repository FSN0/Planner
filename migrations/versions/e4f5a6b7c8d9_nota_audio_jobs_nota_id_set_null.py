"""nota_audio_jobs.nota_id ON DELETE SET NULL

Al borrar una nota creada por voz no debe fallar por FK.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-09-03
"""
from alembic import op
from sqlalchemy import inspect, text


revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def _current_schema(bind):
    return bind.execute(text('SELECT current_schema()')).scalar()


def _table_exists(bind, table_name, schema):
    return table_name in inspect(bind).get_table_names(schema=schema)


def upgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'nota_audio_jobs', schema):
        return

    # Nombre real del constraint (Postgres lo genera; puede variar).
    rows = bind.execute(text("""
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE nsp.nspname = :schema
          AND rel.relname = 'nota_audio_jobs'
          AND con.contype = 'f'
          AND pg_get_constraintdef(con.oid) ILIKE '%nota_id%'
    """), {'schema': schema}).fetchall()

    for (conname,) in rows:
        bind.execute(text(
            f'ALTER TABLE "{schema}".nota_audio_jobs DROP CONSTRAINT IF EXISTS "{conname}"'
        ))

    bind.execute(text(f"""
        ALTER TABLE "{schema}".nota_audio_jobs
        ADD CONSTRAINT nota_audio_jobs_nota_id_fkey
        FOREIGN KEY (nota_id) REFERENCES "{schema}".notas(id)
        ON DELETE SET NULL
    """))


def downgrade():
    bind = op.get_bind()
    schema = _current_schema(bind)
    if not schema or not _table_exists(bind, 'nota_audio_jobs', schema):
        return

    bind.execute(text(
        f'ALTER TABLE "{schema}".nota_audio_jobs '
        f'DROP CONSTRAINT IF EXISTS nota_audio_jobs_nota_id_fkey'
    ))
    bind.execute(text(f"""
        ALTER TABLE "{schema}".nota_audio_jobs
        ADD CONSTRAINT nota_audio_jobs_nota_id_fkey
        FOREIGN KEY (nota_id) REFERENCES "{schema}".notas(id)
    """))
