"""Mesa única: una carta en juego e historial de rondas."""
from datetime import date
from decimal import Decimal

import pytest
from flask import g
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app.models import CertificacionLinea, CertificacionPropuesta, CertificacionRonda, Obra, User
from app.services.certificacion_service import (
    DIR_EMP,
    DIR_SUB,
    aceptar,
    contexto_mesa,
    desenviar,
    enviar,
    ronda_en_mesa,
    rechazar,
    sincronizar,
)


@pytest.fixture
def mesa_ctx(tenant_soltec, app, session, company_subcontrata):
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        yield {
            'tenant': tenant_soltec,
            'company': company_subcontrata,
            'session': session,
            'app': app,
        }


_obra_seq = 0


def _obra(session, nombre):
    global _obra_seq
    _obra_seq += 1
    o = Obra(
        nombre=nombre,
        codigo=f'M{_obra_seq:04d}',
        estado='En Curso',
        is_deleted=False,
    )
    session.add(o)
    session.flush()
    return o


def _operario(session, company, name='Pepe'):
    u = User(
        email=f'{name.lower().replace(" ", ".")}@mesa.test',
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


def _linea(session, prop, user, obra, dia=1, horas='8.00', precio='20.00'):
    ln = CertificacionLinea(
        propuesta_id=prop.id,
        user_id=user.id,
        obra_id=obra.id,
        fecha=date(2026, 10, dia),
        horas=Decimal(horas),
        precio_hora=Decimal(precio),
        origen_horas='manual_total',
    )
    session.add(ln)
    session.flush()
    return ln


def test_enviar_crea_ronda_en_mesa(mesa_ctx, monkeypatch):
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra Mesa')
    u = _operario(session, company, 'Ana')
    monkeypatch.setattr(
        'app.services.certificacion_service.periodo_bloqueado',
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        'app.services.certificacion_service._avisar',
        lambda *a, **k: None,
    )
    sub, emp = sincronizar(company, 2026, 10, o.id)
    session.flush()
    # Vaciar y poner una línea limpia en sub
    for ln in list(sub.lineas):
        session.delete(ln)
    session.flush()
    _linea(session, sub, u, o)
    session.flush()

    enviar(sub, actor_id=u.id)
    session.flush()

    mesa = ronda_en_mesa(company.id, o.id, 2026, 10)
    assert mesa is not None
    assert mesa.direccion == DIR_SUB
    assert mesa.resultado == 'en_mesa'
    assert mesa.secuencia == 1
    assert sub.estado == 'enviada'


def test_contraoferta_sustituye_mesa(mesa_ctx, monkeypatch):
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra Contra')
    u = _operario(session, company, 'Luis')
    monkeypatch.setattr(
        'app.services.certificacion_service.periodo_bloqueado',
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        'app.services.certificacion_service._avisar',
        lambda *a, **k: None,
    )
    sub, emp = sincronizar(company, 2026, 10, o.id)
    for prop in (sub, emp):
        for ln in list(prop.lineas):
            session.delete(ln)
    session.flush()
    _linea(session, sub, u, o, horas='8.00')
    _linea(session, emp, u, o, horas='7.50')
    session.flush()

    enviar(sub, actor_id=u.id)
    session.flush()
    first = ronda_en_mesa(company.id, o.id, 2026, 10)
    assert first.direccion == DIR_SUB

    enviar(emp, actor_id=u.id)
    session.flush()

    mesa = ronda_en_mesa(company.id, o.id, 2026, 10)
    assert mesa is not None
    assert mesa.direccion == DIR_EMP
    assert mesa.secuencia == 2
    session.refresh(first)
    assert first.resultado == 'sustituida'
    session.refresh(sub)
    assert sub.estado == 'borrador'
    assert emp.estado == 'enviada'


def test_rechazar_deja_mesa_libre(mesa_ctx, monkeypatch):
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra Rechazo')
    u = _operario(session, company, 'Eva')
    monkeypatch.setattr(
        'app.services.certificacion_service.periodo_bloqueado',
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        'app.services.certificacion_service._avisar',
        lambda *a, **k: None,
    )
    sub, emp = sincronizar(company, 2026, 10, o.id)
    for ln in list(sub.lineas):
        session.delete(ln)
    session.flush()
    _linea(session, sub, u, o)
    session.flush()
    enviar(sub, actor_id=u.id)
    session.flush()

    rechazar(sub, actor_id=u.id, comentario='No cuadra el sábado')
    session.flush()

    assert ronda_en_mesa(company.id, o.id, 2026, 10) is None
    rondas = CertificacionRonda.query.filter_by(
        company_id=company.id, obra_id=o.id, anio=2026, mes=10,
    ).all()
    assert len(rondas) == 1
    assert rondas[0].resultado == 'rechazada'
    assert 'sábado' in (rondas[0].comentario_rechazo or '')
    assert sub.estado == 'borrador'


def test_contexto_mesa_responder(mesa_ctx, monkeypatch):
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra Ctx')
    u = _operario(session, company, 'Nora')
    monkeypatch.setattr(
        'app.services.certificacion_service.periodo_bloqueado',
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        'app.services.certificacion_service._avisar',
        lambda *a, **k: None,
    )
    sub, emp = sincronizar(company, 2026, 10, o.id)
    for ln in list(sub.lineas):
        session.delete(ln)
    session.flush()
    _linea(session, sub, u, o)
    session.flush()
    enviar(sub, actor_id=u.id)
    session.flush()

    ctx = contexto_mesa(
        company, o, 2026, 10,
        propia=emp, ajena=sub,
        vista_subcontrata=False,
    )
    assert ctx['modo_mesa'] == 'responder'
    assert ctx['turno'] == 'te_toca'
    assert ctx['mesa'] is not None
    assert ctx['comparar_ronda'] is not None
    assert (u.id, o.id, date(2026, 10, 1)) in ctx['mapa_comparar']
