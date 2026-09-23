"""Estados de obra y mapeo Odoo BIM."""
from app.services.obra_estado_service import (
    ESTADO_EN_CURSO,
    ESTADO_EN_GARANTIA,
    ESTADO_FINALIZADA,
    ESTADO_PENDIENTE,
    ESTADOS_PLANIFICABLES,
    map_odoo_bim_state_name,
    obra_estado_cerrado,
    obra_estado_planificable,
)


def test_map_odoo_bim_states():
    assert map_odoo_bim_state_name('Ejecución') == ESTADO_EN_CURSO
    assert map_odoo_bim_state_name('En Ejecucion') == ESTADO_EN_CURSO
    assert map_odoo_bim_state_name('Garantía') == ESTADO_EN_GARANTIA
    assert map_odoo_bim_state_name('En garantía') == ESTADO_EN_GARANTIA
    assert map_odoo_bim_state_name('Otro') == ESTADO_PENDIENTE


def test_planificable_incluye_garantia():
    assert obra_estado_planificable(ESTADO_EN_CURSO)
    assert obra_estado_planificable(ESTADO_EN_GARANTIA)
    assert not obra_estado_planificable(ESTADO_PENDIENTE)
    assert not obra_estado_planificable(ESTADO_FINALIZADA)
    assert ESTADO_EN_GARANTIA in ESTADOS_PLANIFICABLES


def test_cerrado():
    assert obra_estado_cerrado(ESTADO_FINALIZADA)
    assert not obra_estado_cerrado(ESTADO_EN_GARANTIA)
