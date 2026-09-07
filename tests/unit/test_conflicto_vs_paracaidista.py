"""
Matriz de fichaje de entrada (PWA = Odoo).

- hecho en la obra fichada → Correcto
- hecho en otra obra hoy → Conflicto
- sin hecho, ficha en su casa → Correcto_Automatico
- sin hecho ni casa → primer fichaje (auto o Paracaidista)
- sin hecho, ficha fuera de casa → Cambio_Tajo
"""
from app.services.inercia_service import (
    ESTADO_CAMBIO_TAJO,
    ESTADO_CONFLICTO,
    ESTADO_CORRECTO,
    ESTADO_INERCIA,
    ESTADO_PARACAIDISTA,
    clasificar_entrada_fichaje,
)


def clasificar_estado_entrada(
    *,
    planificado_en_obra_fichada,
    planificado_en_otra_obra,
    casa_obra_id=None,
    obra_fichada_id=1,
    aceptar_primer_fichaje=True,
):
    otras = [2] if planificado_en_otra_obra else []
    if planificado_en_obra_fichada:
        obra_fichada_id = 1
        otras = []
    return clasificar_entrada_fichaje(
        obra_fichada_id=obra_fichada_id,
        planificado_en_obra_fichada=planificado_en_obra_fichada,
        otras_obras_planificadas_ids=otras,
        casa_obra_id=casa_obra_id,
        aceptar_primer_fichaje=aceptar_primer_fichaje,
    ).estado


def test_plan_en_obra_fichada_es_correcto():
    assert clasificar_estado_entrada(
        planificado_en_obra_fichada=True,
        planificado_en_otra_obra=False,
    ) == ESTADO_CORRECTO


def test_plan_en_obra_a_fichaje_en_obra_b_es_conflicto():
    assert clasificar_estado_entrada(
        planificado_en_obra_fichada=False,
        planificado_en_otra_obra=True,
        obra_fichada_id=2,
        casa_obra_id=1,
    ) == ESTADO_CONFLICTO


def test_sin_plan_con_casa_es_inercia():
    assert clasificar_estado_entrada(
        planificado_en_obra_fichada=False,
        planificado_en_otra_obra=False,
        casa_obra_id=1,
        obra_fichada_id=1,
    ) == ESTADO_INERCIA


def test_sin_plan_fuera_de_casa_es_cambio_tajo():
    assert clasificar_estado_entrada(
        planificado_en_obra_fichada=False,
        planificado_en_otra_obra=False,
        casa_obra_id=1,
        obra_fichada_id=2,
    ) == ESTADO_CAMBIO_TAJO


def test_sin_plan_ni_casa_es_paracaidista_si_no_se_acepta_el_primero():
    assert clasificar_estado_entrada(
        planificado_en_obra_fichada=False,
        planificado_en_otra_obra=False,
        casa_obra_id=None,
        aceptar_primer_fichaje=False,
    ) == ESTADO_PARACAIDISTA


def test_plan_exacto_gana_aunque_haya_otra_obra():
    assert clasificar_estado_entrada(
        planificado_en_obra_fichada=True,
        planificado_en_otra_obra=True,
    ) == ESTADO_CORRECTO
