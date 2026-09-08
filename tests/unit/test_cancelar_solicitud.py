"""Cancelación de solicitud por el autor."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.solicitud_service import cancelar_solicitud_por_autor


def test_cancelar_solicitud_autor_ok(monkeypatch):
    monkeypatch.setattr(
        'app.services.solicitud_service.db.session.commit', lambda: None
    )
    monkeypatch.setattr(
        'app.services.solicitud_service.utc_now',
        lambda: '2026-09-08T10:00:00',
    )
    solicitud = SimpleNamespace(
        requested_by_id=7,
        estado='PENDIENTE',
        resolved_at=None,
        resolved_by_id=None,
    )
    actor = SimpleNamespace(id=7)
    msg = cancelar_solicitud_por_autor(solicitud, actor)
    assert solicitud.estado == 'CANCELADA'
    assert solicitud.resolved_by_id == 7
    assert 'cancelada' in msg.lower()


def test_cancelar_solicitud_no_autor_raises():
    solicitud = SimpleNamespace(requested_by_id=7, estado='PENDIENTE')
    actor = SimpleNamespace(id=99)
    with pytest.raises(ValueError):
        cancelar_solicitud_por_autor(solicitud, actor)


def test_cancelar_solicitud_ya_cerrada_raises():
    solicitud = SimpleNamespace(requested_by_id=7, estado='CUMPLIDA')
    actor = SimpleNamespace(id=7)
    with pytest.raises(ValueError):
        cancelar_solicitud_por_autor(solicitud, actor)
