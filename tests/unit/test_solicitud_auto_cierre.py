"""Autocierre de solicitudes por cambios de cuadrante."""
import json
from datetime import date
from types import SimpleNamespace

from app.services.solicitud_service import (
    _mark_auto_cumplida,
    _clear_auto_cierre_marker,
    get_solicitud_auto_cierre_texto,
    build_comentarios_config,
)


def test_mark_auto_cumplida_deja_rastro(monkeypatch):
    class _Now:
        def isoformat(self, timespec='seconds'):
            return '2026-10-01T12:00:00'

    monkeypatch.setattr(
        'app.services.solicitud_service.utc_now',
        lambda: _Now(),
    )

    class _Q:
        @staticmethod
        def get(_id):
            return SimpleNamespace(id=5, name='Ana', lastname='López')

    class _User:
        query = _Q()

    monkeypatch.setattr('app.services.solicitud_service.User', _User)

    sol = SimpleNamespace(
        estado='EN_PROCESO',
        tipo='CONCRETA',
        auto_fulfilled=False,
        resolved_at=None,
        resolved_by_id=None,
        comentarios=build_comentarios_config([date(2026, 10, 1)]),
        cantidad_solicitada=1,
        cantidad_cubierta=0,
    )
    _mark_auto_cumplida(sol, resolved_by_id=5)
    assert sol.estado == 'CUMPLIDA'
    assert sol.auto_fulfilled is True
    assert sol.resolved_by_id == 5
    cfg = json.loads(sol.comentarios)
    assert cfg['auto_cierre']['motivo'] == 'asignaciones_cuadrante'
    assert cfg['auto_cierre']['actor_id'] == 5
    assert cfg['auto_cierre']['estado'] == 'CUMPLIDA'
    txt = get_solicitud_auto_cierre_texto(sol)
    assert txt and 'Ana' in txt
    assert 'cubierta en cuadrante' in txt


def test_mark_cumplida_desde_solicitud_no_es_auto(monkeypatch):
    class _Now:
        def isoformat(self, timespec='seconds'):
            return '2026-10-04T10:36:05'

    monkeypatch.setattr(
        'app.services.solicitud_service.utc_now',
        lambda: _Now(),
    )

    class _Q:
        @staticmethod
        def get(_id):
            return SimpleNamespace(id=7, name='paco', lastname='navarrp')

    class _User:
        query = _Q()

    monkeypatch.setattr('app.services.solicitud_service.User', _User)

    from app.services.solicitud_service import (
        _mark_auto_cumplida,
        solicitud_cerrada_desde_solicitud,
    )

    sol = SimpleNamespace(
        estado='EN_PROCESO',
        tipo='GENERICA',
        auto_fulfilled=False,
        resolved_at=None,
        resolved_by_id=None,
        comentarios=build_comentarios_config([date(2026, 10, 4)]),
        cantidad_solicitada=2,
        cantidad_cubierta=0,
    )
    _mark_auto_cumplida(sol, resolved_by_id=7, automatico=False)
    assert sol.estado == 'CUMPLIDA'
    assert sol.auto_fulfilled is False
    cfg = json.loads(sol.comentarios)
    assert 'auto_cierre' not in cfg
    assert cfg['cierre']['motivo'] == 'asignacion_desde_solicitud'
    assert solicitud_cerrada_desde_solicitud(sol) is True
    txt = get_solicitud_auto_cierre_texto(sol)
    assert txt and 'asignada desde la solicitud' in txt
    assert 'paco' in txt


def test_clear_auto_cierre_marker():
    sol = SimpleNamespace(
        auto_fulfilled=True,
        comentarios=json.dumps({
            'dates': ['2026-10-01'],
            'original_dates': ['2026-10-01'],
            'auto_cierre': {'at': 'x', 'motivo': 'asignaciones_cuadrante'},
        }),
    )
    _clear_auto_cierre_marker(sol)
    assert sol.auto_fulfilled is False
    cfg = json.loads(sol.comentarios)
    assert 'auto_cierre' not in cfg


def test_desasignar_sin_dias_validos_no_autocierra(monkeypatch):
    """Regresión: cobertura 0 con 0 días válidos no debe marcar CUMPLIDA."""
    from app.services.solicitud_service import _recalculate_solicitud_coverage

    sol = SimpleNamespace(
        tipo='CONCRETA',
        accion='DESASIGNAR',
        estado='PENDIENTE',
        obra_id=1,
        empleado_id=9,
        cantidad_solicitada=1,
        cantidad_cubierta=0,
        auto_fulfilled=False,
        resolved_at=None,
        resolved_by_id=None,
        comentarios='{}',
        fecha_inicio=date(2026, 10, 1),
        fecha_fin=date(2026, 10, 1),
    )
    monkeypatch.setattr(
        'app.services.solicitud_service.get_solicitud_valid_dates',
        lambda _s: [],
    )
    monkeypatch.setattr(
        'app.services.solicitud_service.db.session.add',
        lambda _obj: None,
    )
    _recalculate_solicitud_coverage(sol, resolved_by_id=1)
    assert sol.estado == 'PENDIENTE'
    assert sol.auto_fulfilled is False
