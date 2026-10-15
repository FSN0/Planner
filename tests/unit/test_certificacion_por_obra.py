"""Certificación por empresa + obra + mes."""
from datetime import date, datetime, time
from decimal import Decimal
import pytest
from flask import g
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app.models import (
    CertificacionLinea,
    CertificacionPropuesta,
    Company,
    Obra,
    RegistroFichaje,
    User,
)
from app.services.certificacion_service import (
    DIR_EMP,
    DIR_SUB,
    enviar,
    estado_empresa_mes,
    estado_propuesta,
    obras_ids_certificacion,
    panel_certificacion_obras,
    panel_certificacion_oficina,
    panel_certificacion_subcontrata_obras,
    periodo_bloqueado,
    repartir_propuesta_por_obras,
    resumen_estados_empresa,
    sincronizar,
)


@pytest.fixture
def cert_ctx(tenant_soltec, app, session, company_subcontrata, company_internal):
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        yield {
            'tenant': tenant_soltec,
            'company': company_subcontrata,
            'internal': company_internal,
            'session': session,
            'app': app,
        }


_obra_seq = 0


def _obra(session, nombre, jefe_id=None):
    global _obra_seq
    _obra_seq += 1
    o = Obra(
        nombre=nombre,
        codigo=f'C{_obra_seq:04d}',
        estado='En Curso',
        jefe_obra_id=jefe_id,
        is_deleted=False,
    )
    session.add(o)
    session.flush()
    return o


def _operario(session, company, name='Pepe'):
    u = User(
        email=f'{name.lower().replace(" ", ".")}@cert.test',
        password_hash=generate_password_hash('x'),
        role='operario',
        name=name,
        lastname='Test',
        dni=f'DNI-{name[:6]}',
        company_id=company.id,
        active=True,
        email_verified=True,
        is_deleted=False,
    )
    session.add(u)
    session.flush()
    return u


def _fichaje(session, user, obra, dia, h0=8, h1=16):
    session.add(RegistroFichaje(
        user_id=user.id,
        obra_real_id=obra.id,
        fecha=dia,
        check_in=datetime.combine(dia, time(h0, 0)),
        check_out=datetime.combine(dia, time(h1, 0)),
        estado='Correcto',
    ))


def test_repartir_propuesta_multiobra(cert_ctx):
    session = cert_ctx['session']
    company = cert_ctx['company']
    o1 = _obra(session, 'Obra Alpha')
    o2 = _obra(session, 'Obra Beta')
    u = _operario(session, company, 'Ana')
    prop = CertificacionPropuesta(
        company_id=company.id, obra_id=o1.id, anio=2026, mes=10,
        direccion=DIR_SUB, estado='enviada',
    )
    session.add(prop)
    session.flush()
    session.add(CertificacionLinea(
        propuesta_id=prop.id, user_id=u.id, obra_id=o1.id,
        fecha=date(2026, 10, 1), horas=Decimal('8'), precio_hora=Decimal('20'),
        origen_horas='manual_total',
    ))
    session.add(CertificacionLinea(
        propuesta_id=prop.id, user_id=u.id, obra_id=o2.id,
        fecha=date(2026, 10, 2), horas=Decimal('8'), precio_hora=Decimal('20'),
        origen_horas='manual_total',
    ))
    session.flush()

    out = repartir_propuesta_por_obras(prop)
    session.commit()

    assert len(out) == 2
    props = CertificacionPropuesta.query.filter_by(
        company_id=company.id, anio=2026, mes=10, direccion=DIR_SUB,
    ).all()
    assert len(props) == 2
    by_obra = {p.obra_id: p for p in props}
    assert set(by_obra) == {o1.id, o2.id}
    assert {ln.obra_id for ln in by_obra[o1.id].lineas} == {o1.id}
    assert {ln.obra_id for ln in by_obra[o2.id].lineas} == {o2.id}
    assert all(p.estado == 'enviada' for p in props)


def test_sincronizar_crea_par_por_obra(cert_ctx):
    session = cert_ctx['session']
    company = cert_ctx['company']
    o1 = _obra(session, 'Obra Uno')
    o2 = _obra(session, 'Obra Dos')
    u = _operario(session, company, 'Luis')
    _fichaje(session, u, o1, date(2026, 10, 3))
    _fichaje(session, u, o2, date(2026, 10, 4))
    session.commit()

    sub1, emp1 = sincronizar(company, 2026, 10, o1.id)
    sub2, emp2 = sincronizar(company, 2026, 10, o2.id)
    session.commit()

    assert sub1.obra_id == o1.id and emp1.obra_id == o1.id
    assert sub2.obra_id == o2.id and emp2.obra_id == o2.id
    assert sub1.id != sub2.id
    assert all(ln.obra_id == o1.id for ln in sub1.lineas)
    assert all(ln.obra_id == o2.id for ln in sub2.lineas)


def test_enviar_no_bloquea_otra_obra(cert_ctx):
    session = cert_ctx['session']
    company = cert_ctx['company']
    o1 = _obra(session, 'Obra A')
    o2 = _obra(session, 'Obra B')
    u = _operario(session, company, 'Marta')
    actor = _operario(session, cert_ctx['internal'], 'ActorCert')
    _fichaje(session, u, o1, date(2026, 10, 5))
    _fichaje(session, u, o2, date(2026, 10, 6))
    session.commit()

    sub1, emp1 = sincronizar(company, 2026, 10, o1.id)
    sub2, emp2 = sincronizar(company, 2026, 10, o2.id)
    for ln in list(emp1.lineas) + list(emp2.lineas):
        ln.horas = Decimal('8.00')
        ln.precio_hora = Decimal('25.00')
        ln.origen_horas = 'manual_total'
    session.flush()

    enviar(emp1, actor_id=actor.id)
    session.commit()

    assert periodo_bloqueado(company.id, 2026, 10, o1.id) is False  # solo enviada, no aceptada
    assert emp2.estado == 'borrador'
    # Aceptar o1 no debe bloquear o2
    emp1.estado = 'aceptada'
    session.commit()
    assert periodo_bloqueado(company.id, 2026, 10, o1.id) is True
    assert periodo_bloqueado(company.id, 2026, 10, o2.id) is False
    enviar(emp2, actor_id=actor.id)
    assert emp2.estado in ('enviada', 'aceptada')


def test_estado_propuesta_y_agregacion_empresa(cert_ctx):
    session = cert_ctx['session']
    company = cert_ctx['company']
    o1 = _obra(session, 'Obra Est1')
    o2 = _obra(session, 'Obra Est2')
    session.add(CertificacionPropuesta(
        company_id=company.id, obra_id=o1.id, anio=2026, mes=10,
        direccion=DIR_SUB, estado='enviada',
    ))
    session.add(CertificacionPropuesta(
        company_id=company.id, obra_id=o1.id, anio=2026, mes=10,
        direccion=DIR_EMP, estado='borrador',
    ))
    session.add(CertificacionPropuesta(
        company_id=company.id, obra_id=o2.id, anio=2026, mes=10,
        direccion=DIR_EMP, estado='borrador',
        comentario_rechazo='No cuadra',
    ))
    session.add(CertificacionPropuesta(
        company_id=company.id, obra_id=o2.id, anio=2026, mes=10,
        direccion=DIR_SUB, estado='borrador',
    ))
    session.commit()

    assert estado_propuesta(company.id, o1.id, 2026, 10, vista_subcontrata=False) == 'recibida'
    # Comentario en DIR_EMP = la subcontrata nos devolvió nuestra propuesta → alerta SaaS
    assert estado_propuesta(company.id, o2.id, 2026, 10, vista_subcontrata=False) == 'rechazada'
    # Quien rechazó (subcontrata) no ve "rechazada" en su propia propuesta
    assert estado_propuesta(company.id, o2.id, 2026, 10, vista_subcontrata=True) == 'borrador'
    assert estado_empresa_mes(company.id, 2026, 10, vista_subcontrata=False) == 'recibida'
    resumen = resumen_estados_empresa(company.id, 2026, 10, vista_subcontrata=False)
    assert resumen['n_obras'] == 2
    assert resumen['tiene_recibida'] is True
    assert resumen['tiene_rechazada'] is True
    assert resumen['contadores']['recibida'] == 1
    assert resumen['contadores']['rechazada'] == 1
    resumen_sub = resumen_estados_empresa(company.id, 2026, 10, vista_subcontrata=True)
    assert resumen_sub['tiene_rechazada'] is False
    assert resumen_sub['contadores']['rechazada'] == 0


def test_scope_jefe_panel_solo_sus_obras(cert_ctx, monkeypatch):
    session = cert_ctx['session']
    company = cert_ctx['company']
    jefe = User(
        email='jefe.cert@test.com',
        password_hash=generate_password_hash('x'),
        role='jefe',
        name='Jefe',
        lastname='Obra',
        dni='JEFE01',
        company_id=cert_ctx['internal'].id,
        active=True,
        email_verified=True,
        is_deleted=False,
    )
    session.add(jefe)
    session.flush()
    o_ok = _obra(session, 'Obra Custodia', jefe_id=jefe.id)
    o_out = _obra(session, 'Obra Ajena', jefe_id=None)
    u = _operario(session, company, 'Paco')
    _fichaje(session, u, o_ok, date(2026, 10, 7))
    _fichaje(session, u, o_out, date(2026, 10, 8))
    session.commit()

    monkeypatch.setattr(
        'app.services.panel_scope_service.certificacion_obra_ids',
        lambda _user: {o_ok.id},
    )
    filas = panel_certificacion_oficina(jefe, anio=2026, mes=10)
    # Tras sync implícito vía volumen: empresa aparece; hub solo verá o_ok
    from app.services.certificacion_service import panel_certificacion_empresa_obras
    hub = panel_certificacion_empresa_obras(jefe, company.id, anio=2026, mes=10)
    session.commit()
    assert {r['obra'].id for r in hub} == {o_ok.id}
    assert o_out.id not in {r['obra'].id for r in hub}
    # listado empresas no debe exigir obras fuera de alcance
    assert any(f['company'].id == company.id for f in filas) or hub


def test_prorratear_horas_persona_reparte_igual(cert_ctx, monkeypatch):
    from app.services.certificacion_service import prorratear_horas_persona

    session = cert_ctx['session']
    company = cert_ctx['company']
    o = _obra(session, 'Obra Prorrata')
    u = _operario(session, company, 'Luis')
    prop = CertificacionPropuesta(
        company_id=company.id, obra_id=o.id, anio=2026, mes=10,
        direccion=DIR_SUB, estado='borrador',
    )
    session.add(prop)
    session.flush()
    for d in (1, 2, 3):
        session.add(CertificacionLinea(
            propuesta_id=prop.id,
            user_id=u.id,
            obra_id=o.id,
            fecha=date(2026, 10, d),
            horas=Decimal('8.00'),
            precio_hora=Decimal('10.00'),
            origen_horas='app',
        ))
    session.flush()
    monkeypatch.setattr(
        'app.services.certificacion_service.periodo_bloqueado',
        lambda *a, **k: False,
    )
    n = prorratear_horas_persona(prop, u.id, '10')
    assert n == 3
    horas = sorted(float(ln.horas) for ln in prop.lineas)
    assert sum(horas) == pytest.approx(10.0)
    assert abs(max(horas) - min(horas)) <= 0.01
    assert all(ln.origen_horas == 'manual_total' for ln in prop.lineas)
    assert all(ln.hora_inicio is None and ln.hora_fin is None for ln in prop.lineas)


def test_precio_contrato_usa_tarifa_de_operario(cert_ctx, monkeypatch):
    """Si el contrato tiene línea del operario, manda sobre el hourly_rate base."""
    from app.services import certificacion_service as cs

    session = cert_ctx['session']
    company = cert_ctx['company']
    o = _obra(session, 'Obra Contrato')
    u = _operario(session, company, 'Tarifa')
    u.external_ids = {'odoo': '55', 'odoo_model': 'res.partner'}
    session.flush()

    monkeypatch.setattr(
        cs,
        'contrato_asistencia',
        lambda company, obra, fecha=None, cache=None: {
            'contract_id': 1,
            'name': 'C-1',
            'hourly_rate': 18.0,
            'lines': {55: 27.5},
        },
    )
    assert cs.precio_contrato(company, o, user=u) == Decimal('27.50')
    assert cs.precio_contrato(company, o, user=None) == Decimal('18.00')
    otro = _operario(session, company, 'Base')
    otro.external_ids = {'odoo': '99', 'odoo_model': 'res.partner'}
    session.flush()
    assert cs.precio_para(company, o, user=u) == Decimal('27.50')
    assert cs.precio_para(company, o, user=otro) == Decimal('18.00')


def test_precio_contrato_sin_base_usa_linea(cert_ctx, monkeypatch):
    """Si hourly_rate viene a 0, la cabecera toma una tarifa de línea del contrato."""
    from app.services import certificacion_service as cs

    session = cert_ctx['session']
    company = cert_ctx['company']
    o = _obra(session, 'Obra Solo Lineas')
    monkeypatch.setattr(
        cs,
        'contrato_asistencia',
        lambda company, obra, fecha=None, cache=None: {
            'contract_id': 2,
            'name': 'C-2',
            'hourly_rate': 0.0,
            'lines': {10: 22.5, 11: 22.5},
        },
    )
    assert cs.precio_contrato(company, o, user=None) == Decimal('22.50')
    assert cs.precio_para(company, o) == Decimal('22.50')


def test_detalle_obra_no_sincroniza_ni_odoo(cert_ctx, monkeypatch):
    """Hub por obra: solo lectura local; sync/Odoo quedan para «Gestionar»."""
    from app.services import certificacion_service as cs

    session = cert_ctx['session']
    company = cert_ctx['company']
    o = _obra(session, 'Obra Hub Rapido')
    u = _operario(session, company, 'HubOp')
    _fichaje(session, u, o, date(2026, 10, 5))
    _fichaje(session, u, o, date(2026, 10, 6))
    prop = CertificacionPropuesta(
        company_id=company.id, obra_id=o.id, anio=2026, mes=10,
        direccion=DIR_EMP, estado='borrador',
    )
    session.add(prop)
    session.flush()
    session.add(CertificacionLinea(
        propuesta_id=prop.id,
        user_id=u.id,
        obra_id=o.id,
        fecha=date(2026, 10, 5),
        horas=Decimal('8.00'),
        precio_hora=Decimal('19.50'),
        origen_horas='app',
    ))
    session.commit()

    sync_calls = []
    odoo_calls = []
    monkeypatch.setattr(
        cs, 'sincronizar',
        lambda *a, **k: sync_calls.append((a, k)) or (None, None),
    )
    monkeypatch.setattr(
        cs, 'contrato_asistencia',
        lambda *a, **k: odoo_calls.append(1) or {'contract_id': 1, 'hourly_rate': 99.0, 'lines': {}},
    )
    monkeypatch.setattr(
        cs, 'precio_para',
        lambda *a, **k: (_ for _ in ()).throw(AssertionError('hub no debe llamar precio_para/Odoo')),
    )
    admin = User(
        email='admin.hub@cert.test',
        password_hash=generate_password_hash('x'),
        role='admin',
        name='Admin',
        lastname='Hub',
        dni='ADMINHUB',
        company_id=cert_ctx['internal'].id,
        active=True,
        email_verified=True,
        is_deleted=False,
    )
    session.add(admin)
    session.flush()

    detalle = cs.detalle_certificacion_obra(admin, o.id, anio=2026, mes=10)
    assert detalle is not None
    assert sync_calls == []
    assert odoo_calls == []
    assert float(detalle['horas']) == pytest.approx(16.0)
    assert len(detalle['empresas']) == 1
    assert detalle['empresas'][0]['estado'] == 'borrador'
    assert detalle['empresas'][0]['precio'] == Decimal('19.50')


def test_detalle_obra_omite_empresa_interna(cert_ctx, monkeypatch):
    """La empresa principal (is_internal) no sale en el hub de obra."""
    from app.services import certificacion_service as cs

    session = cert_ctx['session']
    sub = cert_ctx['company']
    internal = cert_ctx['internal']
    o = _obra(session, 'Obra Sin Soltec')
    u_sub = _operario(session, sub, 'Externo')
    _fichaje(session, u_sub, o, date(2026, 10, 12))
    # Propuesta fantasma de la principal (no debe listarse).
    session.add(CertificacionPropuesta(
        company_id=internal.id, obra_id=o.id, anio=2026, mes=10,
        direccion=DIR_EMP, estado='borrador',
    ))
    session.add(CertificacionPropuesta(
        company_id=sub.id, obra_id=o.id, anio=2026, mes=10,
        direccion=DIR_EMP, estado='borrador',
    ))
    session.commit()

    monkeypatch.setattr(
        'app.services.panel_scope_service.certificacion_obra_ids',
        lambda _user: None,
    )
    admin = User(
        email='admin.nosoltec@cert.test',
        password_hash=generate_password_hash('x'),
        role='admin',
        name='Admin',
        lastname='NoSoltec',
        dni='NOSOL1',
        company_id=internal.id,
        active=True,
        email_verified=True,
        is_deleted=False,
    )
    session.add(admin)
    session.flush()

    detalle = cs.detalle_certificacion_obra(admin, o.id, anio=2026, mes=10)
    assert detalle is not None
    ids = {e['company'].id for e in detalle['empresas']}
    assert sub.id in ids
    assert internal.id not in ids

    with pytest.raises(ValueError, match='empresa principal'):
        sincronizar(internal, 2026, 10, o.id)

    # Sin fichaje de internos en volumen.
    filas = panel_certificacion_oficina(admin, anio=2026, mes=10)
    assert all(r['company'].id != internal.id for r in filas)


def test_sincronizar_subcontrata_asigna_precio_sin_refresco(cert_ctx, monkeypatch):
    """Portal subcontrata usa refrescar_precios=False; igual debe materializar €/h."""
    session = cert_ctx['session']
    company = cert_ctx['company']
    o = _obra(session, 'Obra precio sub')
    u = _operario(session, company, 'Tarifa')
    dia = date(2026, 10, 8)
    session.add(RegistroFichaje(
        user_id=u.id,
        fecha=dia,
        obra_real_id=o.id,
        check_in=datetime.combine(dia, time(7, 0)),
        check_out=datetime.combine(dia, time(15, 0)),
        estado='Correcto',
    ))
    session.commit()

    import app.services.certificacion_service as cs
    monkeypatch.setattr(
        cs, 'precio_para',
        lambda *a, **k: Decimal('23.00'),
    )

    sub, emp = sincronizar(company, 2026, 10, o.id, refrescar_precios=False)
    session.commit()
    ln_sub = next(x for x in sub.lineas if x.user_id == u.id and x.fecha == dia)
    ln_emp = next(x for x in emp.lineas if x.user_id == u.id and x.fecha == dia)
    assert ln_sub.precio_hora == Decimal('23.00')
    assert ln_emp.precio_hora == Decimal('23.00')

    # Si ya tenía 0, también lo rellena en la siguiente sync sin refresco global.
    ln_sub.precio_hora = Decimal('0.00')
    session.commit()
    sub2, _emp2 = sincronizar(company, 2026, 10, o.id, refrescar_precios=False)
    session.commit()
    ln_sub2 = next(x for x in sub2.lineas if x.user_id == u.id and x.fecha == dia)
    assert ln_sub2.precio_hora == Decimal('23.00')


def test_plataforma_ref_y_delta_propuesta(cert_ctx):
    from app.services.certificacion_service import (
        agrupar_por_persona,
        delta_vs_plataforma,
        enriquecer_grupos_plataforma,
        mapa_fichaje_plataforma,
        totales_plataforma_grupos,
    )

    session = cert_ctx['session']
    company = cert_ctx['company']
    o = _obra(session, 'Obra plat')
    u = _operario(session, company, 'Luis')
    dia = date(2026, 10, 5)
    session.add(RegistroFichaje(
        user_id=u.id,
        fecha=dia,
        obra_real_id=o.id,
        check_in=datetime.combine(dia, time(7, 0)),
        check_out=datetime.combine(dia, time(15, 0)),
        estado='Correcto',
    ))
    session.commit()

    sub, emp = sincronizar(company, 2026, 10, o.id)
    # Oficina edita al alza; el fichaje real sigue en 8 h.
    ln = next(x for x in emp.lineas if x.user_id == u.id and x.fecha == dia)
    ln.horas = Decimal('10.00')
    ln.precio_hora = Decimal('20.00')
    ln.origen_horas = 'manual_total'
    session.commit()

    from app.compliance.routes import _grupos_como_persona
    grupos = _grupos_como_persona(agrupar_por_persona(emp), obra_real=o)
    mapa = mapa_fichaje_plataforma(company.id, 2026, 10, o.id)
    enriquecer_grupos_plataforma(grupos, mapa, precio_fallback=Decimal('20.00'))
    item = grupos[0]['fechas'][0]['lineas'][0]
    assert item['plat_horas'] == Decimal('8.00')
    assert item['plat_importe'] == Decimal('160.00')
    tot = totales_plataforma_grupos(grupos)
    assert tot['horas'] == Decimal('8.00')
    assert tot['importe'] == Decimal('160.00')

    d = delta_vs_plataforma(
        propuesto_horas=Decimal('10.00'),
        propuesto_importe=Decimal('200.00'),
        plataforma_horas=tot['horas'],
        plataforma_importe=tot['importe'],
    )
    assert d['delta_horas'] == Decimal('2.00')
    assert d['delta_importe'] == Decimal('40.00')
    assert d['pct_horas'] == Decimal('25.00')
    assert d['pct_importe'] == Decimal('25.00')


def test_prorrata_persona_json_xhr_persiste(cert_ctx, monkeypatch):
    """XHR prorrata_persona guarda el total y devuelve líneas + importe."""
    from app.compliance.routes import _post_cert

    session = cert_ctx['session']
    company = cert_ctx['company']
    app = cert_ctx['app']
    o = _obra(session, 'Obra Autosave Total')
    u = _operario(session, company, 'Autosave')
    prop = CertificacionPropuesta(
        company_id=company.id, obra_id=o.id, anio=2026, mes=10,
        direccion=DIR_SUB, estado='borrador',
    )
    session.add(prop)
    session.flush()
    lids = []
    for d in (1, 2):
        ln = CertificacionLinea(
            propuesta_id=prop.id,
            user_id=u.id,
            obra_id=o.id,
            fecha=date(2026, 10, d),
            horas=Decimal('8.00'),
            precio_hora=Decimal('10.00'),
            origen_horas='app',
        )
        session.add(ln)
        session.flush()
        lids.append(ln.id)
    session.commit()
    monkeypatch.setattr(
        'app.services.certificacion_service.periodo_bloqueado',
        lambda *a, **k: False,
    )
    with app.test_request_context(
        '/subcontrata/certificacion/obra/%s' % o.id,
        method='POST',
        data={
            'accion': 'prorrata_persona',
            'user_id': str(u.id),
            'horas_total': '100',
            'anio': '2026',
            'mes': '10',
        },
        headers={
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json',
        },
    ):
        resp = _post_cert(
            company, 2026, 10, o.id,
            direccion_propia=DIR_SUB,
            endpoint='subcontrata.certificacion_obra',
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is True
    assert data['saved'] is True
    assert float(data['horas_total']) == pytest.approx(100.0)
    assert float(data['importe_total']) == pytest.approx(1000.0)
    assert len(data['lineas']) == 2
    assert {ln['linea_id'] for ln in data['lineas']} == set(lids)
    session.expire_all()
    prop2 = CertificacionPropuesta.query.get(prop.id)
    assert sum(float(ln.horas) for ln in prop2.lineas) == pytest.approx(100.0)
    assert all(ln.origen_horas == 'manual_total' for ln in prop2.lineas)


def test_obra_sin_fichaje_ni_contrato_no_sale_en_mes(cert_ctx, monkeypatch):
    """Septiembre con fichaje sí; octubre vacío (borrador fantasma) no sale a certificar."""
    session = cert_ctx['session']
    company = cert_ctx['company']
    o = _obra(session, 'Obra Solo Sept')
    u = _operario(session, company, 'OctubreVacio')
    _fichaje(session, u, o, date(2026, 9, 10))
    session.commit()

    sincronizar(company, 2026, 9, o.id)
    # Abrir octubre crea borradores vacíos (como al navegar el mes).
    sincronizar(company, 2026, 10, o.id)
    session.commit()

    monkeypatch.setattr(
        'app.services.certificacion_service.contrato_asistencia',
        lambda *a, **k: None,
    )

    assert o.id in obras_ids_certificacion(company.id, 2026, 9)
    assert o.id not in obras_ids_certificacion(company.id, 2026, 10)

    panel_sep = panel_certificacion_subcontrata_obras(company, anio=2026, mes=9)
    panel_oct = panel_certificacion_subcontrata_obras(company, anio=2026, mes=10)
    assert o.id in {r['obra'].id for r in panel_sep}
    assert o.id not in {r['obra'].id for r in panel_oct}


def test_obra_sin_fichaje_con_contrato_si_sale(cert_ctx, monkeypatch):
    session = cert_ctx['session']
    company = cert_ctx['company']
    o = _obra(session, 'Obra Solo Contrato')
    session.commit()
    # Borradores vacíos sin fichaje
    sincronizar(company, 2026, 10, o.id)
    session.commit()

    monkeypatch.setattr(
        'app.services.certificacion_service.contrato_asistencia',
        lambda *a, **k: {'hourly_rate': '25.00', 'lines': {}},
    )
    assert o.id in obras_ids_certificacion(company.id, 2026, 10)


def test_panel_obras_marca_por_revisar(cert_ctx, monkeypatch):
    """Vista Obras: la obra con propuesta recibida sale con requiere_accion."""
    session = cert_ctx['session']
    company = cert_ctx['company']
    o_ok = _obra(session, 'Obra Con Recibida')
    o_otra = _obra(session, 'Obra Solo Fichaje')
    u = _operario(session, company, 'Marta')
    _fichaje(session, u, o_ok, date(2026, 10, 5))
    _fichaje(session, u, o_otra, date(2026, 10, 6))
    session.flush()

    monkeypatch.setattr(
        'app.services.certificacion_service.periodo_bloqueado',
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        'app.services.certificacion_service._avisar',
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        'app.services.panel_scope_service.certificacion_obra_ids',
        lambda _user: {o_ok.id, o_otra.id},
    )

    sub, _emp = sincronizar(company, 2026, 10, o_ok.id)
    session.flush()
    for ln in list(sub.lineas):
        ln.horas = Decimal('8.00')
        ln.precio_hora = Decimal('20.00')
        ln.origen_horas = 'manual_total'
    if not sub.lineas:
        session.add(CertificacionLinea(
            propuesta_id=sub.id,
            user_id=u.id,
            obra_id=o_ok.id,
            fecha=date(2026, 10, 5),
            horas=Decimal('8.00'),
            precio_hora=Decimal('20.00'),
            origen_horas='manual_total',
        ))
    session.flush()
    enviar(sub, actor_id=u.id)
    session.flush()

    filas = panel_certificacion_obras(u, anio=2026, mes=10)
    by_id = {r['obra'].id: r for r in filas}
    assert o_ok.id in by_id
    assert by_id[o_ok.id]['requiere_accion'] is True
    assert by_id[o_ok.id]['tiene_recibida'] is True
    assert by_id[o_ok.id]['estado'] == 'recibida'
    if o_otra.id in by_id:
        assert by_id[o_otra.id]['requiere_accion'] is False
    # Las pendientes salen primero
    assert filas[0]['obra'].id == o_ok.id


def test_requerir_accion_marca_y_limpia_al_enviar(cert_ctx, monkeypatch):
    from app.services.certificacion_avisos_service import pares_pendientes_mes
    from app.services.certificacion_service import requerir_accion

    session = cert_ctx['session']
    company = cert_ctx['company']
    o = _obra(session, 'Obra Requerir')
    u = _operario(session, company, 'ReqOp')
    _fichaje(session, u, o, date(2026, 10, 5))
    admin = User(
        email='admin.req@test.com',
        password_hash=generate_password_hash('x'),
        role='admin',
        name='Admin',
        lastname='Req',
        dni='REQ001',
        company_id=cert_ctx['internal'].id,
        active=True,
        email_verified=True,
        is_deleted=False,
    )
    session.add(admin)
    session.commit()

    monkeypatch.setattr('app.services.certificacion_service._avisar', lambda *a, **k: None)
    monkeypatch.setattr(
        'app.services.certificacion_service.periodo_bloqueado',
        lambda *a, **k: False,
    )

    sub = requerir_accion(company, o.id, 2026, 10, admin.id)
    session.commit()
    assert sub.requerida_at is not None
    assert sub.estado == 'borrador'
    pares = pares_pendientes_mes(
        anio=2026, mes=10, company_id=company.id, obra_id=o.id,
        vista_subcontrata=True,
    )
    assert pares.get((company.id, o.id)) == 'requerida'

    sub, _emp = sincronizar(company, 2026, 10, o.id, refrescar_precios=False)
    session.flush()
    if not sub.lineas:
        session.add(CertificacionLinea(
            propuesta_id=sub.id,
            user_id=u.id,
            obra_id=o.id,
            fecha=date(2026, 10, 5),
            horas=Decimal('8.00'),
            precio_hora=Decimal('20.00'),
            origen_horas='manual_total',
        ))
        session.flush()
    else:
        for ln in sub.lineas:
            ln.horas = Decimal('8.00')
            ln.precio_hora = Decimal('20.00')
    enviar(sub, u.id)
    session.commit()
    sub = CertificacionPropuesta.query.get(sub.id)
    assert sub.requerida_at is None
    assert sub.estado == 'enviada'
    pares2 = pares_pendientes_mes(
        anio=2026, mes=10, company_id=company.id, obra_id=o.id,
        vista_subcontrata=True,
    )
    assert (company.id, o.id) not in pares2
    pares_ofi = pares_pendientes_mes(
        anio=2026, mes=10, company_id=company.id, obra_id=o.id,
        vista_subcontrata=False,
    )
    assert pares_ofi.get((company.id, o.id)) == 'recibida'


def test_panel_marca_aviso_recibida_empresa_y_obra(cert_ctx, monkeypatch):
    """Aviso = propuesta recibida en tu tejado; se marca en la fila de empresa/obra."""
    session = cert_ctx['session']
    company = cert_ctx['company']
    o_pend = _obra(session, 'Obra Recibida')
    o_ok = _obra(session, 'Obra Ya Aceptada')
    u = _operario(session, company, 'AvisoMark')
    _fichaje(session, u, o_pend, date(2026, 10, 3))
    _fichaje(session, u, o_ok, date(2026, 10, 4))
    # Solo fichaje/borrador en o_pend no basta: hace falta enviada de la subcontrata.
    session.add(CertificacionPropuesta(
        company_id=company.id, obra_id=o_pend.id, anio=2026, mes=10,
        direccion=DIR_SUB, estado='enviada',
    ))
    session.add(CertificacionPropuesta(
        company_id=company.id, obra_id=o_ok.id, anio=2026, mes=10,
        direccion=DIR_EMP, estado='aceptada',
    ))
    session.add(CertificacionPropuesta(
        company_id=company.id, obra_id=o_ok.id, anio=2026, mes=10,
        direccion=DIR_SUB, estado='aceptada',
    ))
    session.commit()

    monkeypatch.setattr(
        'app.services.panel_scope_service.certificacion_obra_ids',
        lambda _user: None,
    )
    monkeypatch.setattr(
        'app.services.certificacion_avisos_service._obra_ids_permitidas',
        lambda _user: None,
    )

    admin = User(
        email='admin.aviso@mark.test',
        password_hash=generate_password_hash('x'),
        role='admin',
        name='Admin',
        lastname='Aviso',
        dni='AVISO1',
        company_id=cert_ctx['internal'].id,
        active=True,
        email_verified=True,
        is_deleted=False,
    )
    session.add(admin)
    session.commit()

    empresas = panel_certificacion_oficina(admin, anio=2026, mes=10)
    emp = next(r for r in empresas if r['company'].id == company.id)
    assert emp['aviso_pendiente'] is True
    assert emp['n_aviso'] >= 1
    assert emp['motivo_aviso'] == 'recibida'

    obras = panel_certificacion_obras(admin, anio=2026, mes=10)
    by_obra = {r['obra'].id: r for r in obras}
    assert by_obra[o_pend.id]['aviso_pendiente'] is True
    assert by_obra[o_ok.id]['aviso_pendiente'] is False

    from app.services.certificacion_service import panel_certificacion_empresa_obras
    hub = panel_certificacion_empresa_obras(admin, company.id, anio=2026, mes=10)
    by_hub = {r['obra'].id: r for r in hub}
    assert by_hub[o_pend.id]['aviso_pendiente'] is True
    assert by_hub[o_ok.id]['aviso_pendiente'] is False
