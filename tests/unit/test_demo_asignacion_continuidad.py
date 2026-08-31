from datetime import date, timedelta

from app.services.demo_data_service import (
    _EstadoContinuidadAsignacion,
    _iter_dias_laborables_planificacion,
)


class _Obra:
    def __init__(self, oid):
        self.id = oid


def test_iter_dias_planificacion_simetrico():
    hoy = date(2026, 8, 31)  # lunes
    dias = [d for d, _ in _iter_dias_laborables_planificacion(hoy, 2)]
    assert dias[0] == date(2026, 8, 27)
    assert dias[-1] == date(2026, 9, 2)
    assert hoy in dias


def test_continuidad_prefiere_misma_obra():
    obras = [_Obra(1), _Obra(2), _Obra(3)]
    estado = _EstadoContinuidadAsignacion(obras)
    dia = date(2026, 8, 10)
    user_id = 99

    primera = None
    for _ in range(20):
        obra = estado.elegir(user_id, dia, prob_trabaja=1.0)
        if obra:
            primera = obra
            estado.confirmar(user_id, obra, dia)
            break
    assert primera is not None

    mismas = 0
    for offset in range(1, 6):
        dia_sig = dia + timedelta(days=offset)
        obra = estado.elegir(user_id, dia_sig, prob_trabaja=1.0)
        if obra and obra.id == primera.id:
            mismas += 1
            estado.confirmar(user_id, obra, dia_sig)
    assert mismas >= 3
