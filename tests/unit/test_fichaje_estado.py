"""Tests unitarios de agregación de estado de fichaje (pelotitas)."""
from app.services.fichaje_estado_service import (
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
    assert color_fichaje_agregado(['Correcto', 'Resuelto_Asignado']) == '#10b981'


def test_paracaidista_gana_sobre_correcto():
    assert estado_fichaje_agregado(['Correcto', 'Paracaidista']) == 'Paracaidista'
    assert color_fichaje_agregado(['Correcto', 'Paracaidista']) == '#ef4444'


def test_ausencia_pendiente_es_naranja():
    assert estado_fichaje_agregado(['Correcto', 'Ausencia']) == 'Ausencia'
    assert color_fichaje_agregado(['Correcto', 'Ausencia']) == '#f59e0b'


def test_todo_resuelto_es_verde():
    assert color_fichaje_agregado(
        ['Resuelto_Asignado', 'Resuelto_Ignorado']
    ) == '#10b981'


def test_vacio_sin_registro():
    assert estado_fichaje_agregado([]) == 'Sin_Registro'
    assert color_fichaje_agregado([]) == '#94a3b8'
