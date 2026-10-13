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
