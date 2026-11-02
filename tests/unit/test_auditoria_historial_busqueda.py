"""Búsqueda e histórico de auditoría de fichajes."""
from datetime import date, datetime

import pytest
from flask import g
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app.models import Company, Obra, RegistroFichaje, User
from app.services.auditoria_casos_service import (
    ORIGEN_AUTO,
    ORIGEN_COMODIN,
    ORIGEN_MANUAL,
    ORIGEN_ODOO,
    condicion_en_historial,
    expr_origen_sql,
    origen_registro,
)
from app.sync.routes import (
    _ESTADOS_HISTORIAL_DECISION,
    _agrupar_filas_historial,
    _aplicar_busqueda_historial,
    _aplicar_orden_historial,
    _fila_historial,
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
            condicion_en_historial(set()),
        )
    }
    assert cerrado_lado.id in ids
    assert abierto.id not in ids


def test_origen_distingue_decision_odoo_automatico_y_comodin(hist_ctx):
    session = hist_ctx['session']
    company = hist_ctx['company']
    u = _user(session, company, 'RUIZ', 'LLORENS', 'ruiz.origen@hist.test')
    plan = Obra(nombre='CENTRO DE DIA', codigo='S25/158', estado='En Curso', is_deleted=False)
    real = Obra(nombre='URGENCIAS', codigo='S26/027', estado='En Curso', is_deleted=False)
    comodin = Obra(nombre='VACACIONES', codigo='COM', estado='En Curso', is_deleted=False)
    session.add_all([plan, real, comodin])
    session.flush()

    manual = _reg(session, u, estado='Resuelto_Falta', dia=date(2026, 9, 30))
    manual.obra_planificada_id = plan.id
    manual.fecha_auditoria = datetime(2026, 9, 30, 9, 0)

    odoo = _reg(session, u, estado='Sobreescrito_RRHH', dia=date(2026, 9, 29))
    odoo.obra_real_id = real.id
    odoo.notas_resolucion = f'{plan.id}||S25/158||CENTRO DE DIA||{real.id}||S26/027||URGENCIAS||Modificado de Obra||Correcto'

    aceptado = _reg(session, u, estado='Aceptado_Odoo', dia=date(2026, 9, 28))
    aceptado.obra_real_id = real.id

    falta_auto = _reg(session, u, estado='Falta', dia=date(2026, 9, 27))
    falta_auto.obra_planificada_id = plan.id
    falta_auto.notas_resolucion = 'Falta automática: RRHH corrigió el día en Odoo'

    cumplio = _reg(session, u, estado='Correcto', dia=date(2026, 10, 7))
    cumplio.obra_planificada_id = plan.id
    cumplio.obra_real_id = plan.id
    cumplio.estado_antes_resolucion = None

    pendiente_comodin = _reg(session, u, estado='Paracaidista', dia=date(2026, 10, 8))
    pendiente_comodin.obra_real_id = comodin.id
    session.commit()

    com_ids = {comodin.id}
    esperado = {
        manual.id: ORIGEN_MANUAL,
        odoo.id: ORIGEN_ODOO,
        aceptado.id: ORIGEN_ODOO,
        falta_auto.id: ORIGEN_ODOO,
        cumplio.id: ORIGEN_AUTO,
        pendiente_comodin.id: ORIGEN_COMODIN,
    }
    expr = expr_origen_sql(com_ids)
    for reg in (manual, odoo, aceptado, falta_auto, cumplio, pendiente_comodin):
        assert origen_registro(reg, com_ids) == esperado[reg.id]
        assert session.query(expr).filter(RegistroFichaje.id == reg.id).scalar() == esperado[reg.id]

    # El comodín pendiente cuenta como historial; un pendiente normal no.
    en_hist = {
        r.id for r in RegistroFichaje.query.filter(
            RegistroFichaje.user_id == u.id, condicion_en_historial(com_ids),
        )
    }
    assert pendiente_comodin.id in en_hist
    assert RegistroFichaje.query.filter(
        RegistroFichaje.user_id == u.id,
        condicion_en_historial(set()),
        RegistroFichaje.id == pendiente_comodin.id,
    ).count() == 0

    filas = {r.id: _fila_historial(r, com_ids, True) for r in (manual, odoo, falta_auto, cumplio)}
    assert filas[manual.id]['puede_reabrir'] is True
    assert filas[odoo.id]['puede_reabrir'] is False
    assert filas[falta_auto.id]['puede_reabrir'] is False
    assert filas[cumplio.id]['puede_reabrir'] is False
    assert 'Odoo cambió la obra' in filas[odoo.id]['resultado']
    assert 'automática' in filas[falta_auto.id]['resultado']

    # Mismo día + persona → una sola fila agrupada con varios eventos.
    mismos_dia = [
        filas[manual.id], filas[odoo.id], filas[falta_auto.id], filas[cumplio.id],
    ]
    for f in mismos_dia:
        f['fecha_iso'] = '2026-03-10'
        f['fecha_txt'] = '10/03/2026'
        f['user_id'] = u.id
        f['persona'] = 'Juan Pérez'
    grupos = _agrupar_filas_historial(mismos_dia)
    assert len(grupos) == 1
    assert len(grupos[0]['eventos']) == 4

    from flask import render_template
    with hist_ctx['app'].test_request_context('/'):
        html = render_template('sync/_auditoria_historial_rows.html', grupos=grupos)
    assert 'aud-origin--odoo' in html and 'aud-origin--manual' in html and 'aud-origin--auto' in html
    assert html.count('js-aud-reabrir') == 1
    assert html.count('aud-hist-day') == 1
    assert 'aud-metric' in html


def test_quien_y_cuando_usa_ack_parcial_de_desvio():
    from types import SimpleNamespace
    from datetime import timezone

    from app.services.auditoria_casos_service import ORIGEN_MANUAL, quien_y_cuando

    actor = SimpleNamespace(name='Ana', lastname='Jefa')
    reg = SimpleNamespace(
        resuelto_por=None,
        fecha_auditoria=None,
        desvio_ack_plan_by=actor,
        desvio_ack_plan_at=datetime(2026, 11, 2, 11, 30, tzinfo=timezone.utc),
        desvio_ack_real_by=None,
        desvio_ack_real_at=None,
    )
    txt = quien_y_cuando(reg, ORIGEN_MANUAL)
    assert 'Ana Jefa' in txt
    assert '—' not in txt


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
