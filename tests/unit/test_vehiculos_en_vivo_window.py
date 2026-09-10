"""Sync automático de viajes: siempre ventana de N días, no solo hoy."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock


def test_run_vehiculos_en_vivo_uses_retro_days_window(monkeypatch):
    from app.services import vehicle_sync_service as vs

    hoy = date(2026, 9, 10)
    monkeypatch.setattr(vs, 'today_local', lambda: hoy)
    monkeypatch.setattr(
        'app.services.sync_config_service.SyncConfigService.get_config',
        lambda: {'vehiculos_retro_days': 14},
    )

    calls = {}

    def fake_apply_diff(**kwargs):
        return {'ok': True}

    def fake_sync_odometros(**kwargs):
        calls['kwargs'] = kwargs
        return {'registros': 1}

    monkeypatch.setattr(vs, 'apply_diff', fake_apply_diff)
    monkeypatch.setattr(vs, 'sync_odometros', fake_sync_odometros)

    vs.run_vehiculos_en_vivo(modo='Automático')

    assert calls['kwargs']['fecha_desde'] == hoy - timedelta(days=14)
    assert calls['kwargs']['fecha_hasta'] == hoy
    assert calls['kwargs']['modo'] == 'Automático'
