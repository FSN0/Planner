"""Merge de heads para evitar ramas simultáneas

Esto existe para que `flask db upgrade` funcione cuando hay más de un head
en el grafo de migraciones (dev).
"""

from alembic import op

revision = 'm6n7o8p9q0r1'
down_revision = ('e4f5a6b7c8d9', 'f5a6b7c8d9e0')
branch_labels = None
depends_on = None


def upgrade():
    # No operations: es una migración de merge para alinear el grafo.
    pass


def downgrade():
    # No operations: revertir un merge dependería del camino exacto.
    pass

