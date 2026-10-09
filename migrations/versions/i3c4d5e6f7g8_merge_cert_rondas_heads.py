"""Merge heads: tenant_roles/nota_audio + certificacion_rondas.

Revision ID: i3c4d5e6f7g8
Revises: m6n7o8p9q0r1, h2b3c4d5e6f7
Create Date: 2026-10-09
"""

revision = 'i3c4d5e6f7g8'
down_revision = ('m6n7o8p9q0r1', 'h2b3c4d5e6f7')
branch_labels = None
depends_on = None


def upgrade():
    # Merge only: alinea el grafo para `flask db upgrade`.
    pass


def downgrade():
    pass
