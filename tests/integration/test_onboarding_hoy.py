# tests/integration/test_onboarding_hoy.py
#
# Wizard post-alta y resumen «hoy en obra» del panel.

from sqlalchemy import text

from app.models import Asignacion, Obra, RegistroFichaje
from app.services.onboarding_service import (
    CONFIG_ONBOARDING,
    debe_redirigir_a_wizard,
    marcar_onboarding_completo,
    necesita_onboarding,
    tenant_tiene_onboarding,
    tenant_tiene_registro_jornada,
)
from app.services.panel_service import resumen_hoy_plan_vs_ficha
from app.services.plan_service import monetizacion_activa
from app.utils.timezone_utils import today_local


class TestBillingApagado:

    def test_por_defecto_no_se_monetiza(self, app):
        with app.app_context():
            assert monetizacion_activa() is False
            assert app.config.get('BILLING_ENFORCED') is False


class TestOnboarding:

    def test_si_el_modulo_esta_apagado_no_hay_onboarding(self, app, tenant_soltec):
        with app.test_request_context():
            tenant_soltec.modulos_activos = {'onboarding': False, 'registro_jornada': True}
            from flask import g
            g.current_tenant = tenant_soltec
            assert tenant_tiene_onboarding() is False
            assert necesita_onboarding() is False

    def test_registro_jornada_es_visible_por_defecto(self, app, tenant_soltec):
        with app.test_request_context():
            from flask import g
            g.current_tenant = tenant_soltec
            tenant_soltec.modulos_activos = {}
            assert tenant_tiene_registro_jornada() is True

    def test_empresa_vacia_fuerza_wizard(self, session, tenant_soltec, app):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        tenant_soltec.modulos_activos = {'onboarding': True, 'registro_jornada': True}
        session.execute(text('DELETE FROM asignaciones'))
        session.execute(text('UPDATE obras SET is_deleted = true'))
        session.execute(
            text(
                'INSERT INTO configuracion_global (clave, valor) VALUES '
                f"('{CONFIG_ONBOARDING}', 'False') "
                'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
            )
        )
        session.execute(
            text(
                'INSERT INTO configuracion_global (clave, valor) VALUES '
                "('fichaje_operario_activo', 'False') "
                'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
            )
        )
        session.execute(
            text(
                'INSERT INTO configuracion_global (clave, valor) VALUES '
                "('obra_oficina_activa', 'False') "
                'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
            )
        )
        session.commit()
        with app.test_request_context():
            from flask import g
            g.current_tenant = tenant_soltec
            assert debe_redirigir_a_wizard() is True
            assert necesita_onboarding() is True

    def test_onboarding_incompleto_redirige_aunque_haya_obra(
        self, session, tenant_soltec, app,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        tenant_soltec.modulos_activos = {'onboarding': True, 'registro_jornada': True}
        session.execute(
            text(
                'INSERT INTO configuracion_global (clave, valor) VALUES '
                f"('{CONFIG_ONBOARDING}', 'False') "
                'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
            )
        )
        if Obra.query.filter(Obra.is_deleted.is_(False)).count() == 0:
            session.add(Obra(nombre='Obra test onboarding', estado='En Curso'))
            session.commit()
        with app.test_request_context():
            from flask import g
            g.current_tenant = tenant_soltec
            assert necesita_onboarding() is True
            assert debe_redirigir_a_wizard() is True

    def test_marcar_completo_quita_aviso(self, session, tenant_soltec, app):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        tenant_soltec.modulos_activos = {'onboarding': True, 'registro_jornada': True}
        with app.test_request_context():
            from flask import g
            g.current_tenant = tenant_soltec
            marcar_onboarding_completo()
            assert necesita_onboarding() is False
            assert debe_redirigir_a_wizard() is False

    def test_paso_informe_se_marca(self, session, tenant_soltec, app):
        from app.services.onboarding_service import (
            informe_onboarding_visto,
            marcar_informe_visto,
            estado_onboarding,
        )
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        tenant_soltec.modulos_activos = {'onboarding': True, 'registro_jornada': True}
        session.execute(
            text(
                'INSERT INTO configuracion_global (clave, valor) VALUES '
                f"('{CONFIG_ONBOARDING}', 'False') "
                'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
            )
        )
        with app.test_request_context():
            from flask import g
            g.current_tenant = tenant_soltec
            assert informe_onboarding_visto() is False
            marcar_informe_visto()
            assert informe_onboarding_visto() is True
            estado = estado_onboarding()
            assert estado['informe_visto'] is True


class TestHoyEnObra:

    def test_planificado_sin_fichar(self, session, tenant_soltec, user_operario):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        hoy = today_local()
        obra = Obra.query.filter(Obra.is_deleted.is_(False)).first()
        if obra is None:
            obra = Obra(nombre='Tajo hoy', estado='En Curso')
            session.add(obra)
            session.flush()
        Asignacion.query.filter_by(fecha=hoy, user_id=user_operario.id).delete()
        RegistroFichaje.query.filter_by(fecha=hoy, user_id=user_operario.id).delete()
        session.add(Asignacion(
            user_id=user_operario.id,
            obra_id=obra.id,
            fecha=hoy,
        ))
        session.commit()

        resumen = resumen_hoy_plan_vs_ficha(hoy)
        assert resumen['planificados'] >= 1
        fila = next(f for f in resumen['filas'] if f['user'].id == user_operario.id)
        assert fila['estado'] == 'sin_fichar'


class TestAcademia:

    def test_visible_por_defecto(self, session, tenant_soltec, app):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        with app.test_request_context():
            from flask import g
            from app.services.onboarding_service import academia_visible

            g.current_tenant = tenant_soltec
            assert academia_visible() is True

    def test_se_puede_apagar_y_reiniciar_la_vuelve_a_mostrar(
        self, session, tenant_soltec, app,
    ):
        from app.services.onboarding_service import (
            academia_visible,
            reiniciar_onboarding,
            set_academia_visible,
        )

        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        tenant_soltec.modulos_activos = {
            **(tenant_soltec.modulos_activos or {}),
            'onboarding': True,
        }
        with app.test_request_context():
            from flask import g
            g.current_tenant = tenant_soltec
            set_academia_visible(False)
            assert academia_visible() is False
            reiniciar_onboarding()
            assert academia_visible() is True

    def test_hub_all_done_ignora_import_opcional(self):
        from app.services.tour_catalog_service import hub_all_done

        assert hub_all_done({
            'caminitos': {
                'inicial': [{'id': 'tablero_leer', 'status': 'done'}],
                'shared': [{'id': 'planificador_multi', 'status': 'done'}],
                'advanced': [{'id': 'coches_libres', 'status': 'done'}],
                'side_import': {'id': 'import', 'status': 'available'},
            },
        }) is True
        assert hub_all_done({
            'caminitos': {
                'inicial': [{'id': 'tablero_leer', 'status': 'done'}],
                'shared': [{'id': 'planificador_multi', 'status': 'available'}],
                'advanced': [],
            },
        }) is False
        assert hub_all_done({
            'caminitos': {
                'inicial': [{'id': 'tablero_leer', 'status': 'done'}],
                'shared': [{'id': 'flota', 'status': 'locked'}],
                'advanced': [{'id': 'coches_libres', 'status': 'locked'}],
            },
        }) is True
        assert hub_all_done({'caminitos': {}}) is False

    def test_auto_hide_al_completar_todos(self, session, tenant_soltec, app, monkeypatch):
        from app.services.onboarding_service import (
            academia_visible,
            marcar_onboarding_completo,
            set_academia_visible,
        )
        from app.services.tour_catalog_service import maybe_auto_hide_academia

        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        tenant_soltec.modulos_activos = {
            **(tenant_soltec.modulos_activos or {}),
            'onboarding': True,
        }
        with app.test_request_context():
            from flask import g
            g.current_tenant = tenant_soltec
            marcar_onboarding_completo()
            set_academia_visible(True)
            monkeypatch.setattr(
                'app.services.tour_catalog_service.evaluate_academia',
                lambda user=None: {
                    'caminitos': {
                        'inicial': [{'id': 'tablero_leer', 'status': 'done'}],
                        'shared': [{'id': 'planificador_multi', 'status': 'done'}],
                        'advanced': [],
                    },
                },
            )
            assert maybe_auto_hide_academia() is True
            assert academia_visible() is False

    def test_repetir_no_vuelve_a_ocultar(self, session, tenant_soltec, app, monkeypatch):
        from app.services.onboarding_service import (
            academia_visible,
            marcar_onboarding_completo,
            set_academia_visible,
        )
        from app.services.tour_catalog_service import mark_tour_done

        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        tenant_soltec.modulos_activos = {
            **(tenant_soltec.modulos_activos or {}),
            'onboarding': True,
        }
        with app.test_request_context():
            from flask import g
            g.current_tenant = tenant_soltec
            marcar_onboarding_completo()
            mark_tour_done('tablero_leer')
            set_academia_visible(True)
            called = {'n': 0}

            def _hide():
                called['n'] += 1
                return True

            monkeypatch.setattr(
                'app.services.tour_catalog_service.maybe_auto_hide_academia',
                _hide,
            )
            mark_tour_done('tablero_leer')
            assert called['n'] == 0
            assert academia_visible() is True

