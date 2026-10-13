"""Búsqueda e histórico de auditoría de fichajes."""
from datetime import date, datetime

import pytest
from flask import g
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app.models import Company, Obra, RegistroFichaje, User
from app.sync.routes import (
    _ESTADOS_HISTORIAL_DECISION,
    _aplicar_busqueda_historial,
    _aplicar_orden_historial,
    _clausula_en_historial,
    _expr_origen_historial,
    _momento_auditoria_historial,
    _origen_historial,
)


@pytest.fixture
def hist_ctx(tenant_soltec, app, session, company_internal):
    with app.app_context():
        g.current_tenant = tenant_soltec
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        yield {
            'session': session,
            'app': app,
            'company': company_internal,
        }


def _user(session, company, name, lastname, email):
    u = User(
        email=email,
        password_hash=generate_password_hash('x'),
        role='operario',
        name=name,
        lastname=lastname or '-',
        dni=f'D-{abs(hash(email)) % 10_000_000}',
        company_id=company.id,
        active=True,
        email_verified=True,
        is_deleted=False,
    )
    session.add(u)
    session.flush()
    return u


def _reg(session, user, estado='Resuelto_Ignorado', dia=None):
    dia = dia or date(2026, 10, 10)
    r = RegistroFichaje(
        user_id=user.id,
        fecha=dia,
        estado=estado,
        check_in=datetime.combine(dia, datetime.min.time().replace(hour=8)),
        check_out=datetime.combine(dia, datetime.min.time().replace(hour=16)),
        fecha_auditoria=datetime.utcnow(),
        estado_antes_resolucion='Ausencia',
    )
    session.add(r)
    session.flush()
    return r


def test_busqueda_historial_nombre_y_apellidos(hist_ctx):
    session = hist_ctx['session']
    company = hist_ctx['company']
    u = _user(session, company, 'Juan', 'Pérez García', 'juan.pg@hist.test')
    r = _reg(session, u)
    # Odoo a menudo mete todo en name
    u2 = _user(session, company, 'JAVIER NARVAEZ', '', 'javier.n@hist.test')
    r2 = _reg(session, u2, dia=date(2026, 10, 11))
    # O nombre / apellido sueltos en mayúsculas
    u3 = _user(session, company, 'JAVIER', 'NARVAEZ', 'javier.n2@hist.test')
    r3 = _reg(session, u3, dia=date(2026, 10, 12))
    session.commit()

    q = RegistroFichaje.query.filter(RegistroFichaje.id == r.id)
    assert _aplicar_busqueda_historial(q, 'Juan Pérez').count() == 1
    assert _aplicar_busqueda_historial(q, 'Pérez García').count() == 1
    assert _aplicar_busqueda_historial(q, 'juan').count() == 1
    assert _aplicar_busqueda_historial(q, 'nadieinexistente').count() == 0

    q2 = RegistroFichaje.query.filter(RegistroFichaje.id.in_([r2.id, r3.id]))
    assert _aplicar_busqueda_historial(q2, 'JAVIER NARVAEZ').count() == 2
    assert _aplicar_busqueda_historial(q2, 'narvaez javier').count() == 2


def test_orden_fecha_incluye_junio_delante_de_octubre(hist_ctx):
    session = hist_ctx['session']
    company = hist_ctx['company']
    u = _user(session, company, 'Edgar', 'Ferrer', 'edgar.ferrer.orden@hist.test')
    junio = _reg(session, u, estado='Resuelto_Falta', dia=date(2026, 6, 1))
    octubre = _reg(session, u, estado='Correcto', dia=date(2026, 10, 13))
    session.commit()

    q = RegistroFichaje.query.filter(RegistroFichaje.user_id == u.id)
    asc = _aplicar_orden_historial(q, 'fecha', 'asc').all()
    assert [r.id for r in asc] == [junio.id, octubre.id]
    desc = _aplicar_orden_historial(
        RegistroFichaje.query.filter(RegistroFichaje.user_id == u.id),
        'fecha',
        'desc',
    ).all()
    assert [r.id for r in desc] == [octubre.id, junio.id]


def test_falta_confirmada_en_desvio_abierto_entra_en_historial(hist_ctx):
    session = hist_ctx['session']
    company = hist_ctx['company']
    u = _user(session, company, 'RUIZ', 'LLORENS JUAN VICENTE', 'ruiz.llorens@hist.test')
    cerrado_lado = _reg(session, u, estado='Conflicto', dia=date(2026, 10, 13))
    cerrado_lado.desvio_ack_plan_at = datetime.utcnow()
    cerrado_lado.desvio_decision_plan = 'mantener_falta'
    abierto = _reg(session, u, estado='Conflicto', dia=date(2026, 10, 12))
    session.commit()

    ids = {
        row.id for row in RegistroFichaje.query.filter(
            RegistroFichaje.user_id == u.id,
            _clausula_en_historial(),
        )
    }
    assert cerrado_lado.id in ids
    assert abierto.id not in ids


def test_origen_separa_ausencia_fichaje_y_desvio(hist_ctx):
    session = hist_ctx['session']
    company = hist_ctx['company']
    u = _user(session, company, 'RUIZ', 'LLORENS', 'ruiz.origen@hist.test')
    plan = Obra(nombre='CENTRO DE DIA', codigo='S25/158', estado='En Curso', is_deleted=False)
    real = Obra(nombre='URGENCIAS', codigo='S26/027', estado='En Curso', is_deleted=False)
    session.add_all([plan, real])
    session.flush()

    ausencia = _reg(session, u, estado='Resuelto_Falta', dia=date(2026, 9, 30))
    ausencia.obra_planificada_id = plan.id
    ausencia.estado_antes_resolucion = 'Ausencia'
    ausencia.fecha_auditoria = datetime(2026, 9, 30, 9, 0)

    sin_plan = _reg(session, u, estado='Resuelto_Asignado', dia=date(2026, 9, 29))
    sin_plan.obra_real_id = real.id
    sin_plan.estado_antes_resolucion = 'Paracaidista'
    sin_plan.fecha_auditoria = datetime(2026, 9, 29, 9, 0)

    desvio = _reg(session, u, estado='Conflicto', dia=date(2026, 10, 13))
    desvio.obra_planificada_id = plan.id
    desvio.obra_real_id = real.id
    desvio.desvio_decision_plan = 'mantener_falta'
    desvio.desvio_ack_plan_at = datetime(2026, 10, 13, 16, 40)
    desvio.fecha_auditoria = datetime(2026, 10, 13, 8, 0)

    cumplio = _reg(session, u, estado='Correcto', dia=date(2026, 10, 7))
    cumplio.obra_planificada_id = plan.id
    cumplio.obra_real_id = plan.id
    cumplio.estado_antes_resolucion = None
    cumplio.fecha_auditoria = datetime(2026, 10, 7, 8, 32)
    session.commit()

    esperado = {
        ausencia.id: 'ausencia',
        sin_plan.id: 'sin_planificar',
        desvio.id: 'desvio',
        cumplio.id: 'cumplio',
    }
    expr = _expr_origen_historial()
    for reg in (ausencia, sin_plan, desvio, cumplio):
        assert _origen_historial(reg) == esperado[reg.id]
        sql_key = session.query(expr).filter(RegistroFichaje.id == reg.id).scalar()
        assert sql_key == esperado[reg.id]

    solo_ausencia = RegistroFichaje.query.filter(
        RegistroFichaje.user_id == u.id,
        _expr_origen_historial() == 'ausencia',
    ).all()
    assert [r.id for r in solo_ausencia] == [ausencia.id]

    assert _momento_auditoria_historial(desvio) == datetime(2026, 10, 13, 16, 40)
    orden = _aplicar_orden_historial(
        RegistroFichaje.query.filter(RegistroFichaje.user_id == u.id),
        'hora_reg',
        'desc',
    ).all()
    assert orden[0].id == desvio.id

    from flask import render_template
    with hist_ctx['app'].test_request_context('/'):
        html = render_template(
            'sync/_auditoria_seccion_rows.html',
            seccion='historial',
            registros=[ausencia, sin_plan, desvio, cumplio],
            geo_por_registro={},
            muestra_geo_audit=False,
            can_resolve_fichajes=True,
            origen_historial=_origen_historial,
            momento_auditoria_historial=_momento_auditoria_historial,
            tenant_has_odoo=False,
        )
    assert 'badge-soft-amber">Ausencia' in html
    assert 'badge-soft-blue">Sin planificar' in html
    assert 'badge-soft-red">Desviación' in html
    assert 'S25/158' in html and 'CENTRO DE DIA' in html
    assert 'S26/027' in html and 'URGENCIAS' in html
    fila_desvio = html.split(f'hist-row-{desvio.id}', 1)[1].split('hist-row-', 1)[0]
    assert 'fa-arrow-right' in fila_desvio
    assert '13/10/26 18:40' in fila_desvio
    fila_ausencia = html.split(f'hist-row-{ausencia.id}', 1)[1].split('hist-row-', 1)[0]
    assert 'S26/027' not in fila_ausencia


def test_estados_decision_cubren_ausencia_y_desasignar():
    assert 'Falta' in _ESTADOS_HISTORIAL_DECISION
    assert 'Resuelto_Falta' in _ESTADOS_HISTORIAL_DECISION
    assert 'Resuelto_Ignorado' in _ESTADOS_HISTORIAL_DECISION


def test_seccion_tras_reabrir():
    from app.sync.routes import _seccion_auditoria_para_estado

    assert _seccion_auditoria_para_estado('Ausencia') == 'ausencias'
    assert _seccion_auditoria_para_estado('Conflicto') == 'conflictos'
    assert _seccion_auditoria_para_estado('Paracaidista') == 'paracaidistas'


def test_previo_reabrir_fallback_desasignado():
    from types import SimpleNamespace
    from app.sync.routes import _previo_para_reabrir

    reg = SimpleNamespace(estado='Resuelto_Falta', estado_antes_resolucion=None)
    assert _previo_para_reabrir(reg) == 'Ausencia'
    reg2 = SimpleNamespace(estado='Resuelto_Falta', estado_antes_resolucion='Ausencia')
    assert _previo_para_reabrir(reg2) == 'Ausencia'
    reg3 = SimpleNamespace(estado='Falta', estado_antes_resolucion='')
    assert _previo_para_reabrir(reg3) == 'Ausencia'
