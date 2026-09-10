"""Sync viajes: un sync estrecho no debe borrar/reescribir días fuera de ventana."""
from datetime import date, timedelta
from types import SimpleNamespace


class _CmpCol:
    """Stub de columna SQLAlchemy que soporta >= / <= y guarda el valor comparado."""

    def __init__(self, bag, key):
        self._bag = bag
        self._key = key

    def __ge__(self, other):
        self._bag[f'{self._key}_ge'] = other
        return True

    def __le__(self, other):
        self._bag[f'{self._key}_le'] = other
        return True


def test_sync_odometros_clips_trip_days_to_requested_window(monkeypatch):
    """Ventana solo-hoy + viaje ayer→hoy: purge y registros no tocan ayer."""
    from app.services import vehicle_sync_service as vs

    hoy = date(2026, 9, 10)
    ayer = hoy - timedelta(days=1)

    monkeypatch.setattr(vs, 'today_local', lambda: hoy)
    monkeypatch.setattr(vs, 'utc_now', lambda: hoy)

    class FakeAdapter:
        def get_viajes_diarios(self, fecha=None, fecha_hasta=None):
            assert fecha == hoy.isoformat()
            assert fecha_hasta == hoy.isoformat()
            return [{
                'odoo_vehicle_id': 99,
                'odoo_vehicle_name': 'Furgoneta',
                'odoo_viaje_id': 1,
                'code': 'V1',
                'date_start': ayer.isoformat(),
                'date_end': hoy.isoformat(),
                'date_registro': hoy.isoformat(),
                'km_start': 100,
                'km_end': 150,
                'qty_km': 50,
                'driver_partner_id': None,
                'driver_name': None,
                'obra_origen': None,
                'obra_destino': None,
            }]

    monkeypatch.setattr(vs, 'get_sync_adapter', lambda: FakeAdapter())

    veh = SimpleNamespace(
        id=7, name='Furgoneta', external_ids={'odoo': '99'},
        odoo_odometer_date=None, odoo_odometer_value=None,
        odoo_driver_partner_id=None, odoo_driver_name=None,
    )
    monkeypatch.setattr(vs, '_build_vehicle_indexes', lambda: ({'99': veh}, {}))
    monkeypatch.setattr(
        vs, '_ensure_vehiculo_for_viaje',
        lambda viaje, by_odoo, by_nombre: (veh, 'ok'),
    )
    monkeypatch.setattr(vs, '_build_user_indexes', lambda: ({}, {}))

    purge = {}
    created = []

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def delete(self, synchronize_session=False):
            return 0

        def all(self):
            return []

    class RO:
        query = _Query()
        fecha = _CmpCol(purge, 'ro')

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            created.append(self)

    class AV:
        query = _Query()
        fecha = _CmpCol(purge, 'av')
        vehiculo_id = SimpleNamespace()

    monkeypatch.setattr(vs, 'RegistroOdometro', RO)
    monkeypatch.setattr(vs, 'AsignacionVehiculo', AV)
    monkeypatch.setattr(vs, 'SyncLog', lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(vs.db.session, 'add', lambda obj: None)
    monkeypatch.setattr(vs.db.session, 'commit', lambda: None)
    monkeypatch.setattr(vs.db.session, 'flush', lambda: None)

    result = vs.sync_odometros(
        fecha_desde=hoy,
        fecha_hasta=hoy,
        modo='Automático',
        limpiar_rango=True,
    )

    # 1) Ventana solo-hoy en el resultado
    assert result['desde'] == hoy.isoformat()
    assert result['hasta'] == hoy.isoformat()

    # 2) Viaje ayer→hoy aplicado, pero solo el día de hoy en dates_seen
    assert result['viajes_aplicados'] == 1
    assert result['min_dia'] == hoy.isoformat()
    assert result['max_dia'] == hoy.isoformat()

    # 3) Purge/delete no incluye ayer
    assert purge.get('ro_ge') == hoy
    assert purge.get('ro_le') == hoy
    assert ayer not in (purge.get('ro_ge'), purge.get('ro_le'))

    # Registros creados solo con fecha de hoy
    fechas = [r.fecha for r in created if getattr(r, 'fecha', None) is not None]
    assert fechas
    assert all(f == hoy for f in fechas)
    assert ayer not in fechas
