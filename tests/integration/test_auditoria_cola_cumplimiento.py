"""Auditoría de fichajes: cola de casos, cumplimiento, historial y página."""
from datetime import datetime, time, timedelta

from sqlalchemy import text

from app.models import Obra, RegistroFichaje
from app.utils.timezone_utils import today_local


def _activar_auditoria(session, tenant):
    mods = dict(tenant.modulos_activos or {})
    mods['odoo'] = True
    tenant.modulos_activos = mods
    session.add(tenant)
    session.commit()


def _obra(session, nombre, codigo, jefe):
    o = Obra(nombre=nombre, codigo=codigo, estado='En Curso', jefe_obra_id=jefe.id, is_deleted=False)
    session.add(o)
    session.flush()
    return o


def _reg(session, user, dia, estado, plan=None, real=None, notas=None):
    r = RegistroFichaje(
        user_id=user.id,
        fecha=dia,
        estado=estado,
        obra_planificada_id=plan.id if plan else None,
        obra_real_id=real.id if real else None,
        check_in=datetime.combine(dia, time(7, 0)) if real else None,
        notas_resolucion=notas,
    )
    session.add(r)
    session.flush()
    return r


class TestCumplimiento:

    def test_agrega_cumplimiento_sin_planificar_y_correcciones(
        self, session, tenant_soltec, user_operario, user_jefe, user_admin,
    ):
        from app.services.auditoria_cumplimiento_service import calcular_cumplimiento

        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        hoy = today_local()
        a = _obra(session, 'Obra A', 'A-1', user_jefe)
        b = _obra(session, 'Obra B', 'B-1', user_admin)

        _reg(session, user_operario, hoy - timedelta(days=2), 'Correcto', a, a)
        _reg(session, user_operario, hoy - timedelta(days=3), 'Retraso', a, a)
        _reg(session, user_operario, hoy - timedelta(days=4), 'Falta', a, None)
        _reg(session, user_operario, hoy - timedelta(days=5), 'Paracaidista', None, b)
        _reg(session, user_operario, hoy - timedelta(days=6), 'Aceptado_Odoo', None, b)
        _reg(
            session, user_operario, hoy - timedelta(days=7), 'Sobreescrito_RRHH', None, b,
            notas=f'{a.id}||A-1||Obra A||{b.id}||B-1||Obra B||Modificado de Obra||Correcto',
        )
        # El día en curso no cuenta.
        _reg(session, user_operario, hoy, 'Falta', a, None)
        session.commit()

        d = calcular_cumplimiento(hoy - timedelta(days=28), hoy, scope_clause=None, hoy=hoy)
        k = d['kpis']
        assert k['planificados'] == 3
        assert k['cumplimiento'] == 66.7
        assert k['faltas'] == 1
        assert k['sin_planificar'] == 2
        assert k['correcciones'] == 2

        por_jefe = {j['jefe_id']: j for j in d['jefes']}
        assert por_jefe[user_jefe.id]['planificados'] == 3
        assert por_jefe[user_jefe.id]['correcciones'] == 1
        assert por_jefe[user_jefe.id]['faltas'] == 1
        assert por_jefe[user_admin.id]['sin_planificar'] == 2
        assert sum(d['serie']['cambio_obra']) == 1
        assert sum(d['serie']['alta_no_planificada']) == 1
        assert d['personas'][0]['faltas'] == 1


class TestColaYPagina:

    def _escenario(self, session, user_operario, user_jefe):
        hoy = today_local()
        a = _obra(session, 'Obra A', 'A-1', user_jefe)
        b = _obra(session, 'Obra B', 'B-1', user_jefe)
        ayer = hoy - timedelta(days=1)
        no_ficho = _reg(session, user_operario, ayer, 'Ausencia', a, None)
        sin_plan = _reg(session, user_operario, hoy - timedelta(days=2), 'Paracaidista', None, b)
        otra = _reg(session, user_operario, hoy - timedelta(days=3), 'Conflicto', a, b)
        aviso = _reg(session, user_operario, hoy, 'Ausencia', a, None)
        session.commit()
        return hoy, no_ficho, sin_plan, otra, aviso

    def test_cola_un_caso_por_fila_y_hoy_es_aviso(
        self, session, tenant_soltec, user_operario, user_jefe, user_admin,
    ):
        from app.services import auditoria_casos_service as acs
        from app.services.desvio_fichaje_service import enriquecer_pendientes_desvio

        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        hoy, no_ficho, sin_plan, otra, aviso = self._escenario(session, user_operario, user_jefe)

        pendientes = RegistroFichaje.query.filter(
            RegistroFichaje.estado.in_(acs.ESTADOS_PENDIENTES),
        ).all()
        pendientes = enriquecer_pendientes_desvio(pendientes, user_admin)
        cola = acs.construir_cola(pendientes, user_admin, hoy=hoy, puede_resolver=True)

        tipos = {c['id']: c['tipo'] for c in cola['casos']}
        assert tipos == {
            no_ficho.id: acs.TIPO_NO_FICHO,
            sin_plan.id: acs.TIPO_SIN_PLANIFICAR,
            otra.id: acs.TIPO_OTRA_OBRA,
        }
        assert [a['id'] for a in cola['avisos_hoy']] == [aviso.id]

        acciones = {c['id']: [a['accion'] for a in c['acciones']] for c in cola['casos']}
        assert acciones[no_ficho.id] == ['confirmar_ausencia', 'borrar_planificacion']
        assert acciones[sin_plan.id] == ['anadir']
        assert acciones[otra.id], 'el desvío debe ofrecer al menos una acción a la oficina'

        # Solo consulta: ninguna acción.
        cola_ro = acs.construir_cola(pendientes, user_admin, hoy=hoy, puede_resolver=False)
        assert all(not c['acciones'] for c in cola_ro['casos'])

    def test_pagina_y_endpoints(
        self, session, tenant_soltec, user_operario, user_jefe, user_admin, authenticated_client,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        _activar_auditoria(session, tenant_soltec)
        hoy, no_ficho, sin_plan, otra, aviso = self._escenario(session, user_operario, user_jefe)
        _reg(session, user_operario, hoy - timedelta(days=9), 'Resuelto_Falta',
             session.query(Obra).filter_by(codigo='A-1').first(), None)
        _reg(session, user_operario, hoy - timedelta(days=10), 'Correcto',
             session.query(Obra).filter_by(codigo='A-1').first(),
             session.query(Obra).filter_by(codigo='A-1').first())
        session.commit()

        resp = authenticated_client.get('/sync/auditoria')
        assert resp.status_code == 200, resp.data[:300]
        html = resp.get_data(as_text=True)
        assert html.count('data-case-id=') == 3
        assert 'id="audCasosData"' in html and 'id="audDetail"' in html
        # «Hoy en curso» es un desplegable, no un bloque dentro de la lista.
        assert 'id="audHoyBtn"' in html
        assert 'id="audSearch"' in html and 'id="audPeriodo"' in html
        assert '/admin/' in html  # enlaces a ficha de persona / obra
        assert 'Desacuerdo' in html or 'desacuerdo' in html.lower()
        assert 'data-tab="cumplimiento"' in html and 'data-tab="historial"' in html
        assert 'Hoy en curso' in html

        cola = authenticated_client.get('/sync/auditoria/cola').get_json()
        assert cola['success'] and cola['count'] == 3 and cola['avisos'] == 1

        # Historial: oculta lo automático salvo que se pida; la decisión manual sale con «Reabrir».
        hist = authenticated_client.get('/sync/auditoria/historial').get_json()
        assert hist['success'] and hist['total'] == 1
        assert 'js-aud-reabrir' in hist['html']
        con_auto = authenticated_client.get('/sync/auditoria/historial?incluir_auto=1').get_json()
        assert con_auto['total'] == 2
        solo_auto = authenticated_client.get('/sync/auditoria/historial?origen=auto').get_json()
        assert solo_auto['total'] == 1

        cump = authenticated_client.get('/sync/auditoria/cumplimiento').get_json()
        assert cump['success'] and cump['kpis']['planificados'] >= 1

        # Enlace antiguo con registro_id que ya no está pendiente → pestaña historial.
        viejo = authenticated_client.get(
            f'/sync/auditoria?seccion=historial&registro_id={no_ficho.id}',
        )
        assert viejo.status_code == 200
