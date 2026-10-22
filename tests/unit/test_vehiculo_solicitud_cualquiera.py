"""Solicitud de vehículo «CUALQUIERA» (sin coche concreto)."""
from datetime import date

import pytest
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app.models import ROLE_ADMIN, SolicitudVehiculo, User, Vehiculo
from app.services.vehicle_assignment_service import _is_vehiculo_cualquiera
from app.services.vehicle_solicitud_service import VehicleSolicitudService


def test_is_vehiculo_cualquiera():
    assert _is_vehiculo_cualquiera('CUALQUIERA') is True
    assert _is_vehiculo_cualquiera('cualquiera') is True
    assert _is_vehiculo_cualquiera(None) is True
    assert _is_vehiculo_cualquiera(7) is False


def test_resolve_cualquiera_exige_vehiculo(session, tenant_soltec, monkeypatch):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    monkeypatch.setattr(
        'app.services.vehicle_solicitud_service.can_resolve_solicitudes_flota',
        lambda _u: True,
    )
    monkeypatch.setattr(
        'app.services.vehicle_solicitud_service.notificar_resolucion_solicitud_vehiculo',
        lambda *a, **k: None,
    )
    # Evita commit real (rompe nested txn del fixture de tests).
    monkeypatch.setattr(
        'app.services.vehicle_solicitud_service.db.session.commit',
        lambda: None,
    )

    admin = User(
        name='Admin', lastname='Test', email='admin-cualq3@test.local',
        dni='CQ7777777G', role=ROLE_ADMIN, active=True, is_deleted=False,
        password_hash=generate_password_hash('x'),
    )
    op = User(
        name='Op2', lastname='Test', email='op2-cualq3@test.local',
        dni='CQ8888888H', role='operario', active=True, is_deleted=False,
        password_hash=generate_password_hash('x'),
    )
    veh = Vehiculo(nombre='Furgón', matricula='0002CCC', active=True)
    session.add_all([admin, op, veh])
    session.flush()

    hoy = date.today()
    sol = SolicitudVehiculo(
        accion='ASIGNAR',
        requested_by_id=admin.id,
        empleado_id=op.id,
        vehiculo_id=None,
        fecha_inicio=hoy,
        fecha_fin=hoy,
        estado='PENDIENTE',
    )
    session.add(sol)
    session.flush()

    with pytest.raises(ValueError, match='cualquier'):
        VehicleSolicitudService.resolve(sol, 'aceptar', admin)

    msg = VehicleSolicitudService.resolve(
        sol, 'aceptar', admin, vehiculo_id=veh.id,
    )
    assert 'aceptada' in msg.lower()
    assert sol.vehiculo_id == veh.id
    assert sol.estado == 'CUMPLIDA'
