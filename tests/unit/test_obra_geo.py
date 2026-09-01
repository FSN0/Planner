# tests/unit/test_obra_geo.py

from types import SimpleNamespace

import pytest

from app.utils.obra_geo import aplicar_obra_geo_json, parse_obra_geo_form


def test_parse_obra_geo_form_solo_lat_rechaza():
    lat, lng = parse_obra_geo_form({'latitud': '40.0', 'longitud': ''})
    assert lat is None and lng is None


def test_aplicar_obra_geo_json_fija_pin():
    obra = SimpleNamespace(latitud=None, longitud=None, ubicacion=None)
    aplicar_obra_geo_json(obra, {
        'latitud': 40.1,
        'longitud': -3.7,
        'ubicacion': 'Calle Mayor',
    })
    assert obra.latitud == pytest.approx(40.1)
    assert obra.longitud == pytest.approx(-3.7)
    assert obra.ubicacion == 'Calle Mayor'


def test_aplicar_obra_geo_json_limpia():
    obra = SimpleNamespace(latitud=40.0, longitud=-3.0, ubicacion='Vieja')
    aplicar_obra_geo_json(obra, {'limpiar': True})
    assert obra.latitud is None
    assert obra.longitud is None
    assert obra.ubicacion is None


def test_truncar_ubicacion():
    from app.utils.obra_geo import truncar_ubicacion
    larga = 'x' * 150
    assert len(truncar_ubicacion(larga)) == 100
