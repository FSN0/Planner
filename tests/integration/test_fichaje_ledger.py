"""
Tests del libro de eventos de jornada.

Aquí se comprueba lo que hay que poder demostrar delante de una inspección:
que los fichajes no se pueden modificar ni borrar, que cualquier manipulación
por fuera de la aplicación queda en evidencia, y que las correcciones dejan
constancia de quién, cuándo y por qué.
"""

import pytest
from datetime import date, datetime, time, timedelta

from sqlalchemy import text
# El disparador lanza SQLSTATE 23001 (restrict_violation), que psycopg2 mapea a
# IntegrityError; se captura la clase padre para no atarse al mapeo exacto.
from sqlalchemy.exc import DatabaseError

from app import db as _db
from app.models import (
    ANIOS_CONSERVACION_FICHAJES,
    EVENTO_ANULACION,
    EVENTO_ENTRADA,
    EVENTO_PAUSA_FIN,
    EVENTO_PAUSA_INICIO,
    EVENTO_SALIDA,
    ORIGEN_ADMIN,
    ORIGEN_PWA,
    FichajeEvento,
    RegistroFichaje,
)
from app.services.fichaje_ledger_service import (
    FichajeLedgerError,
    anular_evento,
    esta_anulado,
    eventos_del_dia,
    jornada_abierta,
    minutos_trabajados,
    proyectar_dia,
    puede_purgarse,
    registrar_evento,
    verificar_cadena,
)


@pytest.fixture
def ledger(
    session, tenant_soltec, company_internal,
    user_admin, user_jefe, user_operario, obra_activa,
):
    """
    Deja la sesión apuntando al esquema del tenant, con el libro vacío.

    Depende de todas las fixtures de datos a propósito, aunque no use sus
    valores: cada una devuelve el search_path a 'public' al terminar, así que
    esta tiene que ejecutarse la última. Si no, el test escribiría en 'public'
    y las claves ajenas apuntarían a usuarios de otro esquema.
    """
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    session.execute(text("ALTER TABLE fichajes_eventos DISABLE TRIGGER USER"))
    session.execute(text("DELETE FROM fichajes_eventos"))
    session.execute(text("ALTER TABLE fichajes_eventos ENABLE TRIGGER USER"))
    session.commit()
    yield session


def _jornada(session, user_id, obra_id, dia, entrada, salida=None):
    registrar_evento(
        user_id=user_id, tipo=EVENTO_ENTRADA, origen=ORIGEN_PWA,
        ocurrido_en=datetime.combine(dia, entrada), fecha_laboral=dia,
        obra_id=obra_id,
    )
    if salida:
        registrar_evento(
            user_id=user_id, tipo=EVENTO_SALIDA, origen=ORIGEN_PWA,
            ocurrido_en=datetime.combine(dia, salida), fecha_laboral=dia,
            obra_id=obra_id,
        )
    session.commit()


class TestCadena:
    """La integridad de la cadena de hashes."""

    def test_eventos_se_encadenan_en_orden(
        self, ledger, user_operario, obra_activa
    ):
        hoy = date.today()
        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(8, 0), time(17, 0))

        eventos = FichajeEvento.query.order_by(FichajeEvento.secuencia).all()

        assert len(eventos) == 2
        assert [e.secuencia for e in eventos] == [1, 2]
        assert eventos[0].hash_previo is None
        assert eventos[1].hash_previo == eventos[0].hash
        assert eventos[0].hash != eventos[1].hash

    def test_cadena_limpia_no_tiene_incidencias(
        self, ledger, user_operario, obra_activa
    ):
        hoy = date.today()
        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(8, 0), time(17, 0))
        _jornada(
            ledger, user_operario.id, obra_activa.id,
            hoy - timedelta(days=1), time(7, 30), time(15, 30),
        )

        assert verificar_cadena() == []

    def test_manipulacion_directa_en_bd_queda_al_descubierto(
        self, ledger, user_operario, obra_activa
    ):
        """
        El caso que de verdad importa: alguien con acceso a la base de datos
        desactiva el disparador y cambia una hora. La cadena lo delata.
        """
        hoy = date.today()
        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(8, 0), time(17, 0))

        assert verificar_cadena() == []

        ledger.execute(text("ALTER TABLE fichajes_eventos DISABLE TRIGGER USER"))
        ledger.execute(text(
            "UPDATE fichajes_eventos SET ocurrido_en = ocurrido_en - INTERVAL '1 hour' "
            "WHERE secuencia = 1"
        ))
        ledger.execute(text("ALTER TABLE fichajes_eventos ENABLE TRIGGER USER"))
        ledger.commit()
        ledger.expire_all()

        incidencias = verificar_cadena()

        assert incidencias, "Una hora alterada debe romper la verificación"
        assert any(i['tipo'] == 'contenido_alterado' for i in incidencias)
        assert incidencias[0]['secuencia'] == 1


class TestInmutabilidad:
    """La barrera de la base de datos."""

    def test_no_se_puede_modificar_un_evento(
        self, ledger, user_operario, obra_activa
    ):
        hoy = date.today()
        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(8, 0))

        with pytest.raises(DatabaseError) as exc:
            ledger.execute(text(
                "UPDATE fichajes_eventos SET ocurrido_en = NOW() WHERE secuencia = 1"
            ))

        assert 'inalterable' in str(exc.value).lower()
        ledger.rollback()

    def test_no_se_puede_borrar_un_evento(
        self, ledger, user_operario, obra_activa
    ):
        hoy = date.today()
        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(8, 0))

        with pytest.raises(DatabaseError) as exc:
            ledger.execute(text("DELETE FROM fichajes_eventos WHERE secuencia = 1"))

        assert 'inalterable' in str(exc.value).lower()
        ledger.rollback()

    def test_no_se_puede_vaciar_la_tabla(
        self, ledger, user_operario, obra_activa
    ):
        hoy = date.today()
        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(8, 0))

        with pytest.raises(DatabaseError):
            ledger.execute(text("TRUNCATE TABLE fichajes_eventos"))

        ledger.rollback()


class TestCorrecciones:
    """Corregir sin reescribir el pasado."""

    def test_anular_no_borra_y_deja_motivo(
        self, ledger, user_operario, user_admin, obra_activa
    ):
        hoy = date.today()
        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(8, 0))
        original = FichajeEvento.query.filter_by(secuencia=1).one()

        anulacion = anular_evento(
            original.id,
            motivo='Fichó por error en la obra equivocada.',
            autor_id=user_admin.id,
        )
        ledger.commit()

        assert FichajeEvento.query.count() == 2
        assert anulacion.tipo == EVENTO_ANULACION
        assert anulacion.evento_anulado_id == original.id
        assert anulacion.autor_id == user_admin.id
        assert 'obra equivocada' in anulacion.motivo
        assert esta_anulado(original.id)

        # El original sigue ahí, intacto.
        assert FichajeEvento.query.filter_by(secuencia=1).one().ocurrido_en \
            == datetime.combine(hoy, time(8, 0))

    def test_evento_anulado_desaparece_del_dia_pero_no_del_libro(
        self, ledger, user_operario, user_admin, obra_activa
    ):
        hoy = date.today()
        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(8, 0))
        original = FichajeEvento.query.filter_by(secuencia=1).one()

        anular_evento(original.id, motivo='Duplicado.', autor_id=user_admin.id)
        ledger.commit()

        assert eventos_del_dia(user_operario.id, hoy) == []
        assert len(eventos_del_dia(user_operario.id, hoy, incluir_anulados=True)) == 2

    def test_anulacion_sin_motivo_se_rechaza(
        self, ledger, user_operario, user_admin, obra_activa
    ):
        hoy = date.today()
        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(8, 0))
        original = FichajeEvento.query.filter_by(secuencia=1).one()

        with pytest.raises(FichajeLedgerError, match='motivo'):
            anular_evento(original.id, motivo='   ', autor_id=user_admin.id)

    def test_alta_manual_exige_motivo(self, ledger, user_operario, obra_activa):
        with pytest.raises(FichajeLedgerError, match='motivo'):
            registrar_evento(
                user_id=user_operario.id,
                tipo=EVENTO_ENTRADA,
                origen=ORIGEN_ADMIN,
                obra_id=obra_activa.id,
            )

    def test_no_se_anula_dos_veces(
        self, ledger, user_operario, user_admin, obra_activa
    ):
        hoy = date.today()
        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(8, 0))
        original = FichajeEvento.query.filter_by(secuencia=1).one()

        anular_evento(original.id, motivo='Error.', autor_id=user_admin.id)
        ledger.commit()

        with pytest.raises(FichajeLedgerError, match='ya estaba anulado'):
            anular_evento(original.id, motivo='Otra vez.', autor_id=user_admin.id)


class TestProyeccion:
    """RegistroFichaje se deriva de los eventos."""

    def test_proyeccion_rellena_entrada_salida_y_obra(
        self, ledger, user_operario, obra_activa
    ):
        hoy = date.today()
        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(7, 45), time(16, 15))

        registro = proyectar_dia(user_operario.id, hoy)
        ledger.commit()

        assert registro is not None
        assert registro.check_in == datetime.combine(hoy, time(7, 45))
        assert registro.check_out == datetime.combine(hoy, time(16, 15))
        assert registro.obra_real_id == obra_activa.id

    def test_proyeccion_ignora_eventos_anulados(
        self, ledger, user_operario, user_admin, obra_activa
    ):
        hoy = date.today()
        registrar_evento(
            user_id=user_operario.id, tipo=EVENTO_ENTRADA, origen=ORIGEN_PWA,
            ocurrido_en=datetime.combine(hoy, time(6, 0)), fecha_laboral=hoy,
            obra_id=obra_activa.id,
        )
        ledger.commit()
        erroneo = FichajeEvento.query.filter_by(secuencia=1).one()
        anular_evento(erroneo.id, motivo='Fichó sin querer.', autor_id=user_admin.id)

        registrar_evento(
            user_id=user_operario.id, tipo=EVENTO_ENTRADA, origen=ORIGEN_PWA,
            ocurrido_en=datetime.combine(hoy, time(8, 0)), fecha_laboral=hoy,
            obra_id=obra_activa.id,
        )
        ledger.commit()

        registro = proyectar_dia(user_operario.id, hoy)
        ledger.commit()

        assert registro.check_in == datetime.combine(hoy, time(8, 0))

    def test_proyeccion_no_pisa_el_estado_de_la_auditoria(
        self, ledger, user_operario, obra_activa
    ):
        """
        El estado de conciliación es un juicio de la empresa, no un hecho:
        la proyección no debe tocarlo.
        """
        hoy = date.today()
        ledger.add(RegistroFichaje(
            user_id=user_operario.id, fecha=hoy,
            obra_planificada_id=obra_activa.id,
            estado='Resuelto_Movido',
            notas_resolucion='Lo movió RRHH.',
        ))
        ledger.commit()

        _jornada(ledger, user_operario.id, obra_activa.id, hoy, time(8, 0), time(17, 0))
        registro = proyectar_dia(user_operario.id, hoy)
        ledger.commit()

        assert registro.estado == 'Resuelto_Movido'
        assert registro.notas_resolucion == 'Lo movió RRHH.'
        assert registro.check_in == datetime.combine(hoy, time(8, 0))


class TestComputo:
    """Cálculo de jornada efectiva y estado actual."""

    def test_descuenta_las_pausas(self, ledger, user_operario, obra_activa):
        hoy = date.today()
        for tipo, hora in (
            (EVENTO_ENTRADA, time(8, 0)),
            (EVENTO_PAUSA_INICIO, time(11, 0)),
            (EVENTO_PAUSA_FIN, time(11, 30)),
            (EVENTO_SALIDA, time(17, 0)),
        ):
            registrar_evento(
                user_id=user_operario.id, tipo=tipo, origen=ORIGEN_PWA,
                ocurrido_en=datetime.combine(hoy, hora), fecha_laboral=hoy,
                obra_id=obra_activa.id,
            )
        ledger.commit()

        assert minutos_trabajados(user_operario.id, hoy) == 8 * 60 + 30

    def test_estado_de_la_jornada(self, ledger, user_operario, obra_activa):
        hoy = date.today()

        assert jornada_abierta(user_operario.id, hoy)['estado'] == 'fuera'

        registrar_evento(
            user_id=user_operario.id, tipo=EVENTO_ENTRADA, origen=ORIGEN_PWA,
            ocurrido_en=datetime.combine(hoy, time(8, 0)), fecha_laboral=hoy,
            obra_id=obra_activa.id,
        )
        ledger.commit()
        estado = jornada_abierta(user_operario.id, hoy)
        assert estado['estado'] == 'dentro'
        assert estado['obra_id'] == obra_activa.id

        registrar_evento(
            user_id=user_operario.id, tipo=EVENTO_PAUSA_INICIO, origen=ORIGEN_PWA,
            ocurrido_en=datetime.combine(hoy, time(11, 0)), fecha_laboral=hoy,
        )
        ledger.commit()
        assert jornada_abierta(user_operario.id, hoy)['estado'] == 'pausa'


class TestConservacion:
    """Los cuatro años que exige la norma."""

    def test_no_se_puede_purgar_dentro_del_plazo(self):
        hoy = date.today()
        assert not puede_purgarse(hoy)
        assert not puede_purgarse(hoy - timedelta(days=365 * ANIOS_CONSERVACION_FICHAJES - 1))

    def test_se_puede_purgar_pasado_el_plazo(self):
        hoy = date.today()
        assert puede_purgarse(hoy - timedelta(days=365 * ANIOS_CONSERVACION_FICHAJES + 60))
