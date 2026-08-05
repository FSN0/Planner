"""
Conflicto vs Paracaidista al fichar entrada.

Regla (misma que fichaje_operario_service / sync Odoo):
- plan en la obra fichada → Correcto
- plan en otra obra hoy → Conflicto (desviación del plan)
- sin plan en todo el día → Paracaidista (sin planificar)
"""


def clasificar_estado_entrada(*, planificado_en_obra_fichada, planificado_en_otra_obra):
    """
    Clasifica el estado de auditoría tras una entrada física.

    Espejo deliberado de la lógica en fichaje_operario_service.fichar
    (ya_planificado / plan_otro) para documentar la regla sin levantar
    el libro de eventos completo.
    """
    if planificado_en_obra_fichada:
        return 'Correcto'
    if planificado_en_otra_obra:
        return 'Conflicto'
    return 'Paracaidista'


def test_plan_en_obra_fichada_es_correcto():
    assert clasificar_estado_entrada(
        planificado_en_obra_fichada=True,
        planificado_en_otra_obra=False,
    ) == 'Correcto'


def test_plan_en_obra_a_fichaje_en_obra_b_es_conflicto():
    """Punching obra B with a plan on obra A is Conflicto, not Paracaidista."""
    assert clasificar_estado_entrada(
        planificado_en_obra_fichada=False,
        planificado_en_otra_obra=True,
    ) == 'Conflicto'


def test_sin_plan_es_paracaidista():
    assert clasificar_estado_entrada(
        planificado_en_obra_fichada=False,
        planificado_en_otra_obra=False,
    ) == 'Paracaidista'


def test_plan_exacto_gana_aunque_haya_otra_obra():
    """Si fichó donde estaba planificado, no es desviación."""
    assert clasificar_estado_entrada(
        planificado_en_obra_fichada=True,
        planificado_en_otra_obra=True,
    ) == 'Correcto'
