# tests/integration/test_fichaje_informe.py
#
# Informe de registro de jornada para la Inspección.
#
# Lo crítico no es que el PDF se pinte: es que las horas salgan de las marcas
# vigentes del libro, que las correcciones aparezcan y que la verificación de
# la cadena forme parte del documento.

from datetime import date, datetime

import pytest
from sqlalchemy import text

from app.models import (
    EVENTO_ENTRADA,
    EVENTO_REASIGNACION_OBRA,
    EVENTO_SALIDA,
    ORIGEN_ADMIN,
    ORIGEN_ERP,
    ORIGEN_PWA,
    Company,
)
from app.services.fichaje_informe_service import (
    FichajeInformeError,
    generar_informe,
    informe_a_csv,
)
from app.services.fichaje_ledger_service import anular_evento, registrar_evento


FECHA = date(2026, 6, 15)


@pytest.fixture
def informe_ctx(session, tenant_soltec, company_internal,
                user_admin, user_jefe, user_operario, obra_activa):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    session.execute(text('ALTER TABLE fichajes_eventos DISABLE TRIGGER USER'))
    session.execute(text('DELETE FROM fichajes_eventos'))
    session.execute(text('ALTER TABLE fichajes_eventos ENABLE TRIGGER USER'))
    company_internal.nif = 'B12345678'
    session.commit()
    yield session


def _jornada(user_id, obra_id, entrada='06:00:00', salida='14:30:00'):
    registrar_evento(
        user_id=user_id,
        tipo=EVENTO_ENTRADA,
        origen=ORIGEN_PWA,
        ocurrido_en=datetime.strptime(f'2026-06-15 {entrada}', '%Y-%m-%d %H:%M:%S'),
        fecha_laboral=FECHA,
        obra_id=obra_id,
    )
    if salida:
        registrar_evento(
            user_id=user_id,
            tipo=EVENTO_SALIDA,
            origen=ORIGEN_PWA,
            ocurrido_en=datetime.strptime(f'2026-06-15 {salida}', '%Y-%m-%d %H:%M:%S'),
            fecha_laboral=FECHA,
            obra_id=obra_id,
        )


class TestInformeBasico:

    def test_incluye_al_trabajador_con_sus_horas(
        self, informe_ctx, user_operario, obra_activa, tenant_soltec
    ):
        _jornada(user_operario.id, obra_activa.id)
        informe_ctx.commit()

        informe = generar_informe(
            FECHA, FECHA, tenant_nombre=tenant_soltec.nombre
        )

        assert informe['trabajadores_count'] == 1
        t = informe['trabajadores'][0]
        assert t['dni'] == user_operario.dni
        assert t['minutos'] == 8 * 60 + 30
        assert t['dias'][0]['obra_nombre'] == obra_activa.nombre
        assert informe['cadena_integra'] is True
        assert informe['empresa']['nif'] == 'B12345678'
        assert informe['huella']

    def test_no_incluye_a_quien_no_ficha_en_el_periodo(
        self, informe_ctx, user_operario, user_jefe, obra_activa
    ):
        _jornada(user_operario.id, obra_activa.id)
        informe_ctx.commit()

        informe = generar_informe(FECHA, FECHA)

        assert [t['dni'] for t in informe['trabajadores']] == [user_operario.dni]

    def test_filtra_por_trabajador(
        self, informe_ctx, user_operario, user_jefe, obra_activa
    ):
        _jornada(user_operario.id, obra_activa.id)
        _jornada(user_jefe.id, obra_activa.id, entrada='07:00:00', salida='15:00:00')
        informe_ctx.commit()

        informe = generar_informe(FECHA, FECHA, user_id=user_operario.id)

        assert informe['trabajadores_count'] == 1
        assert informe['trabajadores'][0]['dni'] == user_operario.dni

    def test_filtra_por_empresa(
        self, informe_ctx, user_operario, user_jefe, obra_activa, company_internal
    ):
        otra = Company(code='EXT', nombre='Subcontrata SA', is_internal=False)
        informe_ctx.add(otra)
        informe_ctx.flush()
        user_jefe.company_id = otra.id
        informe_ctx.commit()

        _jornada(user_operario.id, obra_activa.id)
        _jornada(user_jefe.id, obra_activa.id, entrada='07:00:00', salida='15:00:00')
        informe_ctx.commit()

        informe = generar_informe(FECHA, FECHA, company_id=company_internal.id)

        assert informe['trabajadores_count'] == 1
        assert informe['trabajadores'][0]['dni'] == user_operario.dni

    def test_rango_demasiado_largo_se_rechaza(self, informe_ctx):
        with pytest.raises(FichajeInformeError):
            generar_informe(date(2024, 1, 1), date(2026, 6, 15))


class TestCorreccionesEnElInforme:

    def test_una_anulacion_aparece_y_no_cuenta_las_horas_anuladas(
        self, informe_ctx, user_operario, obra_activa, user_admin
    ):
        _jornada(user_operario.id, obra_activa.id)
        informe_ctx.commit()

        from app.models import FichajeEvento
        entrada = FichajeEvento.query.filter_by(tipo=EVENTO_ENTRADA).one()
        anular_evento(
            entrada.id,
            motivo='El trabajador acredita que ese día no vino.',
            autor_id=user_admin.id,
            origen=ORIGEN_ADMIN,
        )
        informe_ctx.commit()

        informe = generar_informe(FECHA, FECHA)
        dia = informe['trabajadores'][0]['dias'][0]

        assert dia['tiene_correcciones'] is True
        assert dia['entrada'] is None
        assert dia['minutos'] == 0
        assert 'no vino' in dia['correcciones'][0].motivo

    def test_una_reasignacion_aparece_sin_cambiar_las_horas(
        self, informe_ctx, user_operario, obra_activa
    ):
        _jornada(user_operario.id, obra_activa.id)
        informe_ctx.commit()

        registrar_evento(
            user_id=user_operario.id,
            tipo=EVENTO_REASIGNACION_OBRA,
            origen=ORIGEN_ERP,
            ocurrido_en=datetime(2026, 6, 15, 6, 0, 0),
            fecha_laboral=FECHA,
            obra_id=obra_activa.id,
            motivo='Reimputado a otra obra. Las horas no varían.',
        )
        informe_ctx.commit()

        informe = generar_informe(FECHA, FECHA)
        dia = informe['trabajadores'][0]['dias'][0]

        assert dia['minutos'] == 8 * 60 + 30
        assert dia['tiene_correcciones'] is True
        assert dia['correcciones'][0].tipo == EVENTO_REASIGNACION_OBRA


class TestExportacion:

    def test_el_csv_lleva_huella_y_estado_de_la_cadena(
        self, informe_ctx, user_operario, obra_activa, tenant_soltec
    ):
        _jornada(user_operario.id, obra_activa.id)
        informe_ctx.commit()

        informe = generar_informe(
            FECHA, FECHA, tenant_nombre=tenant_soltec.nombre
        )
        csv_texto = informe_a_csv(informe)

        assert user_operario.dni in csv_texto
        assert 'Cadena de integridad' in csv_texto
        assert 'Íntegra' in csv_texto
        assert informe['huella'] in csv_texto
        assert 'Total horas' in csv_texto

    def test_la_pantalla_del_informe_es_accesible_para_admin(
        self, informe_ctx, authenticated_client, user_operario, obra_activa
    ):
        _jornada(user_operario.id, obra_activa.id)
        informe_ctx.commit()

        respuesta = authenticated_client.get(
            f'/admin/registro-jornada?generar=1'
            f'&desde={FECHA.isoformat()}&hasta={FECHA.isoformat()}'
        )

        assert respuesta.status_code == 200
        html = respuesta.get_data(as_text=True)
        assert 'Cadena de integridad íntegra' in html
        assert user_operario.dni in html

    def test_el_csv_se_descarga(
        self, informe_ctx, authenticated_client, user_operario, obra_activa
    ):
        _jornada(user_operario.id, obra_activa.id)
        informe_ctx.commit()

        respuesta = authenticated_client.get(
            f'/admin/registro-jornada.csv'
            f'?desde={FECHA.isoformat()}&hasta={FECHA.isoformat()}'
        )

        assert respuesta.status_code == 200
        assert 'attachment' in respuesta.headers['Content-Disposition']
        assert user_operario.dni in respuesta.get_data(as_text=True)

    def test_un_operario_no_puede_ver_el_informe_de_empresa(
        self, informe_ctx, tenant_client, user_operario, obra_activa
    ):
        _jornada(user_operario.id, obra_activa.id)
        informe_ctx.commit()

        # Sin activar la PWA el operario no entra; forzamos sesión no autenticada.
        respuesta = tenant_client.get('/admin/registro-jornada')
        assert respuesta.status_code in (302, 401)
