"""Tests unitarios de agregación de estado de fichaje (pelotitas)."""
from app.services.fichaje_estado_service import (
    COLOR_GRIS,
    COLOR_NARANJA,
    COLOR_ROJO,
    COLOR_VERDE,
    COLOR_VIOLETA,
    color_fichaje_agregado,
    estado_fichaje_agregado,
)


def test_multi_obra_correcto_mas_resuelto_es_verde():
    estado = estado_fichaje_agregado(['Correcto', 'Resuelto_Asignado'])
    assert estado in (
        'Correcto',
        'Resuelto_Asignado',
        'Correcto_Automatico',
    )
    assert color_fichaje_agregado(['Correcto', 'Resuelto_Asignado']) == COLOR_VERDE


def test_paracaidista_gana_sobre_correcto():
    assert estado_fichaje_agregado(['Correcto', 'Paracaidista']) == 'Paracaidista'
    assert color_fichaje_agregado(['Correcto', 'Paracaidista']) == COLOR_ROJO


def test_ausencia_pendiente_es_naranja():
    assert estado_fichaje_agregado(['Correcto', 'Ausencia']) == 'Ausencia'
    assert color_fichaje_agregado(['Correcto', 'Ausencia']) == COLOR_NARANJA


def test_conflicto_es_rojo():
    assert estado_fichaje_agregado(['Correcto', 'Conflicto']) == 'Conflicto'
    assert color_fichaje_agregado(['Correcto', 'Conflicto']) == COLOR_ROJO


def test_resuelto_tras_cerrar_hermanos_es_verde():
    assert color_fichaje_agregado(
        ['Resuelto_Asignado', 'Resuelto_Ignorado']
    ) == COLOR_VERDE


def test_vacio_sin_registro():
    assert estado_fichaje_agregado([]) == 'Sin_Registro'
    assert color_fichaje_agregado([]) == COLOR_GRIS


def test_correcto_mas_sin_registro_es_verde():
    """Multi-obra: ficha en A, semilla B no deja la pelotita naranja."""
    assert estado_fichaje_agregado(['Correcto', 'Sin_Registro']) == 'Correcto'
    assert color_fichaje_agregado(['Correcto', 'Sin_Registro']) == COLOR_VERDE


def test_solo_sin_registro_es_gris():
    assert estado_fichaje_agregado(['Sin_Registro']) == 'Sin_Registro'
    assert color_fichaje_agregado(['Sin_Registro']) == COLOR_GRIS


def test_sobreescrito_rrhh_es_violeta():
    assert estado_fichaje_agregado(['Sobreescrito_RRHH', 'Correcto']) == 'Sobreescrito_RRHH'
    assert color_fichaje_agregado(['Sobreescrito_RRHH', 'Correcto']) == COLOR_VIOLETA


def test_sobreescrito_mas_sin_registro_es_violeta():
    assert color_fichaje_agregado(
        ['Sobreescrito_RRHH', 'Sin_Registro']
    ) == COLOR_VIOLETA
