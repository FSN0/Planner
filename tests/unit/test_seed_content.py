from sqlalchemy import text

from app.models import Obra, ROLE_OPERARIO, Solicitud, SystemLog, User
from app.services.config_service import get_tenant_config
from app.services.demo_data_service import (
    CONFIG_DEMO_CLEARED,
    DEMO_EMAIL_SUFFIX,
    DEMO_MATRICULA_PREFIX,
    DEMO_OBRA_PREFIX,
    cantidades_desde_formulario,
    demo_activa,
    demo_cantidades,
)
from app.services.superadmin_ops_service import seed_tenant_content
from app.services.tenant_service import provision_new_tenant


class TestSeedContent:
    def test_cantidades_formulario_usa_defaults_y_cap(self):
        d = demo_cantidades()
        assert cantidades_desde_formulario({})['obras'] == d['obras']
        parsed = cantidades_desde_formulario({
            'n_obras': '4',
            'n_empleados': '6',
            'n_solicitudes': '0',
        })
        assert parsed['obras'] == 4
        assert parsed['empleados'] == 6
        assert parsed['solicitudes'] == 0
        assert parsed['vehiculos'] == d['vehiculos']
        assert cantidades_desde_formulario({'n_obras': '9999'})['obras'] == 80

    def test_semilla_superadmin_no_es_demo(self, session, app):
        tenant = provision_new_tenant(
            nombre_empresa='Grabacion Co',
            subdominio='grabavid',
            admin_email='admin@grabavid.com',
            admin_password='test1234',
            modulos_activos={
                'onboarding': False,
                'fichaje_operario': True,
                'registro_jornada': True,
            },
        )
        qty = seed_tenant_content(
            tenant,
            qty={
                'obras': 3,
                'empleados': 6,
                'externos': 1,
                'vehiculos': 2,
                'jefes': 1,
                'dias_historial': 5,
                'dias_flota': 4,
                'solicitudes': 3,
            },
            activar_fichaje=True,
        )
        session.execute(text('SET search_path TO tenant_grabavid, public'))
        from flask import g
        g.current_tenant = tenant
        assert qty['obras'] == 3
        assert demo_activa() is False
        assert get_tenant_config(CONFIG_DEMO_CLEARED, default='False') == 'True'
        assert User.query.filter(User.email.ilike(f'%{DEMO_EMAIL_SUFFIX}')).count() == 0
        assert Obra.query.filter(Obra.codigo.ilike(f'{DEMO_OBRA_PREFIX}%')).count() == 0
        assert Vehiculo.query.filter(
            Vehiculo.matricula.ilike(f'{DEMO_MATRICULA_PREFIX}%')
        ).count() == 0
        assert Obra.query.filter(Obra.is_deleted.is_(False)).count() >= 3
        assert User.query.filter_by(role=ROLE_OPERARIO, is_deleted=False).count() >= 7
        assert Vehiculo.query.count() >= 2
        assert Solicitud.query.count() >= 1
        logs_plan = SystemLog.query.filter_by(category='planificacion').limit(30).all()
        assert logs_plan
        assert all(log.action != 'importacion' for log in logs_plan)
        assert any(log.action == 'Planificación Manual' for log in logs_plan)
        fichaje_logs = SystemLog.query.filter_by(category='fichaje_app').limit(10).all()
        assert fichaje_logs
        session.execute(text('SET search_path TO public'))
        session.execute(text('DROP SCHEMA tenant_grabavid CASCADE'))
        session.execute(text("DELETE FROM public.tenants WHERE subdominio = 'grabavid'"))
