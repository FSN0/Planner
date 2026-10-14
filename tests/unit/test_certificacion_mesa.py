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
    _build_cert_pdf_context,
    aceptar,
    anadir_dia_manual,
    cadena_rondas_negociacion,
    contexto_mesa,
    desenviar,
    etiquetas_rondas,
    enviar,
    frase_delta_plataforma,
    ids_propuestas_pdf_cerradas,
    periodo_bloqueado,
    programar_warmup_pdf_certificacion,
    reabrir_periodo,
    ronda_en_mesa,
    rechazar,
    sembrar_borrador_desde_mesa,
    siguiente_etiqueta_propuesta,
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


def test_siguiente_etiqueta_y_cadena(mesa_ctx, monkeypatch):
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra Cadena')
    u = _operario(session, company, 'Cad')
    monkeypatch.setattr(
        'app.services.certificacion_service.periodo_bloqueado',
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        'app.services.certificacion_service._avisar',
        lambda *a, **k: None,
    )
    assert siguiente_etiqueta_propuesta('3') == '3.2'
    assert siguiente_etiqueta_propuesta('3.3') == '3.4'

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
    r1 = ronda_en_mesa(company.id, o.id, 2026, 10)
    enviar(emp, actor_id=u.id)
    session.flush()
    r2 = ronda_en_mesa(company.id, o.id, 2026, 10)
    # Sub vuelve a contestar → 1.3 en mesa
    session.refresh(sub)
    for ln in list(sub.lineas):
        ln.horas = Decimal('7.00')
        ln.precio_hora = Decimal('20.00')
        ln.origen_horas = 'manual_total'
    if not sub.lineas:
        _linea(session, sub, u, o, horas='7.00')
    session.flush()
    enviar(sub, actor_id=u.id)
    session.flush()
    r3 = ronda_en_mesa(company.id, o.id, 2026, 10)

    rondas = CertificacionRonda.query.filter_by(
        company_id=company.id, obra_id=o.id, anio=2026, mes=10,
    ).all()
    et = etiquetas_rondas(rondas)
    assert et[r1.id] == '1'
    assert et[r2.id] == '1.2'
    assert et[r3.id] == '1.3'

    cadena = cadena_rondas_negociacion(rondas, r3, et)
    assert [c['etiqueta'] for c in cadena] == ['1', '1.2', '1.3']
    assert siguiente_etiqueta_propuesta(cadena[-1]['etiqueta']) == '1.4'

    ctx = contexto_mesa(
        company, o, 2026, 10,
        propia=emp, ajena=sub,
        vista_subcontrata=False,
        corr=True,
    )
    assert ctx['modo_mesa'] == 'responder'
    assert [c['etiqueta'] for c in ctx['comparar_cadena']] == ['1', '1.2', '1.3']
    assert ctx['etiqueta_borrador'] == '1.4'


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
    assert mesa.secuencia == 2  # orden interno
    et = etiquetas_rondas(
        CertificacionRonda.query.filter_by(
            company_id=company.id, obra_id=o.id, anio=2026, mes=10,
        ).all()
    )
    assert et[first.id] == '1'
    assert et[mesa.id] == '1.2'
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
    # Por defecto: ver lo recibido (aceptar/rechazar) sin editar.
    assert ctx['modo_mesa'] == 'recibida'
    assert ctx['viendo_recibida'] is True
    assert ctx['turno'] == 'te_toca'
    assert ctx['mesa'] is not None
    assert ctx['comparar_ronda'] is None
    assert ctx['mesa_carta_seq'] == '1'
    assert ctx['baraja'][0]['etiqueta'] == '1'

    ctx_corr = contexto_mesa(
        company, o, 2026, 10,
        propia=emp, ajena=sub,
        vista_subcontrata=False,
        corr=True,
    )
    assert ctx_corr['modo_mesa'] == 'responder'
    assert ctx_corr['corr_activa'] is True
    assert ctx_corr['viendo_recibida'] is False
    assert ctx_corr['comparar_ronda'] is not None
    assert (u.id, o.id, date(2026, 10, 1)) in ctx_corr['mapa_comparar']


def test_etiquetas_nueva_propuesta_tras_rechazo(mesa_ctx, monkeypatch):
    """Tras rechazar, el siguiente envío es #2 (no 1.2)."""
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra Etiqueta')
    u = _operario(session, company, 'Paco')
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
    session.flush()
    enviar(sub, actor_id=u.id)
    session.flush()
    first = ronda_en_mesa(company.id, o.id, 2026, 10)
    rechazar(sub, actor_id=u.id, comentario='No')
    session.flush()

    _linea(session, emp, u, o, horas='7.00')
    session.flush()
    enviar(emp, actor_id=u.id)
    session.flush()
    second = ronda_en_mesa(company.id, o.id, 2026, 10)
    et = etiquetas_rondas(
        CertificacionRonda.query.filter_by(
            company_id=company.id, obra_id=o.id, anio=2026, mes=10,
        ).all()
    )
    assert et[first.id] == '1'
    assert et[second.id] == '2'


def test_pdf_muestra_quien_acepto(mesa_ctx, monkeypatch):
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra PDF Acepta')
    u = _operario(session, company, 'Rita')
    monkeypatch.setattr(
        'app.services.certificacion_service.periodo_bloqueado',
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        'app.services.certificacion_service._avisar',
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        'app.services.tenant_branding_service.logo_stripe_data_uri',
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        'app.services.tenant_branding_service.header_data_uri',
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        'app.services.tenant_branding_service.mark_data_uri',
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        'app.services.tenant_branding_service.get_organization_display_name',
        lambda *a, **k: 'Org',
    )
    monkeypatch.setattr(
        'app.services.tenant_branding_service.get_brand_stripe_color',
        lambda *a, **k: '#000',
    )
    sub, emp = sincronizar(company, 2026, 10, o.id)
    for ln in list(sub.lineas):
        session.delete(ln)
    session.flush()
    _linea(session, sub, u, o)
    session.flush()
    enviar(sub, actor_id=u.id)
    session.flush()
    aceptar(sub, actor_id=u.id)
    session.flush()
    session.refresh(sub)

    ctx = _build_cert_pdf_context(sub, schema_name=None, grupos=[])
    assert 'Rita' in (ctx.get('aceptada_por') or '')
    assert ctx.get('aceptada_el')
    assert ctx.get('propuesta_num') == '1'


def test_sembrar_borrador_desde_mesa_al_responder(mesa_ctx, monkeypatch):
    """Subcontrata recibe propuesta: su borrador (a 0) se rellena con lo enviado."""
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra Sembrar')
    u = _operario(session, company, 'Toni')
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
    # Oficina envía 8 h; subcontrata tiene fila vacía (como tras sincronizar).
    _linea(session, emp, u, o, horas='8.00', precio='22.00')
    ln_sub = CertificacionLinea(
        propuesta_id=sub.id,
        user_id=u.id,
        obra_id=o.id,
        fecha=date(2026, 10, 1),
        horas=None,
        precio_hora=Decimal('22.00'),
        origen_horas='vacio',
    )
    session.add(ln_sub)
    sub.lineas.append(ln_sub)
    session.flush()

    enviar(emp, actor_id=u.id)
    session.flush()
    mesa = ronda_en_mesa(company.id, o.id, 2026, 10)
    assert mesa is not None
    assert mesa.direccion == DIR_EMP
    assert mesa.lineas_json

    session.refresh(sub)
    n = sembrar_borrador_desde_mesa(sub, mesa)
    session.flush()
    session.refresh(ln_sub)
    assert n == 1
    assert float(ln_sub.horas) == pytest.approx(8.0)
    assert float(ln_sub.precio_hora) == pytest.approx(22.0)
    assert str(ln_sub.origen_horas).startswith('manual')

    # Segunda siembra no pisa la edición manual.
    ln_sub.horas = Decimal('9.00')
    session.flush()
    assert sembrar_borrador_desde_mesa(sub, mesa) == 0
    session.refresh(ln_sub)
    assert float(ln_sub.horas) == pytest.approx(9.0)


def test_programar_warmup_pdf_lanza_hilo(monkeypatch, app):
    import app.services.certificacion_service as svc
    from flask import g
    from types import SimpleNamespace

    called = {}

    class _FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
            called['args'] = args
            called['daemon'] = daemon

        def start(self):
            called['started'] = True

    monkeypatch.setattr(svc.threading, 'Thread', _FakeThread)
    with app.app_context():
        g.current_tenant = SimpleNamespace(schema_name='tenant_test')
        with svc._warmup_pdf_lock:
            svc._warmup_pdf_inflight.clear()
        programar_warmup_pdf_certificacion(42, schema_name='tenant_test')
        assert called.get('started') is True
        assert called.get('args')[2] == [42]
        assert called.get('daemon') is True


def test_ids_propuestas_pdf_cerradas(mesa_ctx, monkeypatch):
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra PDF Warm')
    u = _operario(session, company, 'Pdf')
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
    aceptar(sub, actor_id=u.id)
    session.flush()
    ids = ids_propuestas_pdf_cerradas(sub)
    assert sub.id in ids
    assert emp.id in ids


def test_nombre_oficina_sin_empresa_principal(monkeypatch):
    from app.services.certificacion_service import _nombre_oficina_certificacion
    from types import SimpleNamespace

    monkeypatch.setattr(
        'app.services.tenant_branding_service.get_organization_display_name',
        lambda: 'Soltec',
    )
    assert _nombre_oficina_certificacion(
        SimpleNamespace(nombre='Empresa principal'),
    ) == 'Soltec'
    assert _nombre_oficina_certificacion(
        SimpleNamespace(nombre='Empresa principal, Soltec'),
    ) == 'Soltec'
    assert _nombre_oficina_certificacion(
        SimpleNamespace(nombre='Soltec Energía SL'),
    ) == 'Soltec Energía SL'


def test_frase_delta_plataforma_cara_barata():
    cara = frase_delta_plataforma(
        {'pct_importe': Decimal('25.00'), 'pct_horas': Decimal('10.00')},
        etiqueta='propuesta',
    )
    assert 'más cara' in (cara or '')
    assert 'vas a enviar' in (cara or '')
    suya = frase_delta_plataforma(
        {'pct_importe': Decimal('-12.50'), 'pct_horas': None},
        etiqueta='su_propuesta',
        nombre_empresa='Montajes Sur SL',
    )
    assert 'más barata' in (suya or '')
    assert 'Montajes Sur SL' in (suya or '')
    assert 'la empresa' not in (suya or '').lower()
    cerrada = frase_delta_plataforma(
        {'pct_importe': Decimal('-81.00'), 'pct_horas': None},
        etiqueta='aceptada',
    )
    assert 'aceptada' in (cerrada or '')
    assert 'vas a enviar' not in (cerrada or '')
    igual = frase_delta_plataforma(
        {'pct_importe': Decimal('0.00'), 'pct_horas': None},
        etiqueta='propuesta',
    )
    assert 'cuadra' in (igual or '')


def test_anadir_dia_manual_sin_fichaje(mesa_ctx, monkeypatch):
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra Add Day')
    u = _operario(session, company, 'Manual')
    monkeypatch.setattr(
        'app.services.certificacion_service.periodo_bloqueado',
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        'app.services.certificacion_service._precio_rapido_sin_odoo',
        lambda *a, **k: Decimal('18.00'),
    )
    sub, _emp = sincronizar(company, 2026, 10, o.id)
    session.flush()
    ln = anadir_dia_manual(
        sub,
        user_id=u.id,
        fecha=date(2026, 10, 15),
        horas='6.5',
        company=company,
        obra=o,
    )
    session.flush()
    assert ln.origen_horas == 'manual_anadido'
    assert float(ln.horas) == pytest.approx(6.5)
    assert ln.user_id == u.id
    assert ln.fecha == date(2026, 10, 15)
    # No se borra al sincronizar (no es vacio/fichaje).
    sincronizar(company, 2026, 10, o.id, refrescar_precios=False)
    session.flush()
    ids = {x.id for x in CertificacionLinea.query.filter_by(propuesta_id=sub.id).all()}
    assert ln.id in ids


def test_reabrir_tras_aceptar(mesa_ctx, monkeypatch):
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra Reabrir OK')
    u = _operario(session, company, 'Rea')
    monkeypatch.setattr(
        'app.services.certificacion_service._avisar',
        lambda *a, **k: None,
    )
    sub, emp = sincronizar(company, 2026, 10, o.id)
    for ln in list(sub.lineas):
        session.delete(ln)
    session.flush()
    _linea(session, sub, u, o, horas='8.00')
    session.flush()
    enviar(sub, actor_id=u.id)
    session.flush()
    aceptar(sub, actor_id=u.id)
    session.flush()
    assert periodo_bloqueado(company.id, 2026, 10, o.id) is True
    assert ronda_en_mesa(company.id, o.id, 2026, 10) is None

    mesa = reabrir_periodo(company.id, o.id, 2026, 10, actor_id=u.id)
    session.flush()
    session.refresh(sub)
    session.refresh(emp)

    assert mesa is not None
    assert mesa.resultado == 'en_mesa'
    assert mesa.direccion == DIR_SUB
    assert periodo_bloqueado(company.id, 2026, 10, o.id) is False
    assert sub.estado == 'enviada'
    assert emp.estado == 'borrador'
    assert float(sub.lineas[0].horas) == pytest.approx(8.0)

    ctx = contexto_mesa(
        company, o, 2026, 10,
        propia=emp, ajena=sub,
        vista_subcontrata=False,
    )
    assert ctx['modo_mesa'] == 'recibida'
    assert ctx['puede_reabrir'] is False


def test_reabrir_tras_rechazar(mesa_ctx, monkeypatch):
    """Tras rechazo limpio: nueva propuesta (#2), no hace falta «reabrir».

    ``reabrir_periodo`` sigue pudiendo restaurar la carta rechazada a la mesa
    (caso raro / SaaS), pero ``puede_reabrir`` no debe empujar ese CTA.
    """
    session = mesa_ctx['session']
    company = mesa_ctx['company']
    o = _obra(session, 'Obra Reabrir No')
    u = _operario(session, company, 'Reb')
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
    _linea(session, sub, u, o, horas='9.00')
    session.flush()
    enviar(sub, actor_id=u.id)
    session.flush()
    rechazar(sub, actor_id=u.id, comentario='Mal el viernes')
    session.flush()
    assert ronda_en_mesa(company.id, o.id, 2026, 10) is None
    assert sub.estado == 'borrador'
    assert emp.estado == 'borrador'

    ctx_prev = contexto_mesa(
        company, o, 2026, 10,
        propia=emp, ajena=sub,
        vista_subcontrata=False,
    )
    assert ctx_prev['modo_mesa'] == 'preparar'
    assert ctx_prev['turno'] == 'puedes_enviar'
    assert ctx_prev['etiqueta_borrador'] == '2'
    assert ctx_prev['puede_reabrir'] is False

    # Mirando la carta rechazada en historial: sigue habiendo borrador #2.
    rechazada = CertificacionRonda.query.filter_by(
        company_id=company.id, obra_id=o.id, anio=2026, mes=10,
        resultado='rechazada',
    ).one()
    ctx_hist = contexto_mesa(
        company, o, 2026, 10,
        propia=emp, ajena=sub,
        vista_subcontrata=False,
        ronda_id=rechazada.id,
    )
    assert ctx_hist['modo_mesa'] == 'historial'
    assert ctx_hist['turno'] == 'puedes_enviar'
    assert ctx_hist['etiqueta_borrador'] == '2'
    assert ctx_hist['puede_reabrir'] is False

    mesa = reabrir_periodo(company.id, o.id, 2026, 10, actor_id=u.id)
    session.flush()
    session.refresh(sub)

    assert mesa is not None
    assert mesa.resultado == 'en_mesa'
    assert mesa.direccion == DIR_SUB
    assert sub.estado == 'enviada'
    assert float(sub.lineas[0].horas) == pytest.approx(9.0)
    assert 'viernes' not in (mesa.comentario_rechazo or '')
