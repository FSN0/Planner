# tests/integration/test_fichaje_erp_ledger.py
#
# Volcado de los fichajes del ERP al libro de eventos.
#
# La dificultad no está en anotar un fichaje: está en que la sincronización
# vuelve a pasar por la misma fecha muchas veces al día, y además hay una
# revisión retrospectiva que repasa hasta un año atrás. El libro solo admite
# añadir, así que cada pasada tiene que anotar exclusivamente la diferencia.
#
# Del ERP solo se lee. Cuando alguien corrige un fichaje allí, aquí queda la
# marca anterior, la anulación con su motivo y la nueva.

from datetime import date, datetime

import pytest
from sqlalchemy import text

from app.models import (
    EVENTO_ANULACION,
    EVENTO_ENTRADA,
    EVENTO_REASIGNACION_OBRA,
    EVENTO_SALIDA,
    ORIGEN_ADMIN,
    ORIGEN_ERP,
    ORIGEN_MIGRACION,
    FichajeEvento,
    Obra,
)
from app.services.fichaje_erp_ledger_service import reflejar_jornada_del_erp

FECHA = date(2026, 6, 15)


def _apunte(ref, empleado, obra, entrada, salida=None, autor='RRHH Odoo'):
    """Un apunte tal como lo devuelve el adaptador de Odoo."""
    return {
        'registro_external_id': ref,
        'origen_modelo': 'hr.attendance',
        'empleado_external_id': empleado,
        'obra_external_id': obra,
        'fecha': FECHA.strftime('%Y-%m-%d'),
        'check_in': entrada,
        'check_out': salida,
        'autor': autor,
        'note': None,
    }


def _eventos(tipo=None, incluir_anulaciones=True):
    consulta = FichajeEvento.query.order_by(FichajeEvento.secuencia.asc())
    eventos = consulta.all()
    if not incluir_anulaciones:
        eventos = [e for e in eventos if e.tipo != EVENTO_ANULACION]
    if tipo:
        eventos = [e for e in eventos if e.tipo == tipo]
    return eventos


@pytest.fixture
def erp(session, tenant_soltec, company_internal,
        user_admin, user_jefe, user_operario, obra_activa):
    """
    Libro vacío, con el operario y la obra enlazados a identificadores de Odoo.

    Depende de todas las fixtures de datos aunque no use sus valores: cada una
    devuelve el search_path a 'public' al terminar, así que esta debe ir última.
    """
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    session.execute(text('ALTER TABLE fichajes_eventos DISABLE TRIGGER USER'))
    session.execute(text('DELETE FROM fichajes_eventos'))
    session.execute(text('ALTER TABLE fichajes_eventos ENABLE TRIGGER USER'))

    user_operario.external_ids = {'odoo': '77'}
    user_jefe.external_ids = {'odoo': '78'}
    obra_activa.external_ids = {'odoo': '500'}
    session.commit()

    yield session


@pytest.fixture
def obra_secundaria(erp, user_jefe):
    """Segunda obra, para reimputar horas de una a otra."""
    obra = Obra(
        codigo='OBR002',
        nombre='Nave Industrial Norte',
        estado='En proceso',
        jefe_obra_id=user_jefe.id,
        external_ids={'odoo': '501'},
    )
    erp.add(obra)
    erp.commit()
    return obra


class TestPrimeraPasada:

    def test_un_fichaje_completo_se_anota_como_entrada_y_salida(
        self, erp, user_operario, obra_activa
    ):
        resumen = reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()

        assert resumen['altas'] == 2

        entrada, salida = _eventos(incluir_anulaciones=False)
        assert entrada.tipo == EVENTO_ENTRADA
        assert entrada.origen == ORIGEN_ERP
        assert entrada.user_id == user_operario.id
        assert entrada.obra_id == obra_activa.id
        assert entrada.fecha_laboral == FECHA
        assert entrada.ocurrido_en == datetime(2026, 6, 15, 6, 0, 0)
        assert entrada.external_ids['erp_ref'] == 'hr.attendance:4471'
        # Nadie de la aplicación es autor: el dato lo introdujo el ERP.
        assert entrada.autor_id is None
        assert salida.ocurrido_en == datetime(2026, 6, 15, 14, 30, 0)

    def test_una_jornada_aun_abierta_solo_anota_la_entrada(self, erp):
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', None),
        ])
        erp.commit()

        eventos = _eventos(incluir_anulaciones=False)
        assert len(eventos) == 1
        assert eventos[0].tipo == EVENTO_ENTRADA

    def test_cada_apunte_del_erp_se_anota_por_separado(self, erp):
        """
        El motor de auditoría fusiona los apuntes de una misma obra en un solo
        registro. El libro no: guarda el hecho en bruto, no la interpretación.
        """
        reflejar_jornada_del_erp(FECHA, [
            _apunte('1', '77', '500', '2026-06-15 06:00:00', '2026-06-15 10:00:00'),
            _apunte('2', '77', '500', '2026-06-15 11:00:00', '2026-06-15 15:00:00'),
        ])
        erp.commit()

        assert len(_eventos(EVENTO_ENTRADA)) == 2
        assert len(_eventos(EVENTO_SALIDA)) == 2

    def test_un_apunte_sin_identidad_no_entra(self, erp):
        """Sin referencia estable no se puede reconciliar, y duplicaría."""
        apunte = _apunte('1', '77', '500', '2026-06-15 06:00:00')
        del apunte['registro_external_id']

        reflejar_jornada_del_erp(FECHA, [apunte])
        erp.commit()

        assert FichajeEvento.query.count() == 0

    def test_un_empleado_desconocido_se_ignora(self, erp):
        reflejar_jornada_del_erp(FECHA, [
            _apunte('1', '99999', '500', '2026-06-15 06:00:00'),
        ])
        erp.commit()

        assert FichajeEvento.query.count() == 0


class TestPasadasRepetidas:

    def test_repetir_la_sincronizacion_no_duplica_nada(self, erp):
        """
        Lo que más daño haría: el sync corre cada pocos minutos y sin esto la
        jornada acabaría con decenas de entradas repetidas.
        """
        apuntes = [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ]

        for _ in range(5):
            reflejar_jornada_del_erp(FECHA, apuntes)
            erp.commit()

        assert FichajeEvento.query.count() == 2

    def test_la_salida_que_aparece_despues_se_añade_sin_tocar_la_entrada(self, erp):
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', None),
        ])
        erp.commit()
        hash_entrada = _eventos(EVENTO_ENTRADA)[0].hash

        resumen = reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()

        assert resumen['altas'] == 1
        assert _eventos(EVENTO_ENTRADA)[0].hash == hash_entrada
        assert len(_eventos(EVENTO_SALIDA)) == 1


class TestCorreccionesEnElErp:

    def test_cambiar_la_hora_en_odoo_deja_rastro_de_las_tres_cosas(self, erp):
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()

        resumen = reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 07:15:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()

        assert resumen['correcciones'] == 1

        # La marca original sigue en el libro, nadie la ha borrado.
        entradas = _eventos(EVENTO_ENTRADA)
        assert len(entradas) == 2
        assert entradas[0].ocurrido_en == datetime(2026, 6, 15, 6, 0, 0)
        assert entradas[1].ocurrido_en == datetime(2026, 6, 15, 7, 15, 0)

        anulacion = _eventos(EVENTO_ANULACION)[0]
        assert anulacion.evento_anulado_id == entradas[0].id
        assert '06:00:00' in anulacion.motivo and '07:15:00' in anulacion.motivo

    def test_tras_la_correccion_solo_queda_vigente_la_hora_nueva(
        self, erp, user_operario
    ):
        from app.services.fichaje_ledger_service import eventos_del_dia

        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00'),
        ])
        erp.commit()
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 07:15:00'),
        ])
        erp.commit()

        vigentes = eventos_del_dia(user_operario.id, FECHA)
        assert len(vigentes) == 1
        assert vigentes[0].ocurrido_en == datetime(2026, 6, 15, 7, 15, 0)

    def test_borrar_la_salida_en_odoo_la_anula_pero_no_la_borra(self, erp):
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()

        resumen = reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', None),
        ])
        erp.commit()

        assert resumen['retiradas'] == 1
        assert len(_eventos(EVENTO_SALIDA)) == 1
        assert len(_eventos(EVENTO_ANULACION)) == 1

    def test_borrar_el_apunte_entero_en_odoo_anula_sus_dos_marcas(self, erp):
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()

        resumen = reflejar_jornada_del_erp(FECHA, [])
        erp.commit()

        assert resumen['retiradas'] == 2
        assert len(_eventos(EVENTO_ANULACION)) == 2
        # Las marcas originales siguen ahí: se han dejado sin efecto, no borrado.
        assert len(_eventos(EVENTO_ENTRADA)) == 1
        assert len(_eventos(EVENTO_SALIDA)) == 1

    def test_no_se_pisa_una_correccion_hecha_a_mano_en_la_aplicacion(self, erp):
        """
        Si alguien corrigió el fichaje aquí y el ERP sigue mandando el original,
        volver a anotarlo desharía su decisión en cada pasada.
        """
        from app.services.fichaje_ledger_service import anular_evento

        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00'),
        ])
        erp.commit()

        entrada = _eventos(EVENTO_ENTRADA)[0]
        anular_evento(
            entrada.id,
            motivo='El trabajador acredita que ese día no vino.',
            autor_id=entrada.user_id,
            origen=ORIGEN_ADMIN,
        )
        erp.commit()

        resumen = reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00'),
        ])
        erp.commit()

        assert resumen['respetadas'] == 1
        assert resumen['altas'] == 0
        assert len(_eventos(EVENTO_ENTRADA)) == 1


class TestReimputacionDeObra:
    """
    El flujo diario de Soltec: el trabajador ficha en la obra que pilla y
    administración lo reimputa después en Odoo.

    No es una rectificación de jornada. El art. 34.9 ET obliga a registrar el
    horario de inicio y fin; a qué obra se cargan esas horas es contabilidad de
    costes. Por eso el libro lo anota aparte y no toca las marcas de tiempo:
    si cada corrección de obra anulase la entrada, el registro parecería lleno
    de jornadas rectificadas sin que nadie haya tocado una sola hora.
    """

    def test_cambiar_la_obra_en_odoo_no_toca_las_marcas_de_tiempo(
        self, erp, obra_activa, obra_secundaria
    ):
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()
        entrada_original = _eventos(EVENTO_ENTRADA)[0]
        hash_original = entrada_original.hash

        resumen = reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '501', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()

        assert resumen['reasignaciones'] == 1
        assert resumen['correcciones'] == 0
        assert resumen['retiradas'] == 0

        # Ni una anulación: las horas registradas son las mismas de siempre.
        assert _eventos(EVENTO_ANULACION) == []
        assert len(_eventos(EVENTO_ENTRADA)) == 1
        assert _eventos(EVENTO_ENTRADA)[0].hash == hash_original

    def test_la_reasignacion_deja_constancia_de_las_dos_obras(
        self, erp, obra_activa, obra_secundaria
    ):
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00'),
        ])
        erp.commit()
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '501', '2026-06-15 06:00:00'),
        ])
        erp.commit()

        reasignacion = _eventos(EVENTO_REASIGNACION_OBRA)[0]
        assert reasignacion.obra_id == obra_secundaria.id
        assert reasignacion.external_ids['obra_anterior_id'] == obra_activa.id
        assert obra_activa.nombre in reasignacion.motivo
        assert obra_secundaria.nombre in reasignacion.motivo

    def test_repetir_el_sync_tras_reimputar_no_vuelve_a_anotarlo(
        self, erp, obra_secundaria
    ):
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00'),
        ])
        erp.commit()

        for _ in range(4):
            reflejar_jornada_del_erp(FECHA, [
                _apunte('4471', '77', '501', '2026-06-15 06:00:00'),
            ])
            erp.commit()

        assert len(_eventos(EVENTO_REASIGNACION_OBRA)) == 1

    def test_reimputar_de_vuelta_a_la_obra_original_se_anota_otra_vez(
        self, erp, obra_activa, obra_secundaria
    ):
        """Administración se equivoca y lo deshace: los tres pasos constan."""
        for obra in ('500', '501', '500'):
            reflejar_jornada_del_erp(FECHA, [
                _apunte('4471', '77', obra, '2026-06-15 06:00:00'),
            ])
            erp.commit()

        reasignaciones = _eventos(EVENTO_REASIGNACION_OBRA)
        assert len(reasignaciones) == 2
        assert reasignaciones[0].obra_id == obra_secundaria.id
        assert reasignaciones[1].obra_id == obra_activa.id

    def test_la_proyeccion_imputa_las_horas_a_la_obra_corregida(
        self, erp, user_operario, obra_secundaria
    ):
        from app.models import RegistroFichaje
        from app.services.fichaje_ledger_service import proyectar_dia

        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '501', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()

        proyectar_dia(user_operario.id, FECHA)
        erp.commit()

        registro = RegistroFichaje.query.filter_by(
            user_id=user_operario.id, fecha=FECHA
        ).one()
        assert registro.obra_real_id == obra_secundaria.id
        assert registro.check_in == datetime(2026, 6, 15, 6, 0, 0)

    def test_la_reasignacion_no_altera_las_horas_computadas(
        self, erp, user_operario, obra_secundaria
    ):
        from app.services.fichaje_ledger_service import minutos_trabajados

        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()
        antes = minutos_trabajados(user_operario.id, FECHA)

        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '501', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()

        assert antes == 8 * 60 + 30
        assert minutos_trabajados(user_operario.id, FECHA) == antes

    def test_cambiar_obra_y_hora_a_la_vez_no_duplica_el_cambio(
        self, erp, obra_secundaria
    ):
        """
        Las marcas rehechas ya llevan la obra buena; anotar además una
        reasignación contaría dos veces el mismo cambio.
        """
        reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00'),
        ])
        erp.commit()

        resumen = reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '501', '2026-06-15 07:00:00'),
        ])
        erp.commit()

        assert resumen['correcciones'] == 1
        assert resumen['reasignaciones'] == 0
        assert _eventos(EVENTO_ENTRADA)[-1].obra_id == obra_secundaria.id

    def test_una_reasignacion_sin_obra_se_rechaza(self, erp, user_operario):
        from app.services.fichaje_ledger_service import (
            FichajeLedgerError,
            registrar_evento,
        )

        with pytest.raises(FichajeLedgerError):
            registrar_evento(
                user_id=user_operario.id,
                tipo=EVENTO_REASIGNACION_OBRA,
                origen=ORIGEN_ERP,
                fecha_laboral=FECHA,
                obra_id=None,
                motivo='Sin destino.',
            )


class TestConvivenciaConElVolcadoDelHistorico:

    def test_una_jornada_ya_importada_no_se_vuelve_a_derivar_del_erp(
        self, erp, user_operario, obra_activa
    ):
        """
        La revisión retrospectiva repasa hasta un año atrás, y esos días los
        rellenó el backfill desde la tabla antigua. Como el volcado y el ERP
        describen los mismos fichajes sin compartir referencia, derivarlos otra
        vez los contaría dos veces.
        """
        from app.services.fichaje_ledger_service import registrar_evento

        registrar_evento(
            user_id=user_operario.id,
            tipo=EVENTO_ENTRADA,
            origen=ORIGEN_MIGRACION,
            ocurrido_en=datetime(2026, 6, 15, 6, 0, 0),
            fecha_laboral=FECHA,
            obra_id=obra_activa.id,
            motivo='Importado del histórico anterior.',
            external_ids={'registro_fichaje_id': '123'},
        )
        erp.commit()

        resumen = reflejar_jornada_del_erp(FECHA, [
            _apunte('4471', '77', '500', '2026-06-15 06:00:00', '2026-06-15 14:30:00'),
        ])
        erp.commit()

        assert resumen == {'omitida_por_importacion': True}
        assert FichajeEvento.query.count() == 1


class TestIntegridad:

    def test_la_cadena_sigue_intacta_despues_de_todo_el_trasiego(self, erp):
        from app.services.fichaje_ledger_service import verificar_cadena

        reflejar_jornada_del_erp(FECHA, [
            _apunte('1', '77', '500', '2026-06-15 06:00:00', '2026-06-15 14:00:00'),
            _apunte('2', '78', '500', '2026-06-15 07:00:00', None),
        ])
        erp.commit()

        reflejar_jornada_del_erp(FECHA, [
            _apunte('1', '77', '500', '2026-06-15 06:30:00', '2026-06-15 14:00:00'),
            _apunte('2', '78', '500', '2026-06-15 07:00:00', '2026-06-15 16:00:00'),
        ])
        erp.commit()

        reflejar_jornada_del_erp(FECHA, [
            _apunte('2', '78', '500', '2026-06-15 07:00:00', '2026-06-15 16:00:00'),
        ])
        erp.commit()

        assert verificar_cadena() == []
