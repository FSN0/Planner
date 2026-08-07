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
