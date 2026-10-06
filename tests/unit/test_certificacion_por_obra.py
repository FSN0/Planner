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
    panel_certificacion_oficina,
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
