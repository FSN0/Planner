"""Aceptar un fichaje Paracaidista con «Añadir» atribuye el cuadrante al auditor."""

import json
from datetime import datetime, time

from sqlalchemy import text

from app.models import Asignacion, RegistroFichaje, SystemLog
from app.services.core_assignment_service import CoreAssignmentService
from app.services.person_day_timeline_service import build_person_day_timeline
from app.utils.timezone_utils import today_local, utc_now


def _activar_auditoria(session, tenant):
    mods = dict(tenant.modulos_activos or {})
    mods['odoo'] = True
    tenant.modulos_activos = mods
    session.add(tenant)
    session.commit()


def _paracaidista(session, user, obra, dia):
    registro = RegistroFichaje(
        user_id=user.id,
        fecha=dia,
        estado='Paracaidista',
        obra_planificada_id=None,
        obra_real_id=obra.id,
        check_in=datetime.combine(dia, time(6, 49)),
    )
    session.add(registro)
    session.commit()
    return registro


class TestAsignarConservaAutor:

    def test_contexto_auto_no_borra_al_auditor(
        self, session, tenant_soltec, user_admin, user_operario, obra_activa,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        dia = today_local()
        CoreAssignmentService.asignar(
            user_operario.id, obra_activa.id, dia,
            user_admin.id, 'Actualización de Cuadrante (Auto)',
        )
        session.commit()

        log = SystemLog.query.filter_by(
            category='planificacion',
            target_user_id=user_operario.id,
            target_date=dia,
        ).first()
        assert log is not None
        assert log.user_id == user_admin.id

    def test_auto_fichaje_fisico_sigue_siendo_sistema(
        self, session, tenant_soltec, user_operario, obra_activa,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        dia = today_local()
        CoreAssignmentService.asignar(
            user_operario.id, obra_activa.id, dia,
            None, 'Auto-asignación por Fichaje Físico',
        )
        session.commit()

        log = SystemLog.query.filter_by(
            category='planificacion',
            target_user_id=user_operario.id,
            target_date=dia,
        ).first()
        assert log is not None
        assert log.user_id is None


class TestResolverAnadirAutor:

    def test_anadir_paracaidista_loguea_al_admin(
        self, session, tenant_soltec, user_admin, user_operario, obra_activa,
        authenticated_client,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        _activar_auditoria(session, tenant_soltec)
        dia = today_local()
        registro = _paracaidista(session, user_operario, obra_activa, dia)

        response = authenticated_client.post(
            '/sync/auditoria/resolver',
            data=json.dumps({'registro_id': registro.id, 'accion': 'anadir'}),
            content_type='application/json',
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        data = json.loads(response.data)
        assert data.get('success') is True, data

        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        asig = Asignacion.query.filter_by(
            user_id=user_operario.id, obra_id=obra_activa.id, fecha=dia,
        ).first()
        assert asig is not None

        plan_log = SystemLog.query.filter_by(
            category='planificacion',
            target_user_id=user_operario.id,
            target_date=dia,
        ).first()
        assert plan_log is not None
        assert plan_log.user_id == user_admin.id
        assert plan_log.action == 'Resolución de Fichaje: Añadir'
        assert 'Actualización de Cuadrante (Auto)' not in (plan_log.action or '')

        res_log = SystemLog.query.filter_by(
            category='fichajes',
            target_user_id=user_operario.id,
            target_date=dia,
        ).first()
        assert res_log is not None
        assert res_log.user_id == user_admin.id
        assert res_log.action == 'Resolución de Fichaje: Añadir'


class TestTimelineLegacyAutoAnadir:

    def test_log_auto_sin_autor_toma_al_auditor_hermano(
        self, session, tenant_soltec, user_admin, user_operario, obra_activa, app,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        dia = today_local()
        ahora = utc_now()
        session.add(SystemLog(
            timestamp=ahora,
            user_id=None,
            category='planificacion',
            action='Actualización de Cuadrante (Auto)',
            detail=(
                f"Asignado {user_operario.name} {user_operario.lastname} "
                f"→ '{obra_activa.codigo} — {obra_activa.nombre}' "
                f"({dia.strftime('%d/%m/%Y')})."
            ),
            target_user_id=user_operario.id,
            target_date=dia,
        ))
        session.add(SystemLog(
            timestamp=ahora,
            user_id=user_admin.id,
            category='fichajes',
            action='Resolución de Fichaje: Añadir',
            detail=f"Se acepta el fichaje sin planificar en '{obra_activa.codigo}'.",
            target_user_id=user_operario.id,
            target_date=dia,
        ))
        session.commit()

        with app.test_request_context(base_url='http://soltec.localhost:5000'):
            timeline = build_person_day_timeline(user_operario.id, dia)

        hitos = timeline['hitos']
        plan = next(
            (h for h in hitos if 'Asignado' in (h.get('descripcion') or '')),
            None,
        )
        assert plan is not None
        assert user_admin.name in plan['autor']
        assert user_admin.lastname in plan['autor']
        assert plan['actor_user_id'] == user_admin.id
        assert 'Añadir' in plan['titulo']
        assert plan.get('actor_is_system') is False
