# tests/integration/test_vehicle_availability.py
#
# Coches libres: sin plan o conductor de ausencia cuentan igual.

from datetime import timedelta

from sqlalchemy import text

from app.models import (
    LEAVE_STATUS_APROBADA,
    AsignacionVehiculo,
    AusenciaPlanificada,
    Vehiculo,
)
from app.services.vehicle_availability_service import (
    MOTIVO_AUSENCIA,
    MOTIVO_SIN_PLAN,
    list_free_vehicle_stretches,
)
from app.utils.timezone_utils import today_local
import pytest


@pytest.fixture
def fleet_ctx(session, tenant_soltec, user_operario, user_admin):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    v = Vehiculo(
        nombre='Furgón test',
        matricula='TEST-LIBRE-1',
        active=True,
    )
    session.add(v)
    session.flush()
    yield session, v, user_operario
    session.execute(text('SET search_path TO public'))


class TestVehicleAvailability:

    def test_sin_plan_es_libre(self, fleet_ctx):
        session, vehiculo, _operario = fleet_ctx
        today = today_local()
        stretches = list_free_vehicle_stretches(
            fecha_desde=today,
            fecha_hasta=today + timedelta(days=2),
        )
        mine = [s for s in stretches if s['vehiculo_id'] == vehiculo.id]
        assert len(mine) == 1
        assert mine[0]['motivo'] == MOTIVO_SIN_PLAN
        assert mine[0]['dias'] == 3
        assert mine[0]['conductor_label'] is None
        assert mine[0]['abierto'] is True

    def test_asignacion_ocupa_el_coche(self, fleet_ctx):
        session, vehiculo, operario = fleet_ctx
        today = today_local()
        session.add(AsignacionVehiculo(
            vehiculo_id=vehiculo.id,
            user_id=operario.id,
            fecha=today,
        ))
        session.commit()

        stretches = list_free_vehicle_stretches(
            fecha_desde=today,
            fecha_hasta=today,
        )
        mine = [s for s in stretches if s['vehiculo_id'] == vehiculo.id]
        assert mine == []

    def test_ausencia_libera_el_coche_con_conductor(self, fleet_ctx):
        session, vehiculo, operario = fleet_ctx
        today = today_local()
        fin = today + timedelta(days=4)
        session.add(AsignacionVehiculo(
            vehiculo_id=vehiculo.id,
            user_id=operario.id,
            fecha=today + timedelta(days=1),
        ))
        session.add(AsignacionVehiculo(
            vehiculo_id=vehiculo.id,
            user_id=operario.id,
            fecha=today + timedelta(days=2),
        ))
        session.add(AusenciaPlanificada(
            user_id=operario.id,
            fecha_inicio=today + timedelta(days=1),
            fecha_fin=today + timedelta(days=2),
            tipo='Vacaciones',
            estado=LEAVE_STATUS_APROBADA,
            origen='manual',
        ))
        session.commit()

        stretches = list_free_vehicle_stretches(
            fecha_desde=today + timedelta(days=1),
            fecha_hasta=today + timedelta(days=2),
        )
        mine = [s for s in stretches if s['vehiculo_id'] == vehiculo.id]
        assert len(mine) == 1
        assert mine[0]['motivo'] == MOTIVO_AUSENCIA
        assert mine[0]['dias'] == 2
        assert mine[0]['conductor_id'] == operario.id
        assert 'Vacaciones' in mine[0]['ausencia_tipos']
        assert mine[0]['abierto'] is False

    def test_tras_ausencia_sigue_tramo_abierto(self, fleet_ctx):
        """Asignado en vacaciones → tramo ausencia + tramo sin plan en adelante."""
        session, vehiculo, operario = fleet_ctx
        today = today_local()
        # Hoy ocupado de verdad (sin ausencia)
        session.add(AsignacionVehiculo(
            vehiculo_id=vehiculo.id,
            user_id=operario.id,
            fecha=today,
        ))
        # Mañana y pasado: plan + vacaciones → libres por ausencia
        session.add(AsignacionVehiculo(
            vehiculo_id=vehiculo.id,
            user_id=operario.id,
            fecha=today + timedelta(days=1),
        ))
        session.add(AsignacionVehiculo(
            vehiculo_id=vehiculo.id,
            user_id=operario.id,
            fecha=today + timedelta(days=2),
        ))
        session.add(AusenciaPlanificada(
            user_id=operario.id,
            fecha_inicio=today + timedelta(days=1),
            fecha_fin=today + timedelta(days=2),
            tipo='Vacaciones',
            estado=LEAVE_STATUS_APROBADA,
            origen='manual',
        ))
        session.commit()

        stretches = list_free_vehicle_stretches(
            fecha_desde=today,
            fecha_hasta=today + timedelta(days=5),
        )
        mine = [s for s in stretches if s['vehiculo_id'] == vehiculo.id]
        assert len(mine) == 2
        assert mine[0]['motivo'] == MOTIVO_AUSENCIA
        assert mine[0]['fecha_inicio'] == today + timedelta(days=1)
        assert mine[0]['fecha_fin'] == today + timedelta(days=2)
        assert mine[0]['abierto'] is False
        # Orden por defecto: fecha_inicio → el tramo abierto va después
        assert mine[1]['motivo'] == MOTIVO_SIN_PLAN
        assert mine[1]['fecha_inicio'] == today + timedelta(days=3)
        assert mine[1]['abierto'] is True
