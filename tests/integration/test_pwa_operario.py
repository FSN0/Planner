# tests/integration/test_pwa_operario.py
#
# La PWA de fichaje del trabajador. Lo que se comprueba aquí no es que la
# pantalla se pinte, sino tres cosas que, si fallan, hacen daño de verdad:
#
#   1. Activar el módulo es lo único que abre el login a los operarios. Si un
#      tenant no lo ha pedido, esas cuentas siguen sin poder entrar.
#   2. Lo que se ficha acaba en el libro inalterable, con su origen, y no en
#      una tabla que alguien pueda editar luego.
#   3. El trabajador ve sus horas y solo las suyas.

import json
from datetime import date

import pytest
from sqlalchemy import text

from app.models import (
    EVENTO_ENTRADA,
    EVENTO_PAUSA_FIN,
    EVENTO_PAUSA_INICIO,
    EVENTO_SALIDA,
    ORIGEN_PWA,
    Asignacion,
    FichajeEvento,
    Obra,
    RegistroFichaje,
)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _configurar(session, **claves):
    """Escribe configuración en el esquema del tenant que esté activo."""
    for clave, valor in claves.items():
        session.execute(
            text(
                'INSERT INTO configuracion_global (clave, valor) VALUES (:c, :v) '
                'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
            ),
            {'c': clave, 'v': str(valor)},
        )
    session.commit()


def _fichar(cliente, tipo, **extra):
    cuerpo = dict(tipo=tipo, **extra)
    return cliente.post(
        '/mi/fichar',
        data=json.dumps(cuerpo),
        content_type='application/json',
    )


def _entrar(cliente, email='operario@test.com', password='operario123'):
    return cliente.post('/auth/login', data={'email': email, 'password': password})


@pytest.fixture
def pwa(session, tenant_soltec, company_internal,
        user_admin, user_jefe, user_operario, obra_activa):
    """
    Deja el tenant con el fichaje móvil activado y el libro vacío.

    Depende de todas las fixtures de datos aunque no use sus valores: cada una
    devuelve el search_path a 'public' al terminar, así que esta tiene que
    ejecutarse la última para que las escrituras caigan en el esquema correcto.
    """
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    session.execute(text('ALTER TABLE fichajes_eventos DISABLE TRIGGER USER'))
    session.execute(text('DELETE FROM fichajes_eventos'))
    session.execute(text('ALTER TABLE fichajes_eventos ENABLE TRIGGER USER'))
    _configurar(session, fichaje_operario_activo='True')
    yield session


@pytest.fixture
def operario_conectado(pwa, tenant_client):
    respuesta = _entrar(tenant_client)
    assert respuesta.status_code in (200, 302)
    return tenant_client


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------

class TestAcceso:

    def test_operario_no_entra_si_el_modulo_esta_apagado(
        self, session, tenant_soltec, company_internal,
        user_admin, user_jefe, user_operario, obra_activa, tenant_client
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        _configurar(session, fichaje_operario_activo='False')

        respuesta = _entrar(tenant_client)

        assert respuesta.status_code == 200
        assert 'no tiene acceso' in respuesta.get_data(as_text=True)

    def test_sin_configuracion_ninguna_el_operario_sigue_bloqueado(
        self, session, tenant_soltec, company_internal,
        user_admin, user_jefe, user_operario, obra_activa, tenant_client
    ):
        """El valor por defecto no puede ser 'abierto': se falla hacia cerrado."""
        respuesta = _entrar(tenant_client)

        assert 'no tiene acceso' in respuesta.get_data(as_text=True)

    def test_operario_entra_y_aterriza_en_su_area(self, operario_conectado):
        respuesta = operario_conectado.get('/mi/', follow_redirects=True)

        assert respuesta.status_code == 200
        assert 'Entrar' in respuesta.get_data(as_text=True)

    def test_sin_sesion_no_se_ficha(self, pwa, tenant_client):
        respuesta = _fichar(tenant_client, EVENTO_ENTRADA)

        assert respuesta.status_code in (302, 401)
        if respuesta.status_code == 302:
            assert '/mi/entrar' in (respuesta.location or '')

    def test_el_manifiesto_lleva_el_nombre_de_la_empresa(self, operario_conectado):
        datos = operario_conectado.get('/mi/manifest.webmanifest').get_json()

        assert 'SOLTEC' in datos['name']
        assert datos['start_url'] == '/mi/'

    def test_el_service_worker_declara_su_alcance(self, operario_conectado):
        respuesta = operario_conectado.get('/mi/sw.js')

        assert respuesta.status_code == 200
        assert respuesta.headers['Service-Worker-Allowed'] == '/mi/'
        assert 'no-store' in respuesta.headers['Cache-Control']


# ---------------------------------------------------------------------------
# Fichar
# ---------------------------------------------------------------------------

class TestFichar:

    def test_jornada_completa(self, operario_conectado, obra_activa, user_operario):
        assert _fichar(
            operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id
        ).get_json()['estado'] == 'dentro'
        assert _fichar(operario_conectado, EVENTO_PAUSA_INICIO).get_json()['estado'] == 'pausa'
        assert _fichar(operario_conectado, EVENTO_PAUSA_FIN).get_json()['estado'] == 'dentro'
        assert _fichar(operario_conectado, EVENTO_SALIDA).get_json()['estado'] == 'fuera'

        tipos = [
            e.tipo for e in FichajeEvento.query
            .filter_by(user_id=user_operario.id)
            .order_by(FichajeEvento.secuencia).all()
        ]
        assert tipos == [
            EVENTO_ENTRADA, EVENTO_PAUSA_INICIO, EVENTO_PAUSA_FIN, EVENTO_SALIDA
        ]

    def test_el_evento_queda_marcado_como_fichaje_propio_desde_la_pwa(
        self, operario_conectado, obra_activa, user_operario
    ):
        _fichar(operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id)

        evento = FichajeEvento.query.filter_by(user_id=user_operario.id).one()
        assert evento.origen == ORIGEN_PWA
        # El autor es el propio trabajador: nadie ha fichado por él.
        assert evento.autor_id == user_operario.id
        assert evento.motivo is None
        assert evento.hash

    def test_fichar_actualiza_la_proyeccion_del_dia(
        self, operario_conectado, obra_activa, user_operario
    ):
        _fichar(operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id)
        _fichar(operario_conectado, EVENTO_SALIDA)

        registro = RegistroFichaje.query.filter_by(
            user_id=user_operario.id, fecha=date.today()
        ).one()
        assert registro.check_in is not None
        assert registro.check_out is not None
        assert registro.obra_real_id == obra_activa.id

    def test_no_se_entra_dos_veces(self, operario_conectado, obra_activa):
        _fichar(operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id)
        respuesta = _fichar(operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id)

        assert respuesta.status_code == 400
        assert 'ya tienes' in respuesta.get_json()['error'].lower()

    def test_no_se_sale_sin_haber_entrado(self, operario_conectado):
        respuesta = _fichar(operario_conectado, EVENTO_SALIDA)

        assert respuesta.status_code == 400
        assert FichajeEvento.query.count() == 0

    def test_la_entrada_exige_obra(self, operario_conectado):
        respuesta = _fichar(operario_conectado, EVENTO_ENTRADA)

        assert respuesta.status_code == 400
        assert 'obra' in respuesta.get_json()['error'].lower()

    def test_la_salida_hereda_la_obra_de_la_entrada(
        self, operario_conectado, obra_activa, user_operario
    ):
        _fichar(operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id)
        _fichar(operario_conectado, EVENTO_SALIDA)

        salida = FichajeEvento.query.filter_by(tipo=EVENTO_SALIDA).one()
        assert salida.obra_id == obra_activa.id

    def test_un_tipo_inventado_se_rechaza(self, operario_conectado, obra_activa):
        respuesta = _fichar(operario_conectado, 'teletransporte', obra_id=obra_activa.id)

        assert respuesta.status_code == 400
        assert FichajeEvento.query.count() == 0

    def test_no_se_puede_fichar_por_la_pwa_como_anulacion(
        self, operario_conectado, obra_activa
    ):
        """Anular es cosa de administración, no un botón del trabajador."""
        respuesta = _fichar(operario_conectado, 'anulacion', obra_id=obra_activa.id)

        assert respuesta.status_code == 400
        assert FichajeEvento.query.count() == 0


# ---------------------------------------------------------------------------
# Ubicación
# ---------------------------------------------------------------------------

class TestUbicacion:

    def test_apagada_descarta_las_coordenadas_aunque_lleguen(
        self, pwa, operario_conectado, obra_activa
    ):
        _fichar(
            operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id,
            latitud=41.65, longitud=-4.72, precision_metros=8,
        )

        evento = FichajeEvento.query.one()
        assert evento.latitud is None
        assert evento.longitud is None

    def test_opcional_guarda_lo_que_llegue_y_deja_fichar_sin_ello(
        self, pwa, operario_conectado, obra_activa
    ):
        _configurar(pwa, fichaje_geolocalizacion='opcional')

        _fichar(
            operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id,
            latitud=41.65, longitud=-4.72, precision_metros=8,
        )
        assert _fichar(operario_conectado, EVENTO_SALIDA).status_code == 200

        entrada = FichajeEvento.query.filter_by(tipo=EVENTO_ENTRADA).one()
        assert entrada.latitud == pytest.approx(41.65)
        assert entrada.precision_metros == pytest.approx(8)

        salida = FichajeEvento.query.filter_by(tipo=EVENTO_SALIDA).one()
        assert salida.latitud is None

    def test_obligatoria_rechaza_el_fichaje_sin_coordenadas(
        self, pwa, operario_conectado, obra_activa
    ):
        _configurar(pwa, fichaje_geolocalizacion='obligatoria')

        respuesta = _fichar(operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id)

        assert respuesta.status_code == 400
        assert 'ubicación' in respuesta.get_json()['error'].lower()
        assert FichajeEvento.query.count() == 0

    def test_un_valor_de_configuracion_corrupto_no_activa_la_geolocalizacion(
        self, pwa, operario_conectado, obra_activa
    ):
        """Ante un valor que no se reconoce, se elige la opción menos invasiva."""
        _configurar(pwa, fichaje_geolocalizacion='sí, claro')

        respuesta = _fichar(
            operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id,
            latitud=41.65, longitud=-4.72,
        )

        assert respuesta.status_code == 200
        assert FichajeEvento.query.one().latitud is None


# ---------------------------------------------------------------------------
# Obras ofrecidas
# ---------------------------------------------------------------------------

class TestObras:

    def test_la_obra_planificada_aparece_primero(
        self, pwa, operario_conectado, obra_activa, user_operario
    ):
        pwa.add(Asignacion(
            obra_id=obra_activa.id, user_id=user_operario.id, fecha=date.today()
        ))
        pwa.commit()

        html = operario_conectado.get('/mi/').get_data(as_text=True)

        assert 'Tu planificación de hoy' in html
        assert obra_activa.nombre in html

    def test_sin_planificacion_se_avisa_pero_se_deja_fichar(
        self, operario_conectado, obra_activa, user_operario
    ):
        """
        En obra mandan a la gente a tajos no previstos. Impedir el fichaje
        provocaría que no fichasen, que es peor. Tras fichar, el tablero lo
        refleja como asignación (planificado = fichado).
        """
        html = operario_conectado.get('/mi/').get_data(as_text=True)
        assert 'no tienes obra planificada' in html.lower()

        respuesta = _fichar(operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id)
        assert respuesta.status_code == 200
        assert Asignacion.query.filter_by(
            user_id=user_operario.id,
            obra_id=obra_activa.id,
            fecha=date.today(),
        ).first() is not None
        registro = RegistroFichaje.query.filter_by(
            user_id=user_operario.id, fecha=date.today()
        ).one()
        assert registro.estado == 'Paracaidista'
        assert registro.obra_real_id == obra_activa.id

    def test_fichar_mueve_si_ya_estaba_en_otra_obra(
        self, pwa, operario_conectado, obra_activa, user_operario
    ):
        otra = Obra(
            nombre='Otra obra test',
            estado='En Curso',
            codigo='OTRA-TEST',
        )
        pwa.add(otra)
        pwa.flush()
        pwa.add(Asignacion(
            obra_id=otra.id, user_id=user_operario.id, fecha=date.today()
        ))
        pwa.commit()

        assert _fichar(
            operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id
        ).status_code == 200

        assert Asignacion.query.filter_by(
            user_id=user_operario.id, obra_id=obra_activa.id, fecha=date.today()
        ).first() is not None
        assert Asignacion.query.filter_by(
            user_id=user_operario.id, obra_id=otra.id, fecha=date.today()
        ).first() is None

    def test_una_obra_que_no_existe_se_rechaza(self, operario_conectado):
        respuesta = _fichar(operario_conectado, EVENTO_ENTRADA, obra_id=999999)

        assert respuesta.status_code == 400
        assert FichajeEvento.query.count() == 0


# ---------------------------------------------------------------------------
# Consulta de las propias horas
# ---------------------------------------------------------------------------

class TestMisHoras:

    def test_el_trabajador_ve_sus_horas(
        self, operario_conectado, obra_activa
    ):
        _fichar(operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id)
        _fichar(operario_conectado, EVENTO_SALIDA)

        html = operario_conectado.get('/mi/registros').get_data(as_text=True)

        assert respuesta_contiene_fecha_de_hoy(html)
        assert obra_activa.nombre in html

    def test_no_ve_los_fichajes_de_otro(
        self, pwa, operario_conectado, obra_activa, user_jefe
    ):
        from app.services.fichaje_ledger_service import registrar_evento

        registrar_evento(
            user_id=user_jefe.id, tipo=EVENTO_ENTRADA, origen=ORIGEN_PWA,
            obra_id=obra_activa.id, fecha_laboral=date.today(),
        )
        pwa.commit()

        html = operario_conectado.get('/mi/registros').get_data(as_text=True)

        assert 'No hay registros en este periodo' in html

    def test_puede_descargarse_su_registro(self, operario_conectado, obra_activa):
        _fichar(operario_conectado, EVENTO_ENTRADA, obra_id=obra_activa.id)
        _fichar(operario_conectado, EVENTO_SALIDA)

        respuesta = operario_conectado.get('/mi/registros.csv')
        texto = respuesta.get_data(as_text=True)

        assert respuesta.status_code == 200
        assert 'attachment' in respuesta.headers['Content-Disposition']
        assert 'Total horas' in texto
        assert '44444444D' in texto

    def test_consultar_las_propias_horas_no_depende_del_modulo(
        self, pwa, operario_conectado
    ):
        """
        Consultar el registro propio es un derecho del trabajador, no una
        función que la empresa contrate: no se apaga con el módulo.
        """
        _configurar(pwa, fichaje_operario_activo='False')

        respuesta = operario_conectado.get('/mi/registros')

        assert respuesta.status_code == 200
        assert 'Mis horas' in respuesta.get_data(as_text=True)

    def test_con_el_modulo_apagado_la_pantalla_de_fichar_lo_explica(
        self, pwa, operario_conectado
    ):
        _configurar(pwa, fichaje_operario_activo='False')

        html = operario_conectado.get('/mi/').get_data(as_text=True)

        assert 'no está activado' in html

    def test_un_rango_de_fechas_absurdo_no_rompe_la_pantalla(self, operario_conectado):
        respuesta = operario_conectado.get('/mi/registros?desde=manzana&hasta=1')

        assert respuesta.status_code == 200


def respuesta_contiene_fecha_de_hoy(html):
    return date.today().strftime('%d/%m/%Y') in html
