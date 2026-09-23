"""Regresión: traslado/overwrite en planificador no debe hacer no-op silencioso."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.assignment_service import _handle_direct_assignment


@pytest.fixture
def actor():
    return SimpleNamespace(id=1, role='admin', name='Admin')


@pytest.fixture
def worker():
    return SimpleNamespace(id=10, company_id=1, name='Antonio', lastname='Hernandez')


@pytest.fixture
def obra_a():
    return SimpleNamespace(id=100, nombre='Reforma')


@pytest.fixture
def obra_b():
    return SimpleNamespace(id=200, nombre='Polideportivo')


def test_overwrite_clears_other_obras_even_if_already_on_target(actor, worker, obra_a, obra_b):
    """Si ya está en destino pero también en otra obra, overwrite debe limpiar la otra."""
    day = date.today() + timedelta(days=1)

    filter_by_result = MagicMock()
    filter_by_result.first.return_value = object()  # already on target
    filter_chain = MagicMock()
    filter_chain.with_entities.return_value.all.return_value = [
        (worker.id, obra_b.id, day),
    ]

    with patch('app.services.assignment_service.Asignacion') as Asig, \
         patch('app.services.assignment_service.CoreAssignmentService') as Core, \
         patch('app.services.assignment_service.update_solicitudes_for_assignment'), \
         patch('app.services.assignment_service.db') as db:
        Asig.query.filter_by.return_value = filter_by_result
        Asig.query.filter.return_value = filter_chain

        result = _handle_direct_assignment(
            actor, worker, obra_a, [day], overwrite=True
        )

        Core.desasignar.assert_called_once()
        assert result['success'] is True
        assert not result.get('noop')
        db.session.commit.assert_called()


def test_overwrite_noop_when_nothing_to_do(actor, worker, obra_a):
    day = date.today() + timedelta(days=1)

    filter_by_result = MagicMock()
    filter_by_result.first.return_value = object()
    filter_chain = MagicMock()
    filter_chain.with_entities.return_value.all.return_value = []

    with patch('app.services.assignment_service.Asignacion') as Asig, \
         patch('app.services.assignment_service.CoreAssignmentService'), \
         patch('app.services.assignment_service.update_solicitudes_for_assignment'), \
         patch('app.services.assignment_service.db'):
        Asig.query.filter_by.return_value = filter_by_result
        Asig.query.filter.return_value = filter_chain

        result = _handle_direct_assignment(
            actor, worker, obra_a, [day], overwrite=True
        )

        assert result.get('noop') is True
        assert result.get('unchanged') is True


def test_check_mode_returns_conflict_when_extending_onto_other_obra(actor, worker, obra_a, obra_b):
    """Estirar un tramo sobre días de otra obra debe devolver conflicto, no overwrite."""
    from app.models import ROLE_ADMIN
    from app.services.assignment_service import process_assignment_action

    day = date.today() + timedelta(days=1)
    actor.role = ROLE_ADMIN
    other_asig = SimpleNamespace(obra_id=obra_b.id)

    filter_by = MagicMock()
    filter_by.all.return_value = [other_asig]

    with patch('app.services.assignment_service.User') as UserM, \
         patch('app.services.assignment_service.Obra') as ObraM, \
         patch('app.services.assignment_service.Asignacion') as Asig, \
         patch('app.services.leave_service.user_has_approved_leave', return_value=False), \
         patch('app.services.assign_mode_service.user_assigns_direct', return_value=True), \
         patch('app.services.panel_scope_service.planning_acts_as_office', return_value=True):
        UserM.query.get.return_value = worker
        ObraM.query.get.side_effect = lambda oid: obra_a if oid == obra_a.id else obra_b
        Asig.query.filter_by.return_value = filter_by

        result = process_assignment_action(
            actor_user=actor,
            worker_id=worker.id,
            target_obra_id=obra_a.id,
            date_list=[day],
            mode='check',
        )

    assert result.get('success') is False
    assert result.get('conflict') is True
    assert result.get('conflict_type') == 'admin_hard'
    assert obra_b.nombre in (result.get('conflict_details') or {})


def test_overwrite_without_conflict_resolved_is_coerced_to_check():
    from app.api.asignaciones import _assignment_mode_from_payload

    assert _assignment_mode_from_payload({'overwrite_mode': 'overwrite'}) == 'check'
    assert _assignment_mode_from_payload({
        'overwrite_mode': 'overwrite',
        'conflict_resolved': True,
    }) == 'overwrite'
    assert _assignment_mode_from_payload({'overwrite_mode': 'check'}) == 'check'
