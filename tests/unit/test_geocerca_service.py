# tests/unit/test_geocerca_service.py

from types import SimpleNamespace

import pytest

from app.services.geocerca_service import (
    GEO_COINCIDE,
    GEO_DUDOSA,
    GEO_NO_APLICA,
    GEO_OBRA_SIN_GEO,
    distancia_metros,
    evaluar_geo_fichaje,
    normalizar_modo_geo_config,
    obra_en_radio,
    preseleccion_obra_id,
)


def test_distancia_metros_cero_en_mismo_punto():
    assert distancia_metros(40.0, -3.0, 40.0, -3.0) == pytest.approx(0.0, abs=0.1)


def test_normalizar_modo_geo_legacy():
    assert normalizar_modo_geo_config('opcional') == 'activada'
    assert normalizar_modo_geo_config('obligatoria') == 'activada'
    assert normalizar_modo_geo_config('desactivada') == 'desactivada'


def test_obra_sin_geo_es_correcta(monkeypatch):
    monkeypatch.setattr('app.services.geocerca_service.geocerca_activa', lambda: True)
    monkeypatch.setattr(
        'app.services.fichaje_operario_service.geolocalizacion_activa',
        lambda: True,
    )
    obra = SimpleNamespace(latitud=None, longitud=None, radio_metros=None)
    estado, dist = evaluar_geo_fichaje(obra, 40.0, -3.0)
    assert estado == GEO_OBRA_SIN_GEO
    assert dist is None


def test_fuera_de_radio_es_dudosa(monkeypatch):
    monkeypatch.setattr('app.services.geocerca_service.geocerca_activa', lambda: True)
    monkeypatch.setattr(
        'app.services.fichaje_operario_service.geolocalizacion_activa',
        lambda: True,
    )
    monkeypatch.setattr('app.services.geocerca_service.radio_default_metros', lambda: 100)
    obra = SimpleNamespace(latitud=40.0, longitud=-3.0)
    estado, dist = evaluar_geo_fichaje(obra, 40.01, -3.0)
    assert estado == GEO_DUDOSA
    assert dist is not None
    assert dist > 100


def test_dentro_de_radio_coincide(monkeypatch):
    monkeypatch.setattr('app.services.geocerca_service.geocerca_activa', lambda: True)
    monkeypatch.setattr(
        'app.services.fichaje_operario_service.geolocalizacion_activa',
        lambda: True,
    )
    obra = SimpleNamespace(latitud=40.0, longitud=-3.0, radio_metros=500)
    estado, dist = evaluar_geo_fichaje(obra, 40.0001, -3.0001)
    assert estado == GEO_COINCIDE
    assert dist is not None


def test_geocerca_inactiva_no_aplica(monkeypatch):
    monkeypatch.setattr('app.services.geocerca_service.geocerca_activa', lambda: False)
    monkeypatch.setattr(
        'app.services.fichaje_operario_service.geolocalizacion_activa',
        lambda: True,
    )
    obra = SimpleNamespace(latitud=40.0, longitud=-3.0, radio_metros=100)
    estado, dist = evaluar_geo_fichaje(obra, 41.0, -3.0)
    assert estado == GEO_NO_APLICA
    assert dist is None


def test_preseleccion_prioriza_ultima_obra_en_radio(monkeypatch):
    obras = [
        SimpleNamespace(id=1, latitud=40.0, longitud=-3.0, radio_metros=200, nombre='A'),
        SimpleNamespace(id=2, latitud=40.0002, longitud=-3.0, radio_metros=200, nombre='B'),
    ]
    monkeypatch.setattr('app.services.geocerca_service.geocerca_activa', lambda: True)
    monkeypatch.setattr(
        'app.services.geocerca_service.ultima_obra_entrada_id',
        lambda uid, fecha: 2,
    )
    elegida = preseleccion_obra_id(1, None, [], obras, latitud=40.0001, longitud=-3.0)
    assert elegida == 2


def test_radio_obra_usa_config_global(monkeypatch):
    monkeypatch.setattr('app.services.geocerca_service.radio_default_metros', lambda: 250)
    obra = SimpleNamespace(latitud=40.0, longitud=-3.0, radio_metros=50)
    from app.services.geocerca_service import radio_obra_metros
    assert radio_obra_metros(obra) == 250


def test_obra_en_radio():
    obra = SimpleNamespace(latitud=40.0, longitud=-3.0)
    dentro, dist = obra_en_radio(obra, 40.0005, -3.0)
    assert dentro is True
    assert dist is not None
