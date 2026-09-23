"""Estados de obra (locales) y mapeo desde Odoo BIM.

Ciclo Soltec:
  Pendiente → En Curso → En Garantía → Finalizada

«En Garantía» se planifica igual que «En Curso» (gente, flota, tablero…).
Solo deja de ser activa al pasar a Finalizada (o estados muertos equivalentes).
"""
from __future__ import annotations

ESTADO_PENDIENTE = 'Pendiente'
ESTADO_EN_CURSO = 'En Curso'
ESTADO_EN_GARANTIA = 'En Garantía'
ESTADO_FINALIZADA = 'Finalizada'
ESTADO_PLANIFICADA = 'PLANIFICADA'  # legado puntual

ESTADOS_VALIDOS = (
    ESTADO_PENDIENTE,
    ESTADO_EN_CURSO,
    ESTADO_EN_GARANTIA,
    ESTADO_FINALIZADA,
)

# Aparecen en tablero / se puede asignar gente y coches
ESTADOS_PLANIFICABLES = frozenset({
    ESTADO_EN_CURSO,
    ESTADO_EN_GARANTIA,
    ESTADO_PLANIFICADA,
})

ESTADOS_CERRADOS = frozenset({
    ESTADO_FINALIZADA,
    'Cerrada',
    'Cancelada',
    'FINALIZADA',
})


def normalize_estado(estado: str | None) -> str:
    return (estado or '').strip()


def obra_estado_planificable(estado: str | None) -> bool:
    return normalize_estado(estado) in ESTADOS_PLANIFICABLES


def obra_estado_cerrado(estado: str | None) -> bool:
    e = normalize_estado(estado)
    if not e:
        return False
    if e in ESTADOS_CERRADOS:
        return True
    return e.lower() in {'finalizada', 'cerrada', 'cancelada'}


def filter_obras_planificables(query):
    """Aplica filtro SQLAlchemy Obra.estado ∈ planificables."""
    from app.models import Obra
    return query.filter(Obra.estado.in_(list(ESTADOS_PLANIFICABLES)))


def map_odoo_bim_state_name(state_name: str | None) -> str:
    """Nombre de bim.project.state → estado local."""
    n = (state_name or '').strip().lower()
    if not n:
        return ESTADO_PENDIENTE
    if 'garant' in n:
        return ESTADO_EN_GARANTIA
    if 'ejecuci' in n:
        return ESTADO_EN_CURSO
    # Cualquier otro stage activo que hayamos pedido: no inventar Finalizada aquí
    return ESTADO_PENDIENTE
