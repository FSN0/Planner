# tests/unit/test_mapa_fichajes_service.py

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.services.mapa_fichajes_service import (
    normalizar_rango,
    fichajes_mapa_obra,
)


def test_normalizar_rango_default_hoy():
    with patch('app.services.mapa_fichajes_service.today_local', return_value=date(2026, 9, 1)):
        d, h = normalizar_rango(None, None)
        assert d == date(2026, 9, 1)
        assert h == date(2026, 9, 1)


def test_normalizar_rango_limita_90_dias():
    with patch('app.services.mapa_fichajes_service.today_local', return_value=date(2026, 9, 1)):
        d, h = normalizar_rango(date(2020, 1, 1), date(2026, 9, 1))
        assert (h - d).days <= 90


@patch('app.services.mapa_fichajes_service.vigentes')
@patch('app.services.mapa_fichajes_service.FichajeEvento')
@patch('app.services.mapa_fichajes_service._obra_visible')
@patch('app.services.mapa_fichajes_service.User')
def test_fichajes_mapa_solo_entradas_con_gps(mock_user, mock_obra_vis, mock_evento, mock_vigentes):
    obra = SimpleNamespace(
        id=1, nombre='Obra A', codigo='A1',
        latitud=40.0, longitud=-3.0, ubicacion='Calle',
    )
    mock_obra_vis.return_value = obra
    entrada_ok = SimpleNamespace(
        id=10, user_id=5, tipo='entrada',
        latitud=40.001, longitud=-3.001,
        geo_estado='coincide', distancia_obra_metros=50,
        nota_ubicacion=None, precision_metros=10,
        fecha_laboral=date(2026, 9, 1),
        ocurrido_en=SimpleNamespace(strftime=lambda fmt: '08:30'),
    )
    entrada_sin_gps = SimpleNamespace(
        id=11, user_id=5, tipo='entrada',
        latitud=None, longitud=None,
        geo_estado='sin_ubicacion', distancia_obra_metros=None,
        nota_ubicacion=None, precision_metros=None,
        fecha_laboral=date(2026, 9, 1),
        ocurrido_en=None,
    )
    mock_evento.query.filter.return_value.all.return_value = [entrada_ok, entrada_sin_gps]
    mock_vigentes.return_value = [entrada_ok, entrada_sin_gps]
    mock_user.query.filter.return_value.all.return_value = [
        SimpleNamespace(id=5, name='Ana', lastname='López'),
    ]

    data = fichajes_mapa_obra(1, SimpleNamespace(role='admin'), date(2026, 9, 1), date(2026, 9, 1))
    assert data is not None
    assert len(data['puntos']) == 1
    assert data['stats']['sin_gps'] == 1
    assert data['stats']['coincide'] == 1
