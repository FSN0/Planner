from app.services.tour_catalog_service import INITIAL_TOUR_IDS, SHARED_TOUR_IDS


def test_recorrido_inicial_orden_obra_antes_persona():
    assert INITIAL_TOUR_IDS == (
        'tablero_leer',
        'tablero_asignar',
        'obra',
        'trabajadores',
        'fichaje',
    )


def test_calendario_es_tutorial_opcional():
    assert 'calendario' in SHARED_TOUR_IDS
    assert 'calendario' not in INITIAL_TOUR_IDS
