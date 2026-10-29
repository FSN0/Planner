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


def test_consolidar_multiplan_autorresuelve_falta(
    session, tenant_soltec, user_operario, user_jefe,
):
    """Plan A+B, fichó solo en B → la pata A pasa a Falta (como confirmar falta)."""
    from app.services.desvio_fichaje_service import (
        ESTADO_FALTA,
        PREFIJO_FALTA_PARCIAL_AUTO,
        es_falta_parcial_auto,
    )

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    a = _obra(session, 'Plan A', 'A-04', jefe_id=user_jefe.id)
    b = _obra(session, 'Plan B', 'B-04', jefe_id=user_jefe.id)
    ayer = date.today() - timedelta(days=1)
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=ayer,
        obra_planificada_id=b.id, obra_real_id=b.id,
        check_in=datetime.combine(ayer, time(8, 0)),
        estado='Correcto',
    ))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=ayer,
        obra_planificada_id=a.id, estado='Sin_Registro',
    ))
    session.commit()

    n = consolidar_pendientes_a_ausencia(ayer)
    session.commit()
    assert n == 1
    reg_a = RegistroFichaje.query.filter_by(
        user_id=user_operario.id, fecha=ayer, obra_planificada_id=a.id,
    ).first()
    assert reg_a.estado == ESTADO_FALTA
    assert es_falta_parcial_auto(reg_a)
    assert (reg_a.notas_resolucion or '').startswith(PREFIJO_FALTA_PARCIAL_AUTO)


def test_autorresolver_ausencia_parcial_ya_creada(
    session, tenant_soltec, user_operario, user_jefe,
):
    from app.services.desvio_fichaje_service import (
        ESTADO_FALTA,
        autorresolver_ausencias_parciales,
        es_falta_parcial_auto,
    )

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    a = _obra(session, 'Plan A', 'A-05', jefe_id=user_jefe.id)
    b = _obra(session, 'Plan B', 'B-05', jefe_id=user_jefe.id)
    ayer = date.today() - timedelta(days=1)
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=ayer,
        obra_planificada_id=b.id, obra_real_id=b.id,
        check_in=datetime.combine(ayer, time(8, 0)),
        estado='Correcto',
    ))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=ayer,
        obra_planificada_id=a.id, estado='Ausencia',
    ))
    session.commit()

    n = autorresolver_ausencias_parciales(ayer)
    session.commit()
    assert n == 1
    reg_a = RegistroFichaje.query.filter_by(
        user_id=user_operario.id, fecha=ayer, obra_planificada_id=a.id,
    ).first()
    assert reg_a.estado == ESTADO_FALTA
    assert es_falta_parcial_auto(reg_a)


def test_corte_mismo_dia_marca_ausencia_y_fichaje_la_quita(
    session, tenant_soltec, user_operario, user_jefe, monkeypatch,
):
    from app.models import ConfiguracionGlobal
    from app.services.desvio_fichaje_service import ya_paso_hora_limite_entrada

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    conf = ConfiguracionGlobal.query.filter_by(clave='hora_limite_entrada').first()
    if conf:
        conf.valor = '08:30'
    else:
        session.add(ConfiguracionGlobal(clave='hora_limite_entrada', valor='08:30'))
    a = _obra(session, 'Plan corte', 'CORTE-01', jefe_id=user_jefe.id)
    hoy = date.today()
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=hoy,
        obra_planificada_id=a.id, estado='Sin_Registro',
    ))
    session.commit()

    monkeypatch.setattr(
        'app.utils.timezone_utils.now_local',
        lambda: datetime.combine(hoy, time(8, 0)),
    )
    assert ya_paso_hora_limite_entrada() is False

    monkeypatch.setattr(
        'app.utils.timezone_utils.now_local',
        lambda: datetime.combine(hoy, time(8, 35)),
    )
    assert ya_paso_hora_limite_entrada() is True

    n = consolidar_pendientes_a_ausencia(hoy)
    session.commit()
    assert n == 1
    reg = RegistroFichaje.query.filter_by(
        user_id=user_operario.id, fecha=hoy, obra_planificada_id=a.id,
    ).first()
    assert reg.estado == 'Ausencia'

    check_in = datetime.combine(hoy, time(9, 15))
    cerrados = resolver_plan_cumplido_por_fichaje(
        user_operario.id, hoy, a.id, check_in=check_in,
    )
    session.commit()
    assert len(cerrados) == 1
    assert reg.estado == 'Correcto'
    assert reg.obra_real_id == a.id


def test_estado_falta_tiene_color_propio():
    assert estado_fichaje_agregado(['Falta']) == 'Falta'
    assert color_fichaje_agregado(['Falta']) == COLOR_FALTA
    assert estado_fichaje_agregado(['Falta', 'Correcto']) == 'Falta'
