# tests/integration/test_gtm_fixes.py
#
# Regresión de los cierres GTM: libres=asignable con ausencia,
# hermanos de fichaje al resolver, PIN en onboarding.

from datetime import date, timedelta

from sqlalchemy import text

from app.models import (
    LEAVE_STATUS_APROBADA,
    AsignacionVehiculo,
    AusenciaPlanificada,
    RegistroFichaje,
    User,
    Vehiculo,
)
from app.services.onboarding_service import estado_onboarding
from app.services.pin_auth_service import asignar_pin
from app.services.vehicle_assignment_service import process_vehicle_assignment_action
from app.sync.routes import _cerrar_hermanos_placeholder
from app.utils.timezone_utils import today_local, utc_now


class TestVehicleLeaveFreeAssign:

    def test_asignar_sobre_conductor_de_vacaciones_sin_overwrite(
        self, session, tenant_soltec, user_admin, db,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        dia = today_local()

        pepe = User(
            email='pepe.leave@test.com',
            password_hash='x',
            role='operario',
            name='Pepe',
            lastname='Vacaciones',
            dni='90000001Z',
            active=True,
        )
        juan = User(
            email='juan.libre@test.com',
            password_hash='x',
            role='operario',
            name='Juan',
            lastname='Libre',
            dni='90000002Z',
            active=True,
        )
        coche = Vehiculo(nombre='Furgoneta test', matricula='GTM-001', active=True)
        session.add_all([pepe, juan, coche])
        session.flush()

        session.add(AsignacionVehiculo(
            vehiculo_id=coche.id, user_id=pepe.id, fecha=dia,
        ))
        session.add(AusenciaPlanificada(
            user_id=pepe.id,
            fecha_inicio=dia,
            fecha_fin=dia + timedelta(days=5),
            tipo='Vacaciones',
            estado=LEAVE_STATUS_APROBADA,
        ))
        session.commit()

        result = process_vehicle_assignment_action(
            user_admin, juan.id, coche.id, [dia],
            overwrite_mode='check', accion='ASIGNAR',
        )
        assert result.get('success') is True, result
        assert result.get('conflict') is not True

        av = AsignacionVehiculo.query.filter_by(vehiculo_id=coche.id, fecha=dia).first()
        assert av is not None
        assert av.user_id == juan.id


class TestFichajeHermanos:

    def test_anadir_cierra_placeholder_hermano(
        self, session, tenant_soltec, user_admin, db,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        dia = today_local()
        op = User(
            email='multi.obra@test.com',
            password_hash='x',
            role='operario',
            name='Multi',
            lastname='Obra',
            dni='90000003Z',
            active=True,
        )
        session.add(op)
        session.flush()

        seed = RegistroFichaje(
            user_id=op.id,
            fecha=dia,
            estado='Ausencia',
            obra_planificada_id=None,
            obra_real_id=None,
        )
        para = RegistroFichaje(
            user_id=op.id,
            fecha=dia,
            estado='Paracaidista',
            obra_planificada_id=None,
            obra_real_id=None,
        )
        conflicto = RegistroFichaje(
            user_id=op.id,
            fecha=dia,
            estado='Conflicto',
            obra_planificada_id=None,
            obra_real_id=None,
        )
        session.add_all([seed, para, conflicto])
        session.flush()

        para.estado = 'Resuelto_Asignado'
        para.resuelto_por_id = user_admin.id
        para.fecha_auditoria = utc_now()
        _cerrar_hermanos_placeholder(para, 'anadir')
        session.commit()

        seed = RegistroFichaje.query.get(seed.id)
        conflicto = RegistroFichaje.query.get(conflicto.id)
        assert seed.estado == 'Resuelto_Ignorado'
        assert conflicto.estado == 'Resuelto_Ignorado'
        assert seed.estado_antes_resolucion == 'Ausencia'
        assert conflicto.estado_antes_resolucion == 'Conflicto'


class TestOnboardingPin:

    def test_paso_gente_exige_pin(
        self, session, tenant_soltec, app, db,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        tenant_soltec.modulos_activos = {
            'onboarding': True,
            'registro_jornada': True,
            'fichaje_operario': True,
        }
        op = User(
            email='sin.pin@test.com',
            password_hash='x',
            role='operario',
            name='Sin',
            lastname='Pin',
            dni='90000004Z',
            active=True,
        )
        session.add(op)
        session.commit()

        with app.test_request_context():
            from flask import g
            g.current_tenant = tenant_soltec
            estado = estado_onboarding()
            antes = estado['con_pin']

            asignar_pin(op, '1234')
            session.commit()
            estado2 = estado_onboarding()
            assert estado2['con_pin'] == antes + 1
