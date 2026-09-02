"""Traslado entre obras en planificador: no debe conflictuar con la obra origen."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.asignaciones import _desasignar_obra_origen_traslado


def test_traslado_quita_obra_origen_antes_de_asignar_en_destino():
    actor = SimpleNamespace(id=1, role='admin', name='Admin')
    worker_id = 10
    old_obra_id = 100
    day = date.today() + timedelta(days=1)

    asig_origen = object()
    filter_by = MagicMock()
    filter_by.first.return_value = asig_origen

    with patch('app.api.asignaciones.Asignacion') as Asig, \
         patch('app.api.asignaciones.CoreAssignmentService') as Core, \
         patch('app.api.asignaciones.update_solicitudes_for_assignment') as upd, \
         patch('app.api.asignaciones.User') as UserM, \
         patch('app.api.asignaciones.notificar_movimiento_admin_a_jo') as notify, \
         patch('app.api.asignaciones.db') as mock_db:
        Asig.query.filter_by.return_value = filter_by
        UserM.query.get.return_value = SimpleNamespace(name='Rafael', lastname='Test')

        hecho, msg = _desasignar_obra_origen_traslado(actor, worker_id, old_obra_id, [day])

        assert hecho is True
        assert msg == ''
        Core.desasignar.assert_called_once_with(
            worker_id, old_obra_id, day, actor.id,
            "Planificación Manual", "Traslado a otra obra desde planificador.",
            registrar_log=False,
        )
        Core.registrar_log_rango.assert_called_once()
        upd.assert_called_once_with(old_obra_id, worker_id, day, resolved_by_id=actor.id)
        notify.assert_called_once()
        mock_db.session.commit.assert_called_once()


def test_traslado_sin_asignacion_en_origen_no_op():
    actor = SimpleNamespace(id=1, role='admin', name='Admin')
    day = date.today() + timedelta(days=1)

    filter_by = MagicMock()
    filter_by.first.return_value = None

    with patch('app.api.asignaciones.Asignacion') as Asig, \
         patch('app.api.asignaciones.CoreAssignmentService') as Core:
        Asig.query.filter_by.return_value = filter_by

        hecho, msg = _desasignar_obra_origen_traslado(actor, 10, 100, [day])

        assert hecho is False
        assert msg == ''
        Core.desasignar.assert_not_called()
