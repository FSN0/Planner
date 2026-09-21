"""Multi-desvío: un Conflicto por obra de plan + consolidación de ausencias."""
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

from app.models import Asignacion, RegistroFichaje
from app.services.desvio_fichaje_service import (
    consolidar_pendientes_a_ausencia,
    materializar_conflictos_entrada,
    resolver_plan_cumplido_por_fichaje,
)
from app.services.fichaje_estado_service import (
    COLOR_FALTA,
    color_fichaje_agregado,
    estado_fichaje_agregado,
)


def _obra(session, nombre, codigo, jefe_id=None):
    from app.models import Obra
    o = Obra(nombre=nombre, codigo=codigo, estado='En Curso', jefe_obra_id=jefe_id)
    session.add(o)
    session.flush()
    return o


def test_materializar_dos_conflictos(session, tenant_soltec, user_operario, user_jefe, company_internal):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    a = _obra(session, 'Plan A', 'A-01', jefe_id=user_jefe.id)
    b = _obra(session, 'Plan B', 'B-01', jefe_id=user_jefe.id)
    c = _obra(session, 'Real C', 'C-01', jefe_id=user_jefe.id)
    fecha = date.today()
    session.add(Asignacion(user_id=user_operario.id, obra_id=a.id, fecha=fecha))
    session.add(Asignacion(user_id=user_operario.id, obra_id=b.id, fecha=fecha))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=fecha,
        obra_planificada_id=a.id, estado='Sin_Registro',
    ))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=fecha,
        obra_planificada_id=b.id, estado='Sin_Registro',
    ))
    session.commit()

    check_in = datetime.combine(fecha, time(7, 30))
    conflictos, a_notif = materializar_conflictos_entrada(
        user_id=user_operario.id,
        fecha=fecha,
        obra_real_id=c.id,
        obras_plan_ids=[a.id, b.id],
        check_in=check_in,
    )
    session.commit()

    assert len(conflictos) == 2
    assert len(a_notif) == 2
    planes = {r.obra_planificada_id for r in conflictos}
    assert planes == {a.id, b.id}
    assert all(r.obra_real_id == c.id and r.estado == 'Conflicto' for r in conflictos)


def test_cumplir_plan_cae_solo_esa_pata(session, tenant_soltec, user_operario, user_jefe):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    a = _obra(session, 'Plan A', 'A-02', jefe_id=user_jefe.id)
    b = _obra(session, 'Plan B', 'B-02', jefe_id=user_jefe.id)
    c = _obra(session, 'Real C', 'C-02', jefe_id=user_jefe.id)
    fecha = date.today()
    check_in = datetime.combine(fecha, time(7, 0))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=fecha,
        obra_planificada_id=a.id, obra_real_id=c.id,
        estado='Conflicto', check_in=check_in,
    ))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=fecha,
        obra_planificada_id=b.id, obra_real_id=c.id,
        estado='Conflicto', check_in=check_in,
    ))
    session.commit()

    resolver_plan_cumplido_por_fichaje(
        user_operario.id, fecha, a.id,
        check_in=datetime.combine(fecha, time(10, 0)),
    )
    session.commit()

    ra = RegistroFichaje.query.filter_by(
        user_id=user_operario.id, fecha=fecha, obra_planificada_id=a.id,
    ).first()
    rb = RegistroFichaje.query.filter_by(
        user_id=user_operario.id, fecha=fecha, obra_planificada_id=b.id,
    ).first()
    assert ra.estado == 'Correcto'
    assert ra.obra_real_id == a.id
    assert rb.estado == 'Conflicto'
    assert rb.obra_real_id == c.id


def test_consolidar_pendientes_a_ausencia(session, tenant_soltec, user_operario, user_jefe):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    a = _obra(session, 'Plan A', 'A-03', jefe_id=user_jefe.id)
    ayer = date.today() - timedelta(days=1)
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=ayer,
        obra_planificada_id=a.id, estado='Sin_Registro',
    ))
    session.commit()

    n = consolidar_pendientes_a_ausencia(ayer)
    session.commit()
    assert n == 1
    reg = RegistroFichaje.query.filter_by(
        user_id=user_operario.id, fecha=ayer, obra_planificada_id=a.id,
    ).first()
    assert reg.estado == 'Ausencia'


def test_estado_falta_tiene_color_propio():
    assert estado_fichaje_agregado(['Falta']) == 'Falta'
    assert color_fichaje_agregado(['Falta']) == COLOR_FALTA
    assert estado_fichaje_agregado(['Falta', 'Correcto']) == 'Falta'
