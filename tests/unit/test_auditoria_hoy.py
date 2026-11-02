"""Roster «Hoy» de auditoría: plan vs fichaje, sin duplicar marcas."""
from datetime import datetime, time

from sqlalchemy import text

from app.models import Asignacion, Obra, RegistroFichaje
from app.utils.timezone_utils import today_local


def _obra(session, nombre, codigo, jefe):
    o = Obra(nombre=nombre, codigo=codigo, estado='En Curso', jefe_obra_id=jefe.id, is_deleted=False)
    session.add(o)
    session.flush()
    return o


def test_count_planificados_sin_marca_solo_sin_ninguna_marca(
    session, tenant_soltec, user_operario, user_jefe, user_admin, company_internal,
):
    """Cuenta personas planificadas sin marca; quien fichó fuera de plan no entra."""
    from werkzeug.security import generate_password_hash

    from app.models import User
    from app.services.auditoria_hoy_service import count_planificados_sin_marca

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    hoy = today_local()
    a = _obra(session, 'Obra A', 'CM-1', user_jefe)
    b = _obra(session, 'Obra B', 'CM-2', user_jefe)
    c = _obra(session, 'Obra C', 'CM-3', user_jefe)
    otro = User(
        email='sinmarca@example.com',
        password_hash=generate_password_hash('x'),
        role='operario',
        name='Otro',
        lastname='SinMarca',
        dni='55555555E',
        company_id=company_internal.id,
        active=True,
        email_verified=True,
    )
    session.add(otro)
    session.flush()
    session.add(Asignacion(user_id=user_operario.id, obra_id=a.id, fecha=hoy))
    session.add(Asignacion(user_id=otro.id, obra_id=b.id, fecha=hoy))
    # Operario fichó fuera de plan → no cuenta.
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=hoy,
        obra_planificada_id=a.id, obra_real_id=c.id,
        check_in=datetime.combine(hoy, time(8, 0)),
        estado='Conflicto',
    ))
    # Otro sin marca alguna → sí cuenta.
    session.add(RegistroFichaje(
        user_id=otro.id, fecha=hoy,
        obra_planificada_id=b.id, estado='Sin_Registro',
    ))
    session.commit()

    assert count_planificados_sin_marca(user_admin, hoy=hoy) == 1


def test_roster_hoy_persona_con_dos_obras(session, tenant_soltec, user_operario, user_jefe, user_admin):
    from app.services.auditoria_hoy_service import roster_hoy

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    hoy = today_local()
    a = _obra(session, 'Obra A', 'HA-1', user_jefe)
    b = _obra(session, 'Obra B', 'HB-1', user_jefe)
    session.add(Asignacion(user_id=user_operario.id, obra_id=a.id, fecha=hoy))
    session.add(Asignacion(user_id=user_operario.id, obra_id=b.id, fecha=hoy))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=hoy,
        obra_planificada_id=a.id, obra_real_id=a.id,
        check_in=datetime.combine(hoy, time(7, 30)),
        estado='Correcto',
    ))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=hoy,
        obra_planificada_id=b.id, estado='Sin_Registro',
    ))
    session.commit()

    data = roster_hoy(user_admin, hoy=hoy)
    assert data['totales']['personas'] == 1
    assert data['totales']['plazas'] == 2
    assert data['totales']['ok'] == 1
    assert data['totales']['sin_fichar'] == 1
    p = data['personas'][0]
    assert p['user_id'] == user_operario.id
    plan = {c['obra_id']: c for c in p['plan']}
    assert plan[a.id]['chip'] == 'ok'
    assert plan[b.id]['chip'] == 'sin_fichar'
    assert len(p['fichajes']) == 1
    assert p['fichajes'][0]['obra_id'] == a.id
    assert p['fichajes'][0]['en_plan'] is True
    assert p['tono_fila'] == 'parcial'  # fichó en una, falta otra → gris
    assert 'metricas' in p
    assert set(p['metricas']) >= {'ud', 'hh', 'mod', 'moe'}


def test_roster_hoy_sin_marca_total_rojo(session, tenant_soltec, user_operario, user_jefe, user_admin):
    from app.services.auditoria_hoy_service import roster_hoy

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    hoy = today_local()
    a = _obra(session, 'Obra sola', 'HS-1', user_jefe)
    session.add(Asignacion(user_id=user_operario.id, obra_id=a.id, fecha=hoy))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=hoy,
        obra_planificada_id=a.id, estado='Sin_Registro',
    ))
    session.commit()

    p = roster_hoy(user_admin, hoy=hoy)['personas'][0]
    assert p['tono_fila'] == 'sin_marca'
    assert not p['fichajes']


def test_roster_hoy_desvio_una_sola_marca_fuera_de_plan(
    session, tenant_soltec, user_operario, user_jefe, user_admin,
):
    """Plan A+B, un solo fichaje en C → 2 chips de plan + 1 de fichaje (sin duplicar C)."""
    from app.services.auditoria_hoy_service import roster_hoy

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    hoy = today_local()
    a = _obra(session, 'Plan A', 'HD-1', user_jefe)
    b = _obra(session, 'Plan B', 'HD-2', user_jefe)
    c = _obra(session, 'Colegio', 'HD-3', user_jefe)
    session.add(Asignacion(user_id=user_operario.id, obra_id=a.id, fecha=hoy))
    session.add(Asignacion(user_id=user_operario.id, obra_id=b.id, fecha=hoy))
    # Materialización típica: un Conflicto por cada obra de plan, mismo obra_real.
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=hoy,
        obra_planificada_id=a.id, obra_real_id=c.id,
        check_in=datetime.combine(hoy, time(8, 0)),
        estado='Conflicto',
    ))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=hoy,
        obra_planificada_id=b.id, obra_real_id=c.id,
        check_in=datetime.combine(hoy, time(8, 0)),
        estado='Conflicto',
    ))
    session.commit()

    data = roster_hoy(user_admin, hoy=hoy)
    p = data['personas'][0]
    assert len(p['plan']) == 2
    assert all(c['chip'] == 'desvio' for c in p['plan'])
    assert all(c['label'] == 'No fichó aquí' for c in p['plan'])
    assert len(p['fichajes']) == 1
    assert p['fichajes'][0]['obra_id'] == c.id
    assert p['fichajes'][0]['en_plan'] is False
    assert p['fichajes'][0]['label'] == 'Fuera de plan'
    assert p['fichajes'][0]['destino'] == 'resolver'
    assert p['fichajes'][0]['registro_id']
    assert p['plan'][0]['destino'] == 'resolver'
    assert p['tiene_problema'] is True
    assert p['tono_fila'] == 'problema'


def test_roster_hoy_falta_confirmada_en_desvio_parcial(
    session, tenant_soltec, user_operario, user_jefe, user_admin,
):
    """Tras «Confirmar falta» el plan pinta Falta aunque el fichaje real siga pendiente."""
    from datetime import timezone

    from app.services.auditoria_hoy_service import roster_hoy

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    hoy = today_local()
    a = _obra(session, 'Plan A', 'HF-1', user_jefe)
    b = _obra(session, 'Plan B', 'HF-2', user_jefe)
    c = _obra(session, 'Colegio', 'HF-3', user_jefe)
    session.add(Asignacion(user_id=user_operario.id, obra_id=a.id, fecha=hoy))
    session.add(Asignacion(user_id=user_operario.id, obra_id=b.id, fecha=hoy))
    ack_at = datetime.now(timezone.utc)
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=hoy,
        obra_planificada_id=a.id, obra_real_id=c.id,
        check_in=datetime.combine(hoy, time(8, 0)),
        estado='Conflicto',
        desvio_ack_plan_at=ack_at,
        desvio_decision_plan='mantener_falta',
    ))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=hoy,
        obra_planificada_id=b.id, obra_real_id=c.id,
        check_in=datetime.combine(hoy, time(8, 0)),
        estado='Conflicto',
        desvio_ack_plan_at=ack_at,
        desvio_decision_plan='mantener_falta',
    ))
    session.commit()

    data = roster_hoy(user_admin, hoy=hoy)
    p = data['personas'][0]
    assert all(c['chip'] == 'falta' for c in p['plan'])
    assert all(c['label'] == 'Falta' for c in p['plan'])
    assert data['totales']['falta'] == 2
    assert data['totales'].get('desvio', 0) == 0
    # El fichaje fuera de plan sigue pendiente → sigue siendo problema.
    assert len(p['fichajes']) == 1
    assert p['fichajes'][0]['chip'] == 'desvio'
    assert p['tono_fila'] == 'problema'
    # Sigue enlazando a Por resolver (falta aceptar el fichaje real).
    assert all(c['destino'] == 'resolver' for c in p['plan'])


def test_roster_hoy_resuelto_movido_cubre_nueva_plaza(
    session, tenant_soltec, user_operario, user_jefe, user_admin,
):
    """Tras Confirmar desvío: asignado a la obra real, registro con plan=antigua.

    Sin puente plaza↔fichaje Hoy pintaba «Sin fichar» en plan y «Según plan»
    en fichaje para la misma obra.
    """
    from app.services.auditoria_hoy_service import roster_hoy

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    hoy = today_local()
    mestalla = _obra(session, 'Nou Mestalla', 'S25/250', user_jefe)
    marina = _obra(session, 'Marina Port', 'SG26/010', user_jefe)
    # Tras liberar plan + aceptar entrada: solo asignación en obra real.
    session.add(Asignacion(user_id=user_operario.id, obra_id=marina.id, fecha=hoy))
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=hoy,
        obra_planificada_id=mestalla.id, obra_real_id=marina.id,
        check_in=datetime.combine(hoy, time(6, 51)),
        estado='Resuelto_Movido',
    ))
    session.commit()

    data = roster_hoy(user_admin, hoy=hoy)
    p = data['personas'][0]
    assert len(p['plan']) == 1
    assert p['plan'][0]['obra_id'] == marina.id
    assert p['plan'][0]['chip'] == 'ok'
    assert p['plan'][0]['label'] == 'Cumplió'
    assert len(p['fichajes']) == 1
    assert p['fichajes'][0]['obra_id'] == marina.id
    assert p['fichajes'][0]['en_plan'] is True
    assert p['fichajes'][0]['label'] == 'Según plan'
    assert p['fichajes'][0]['entrada']  # hora de entrada presente
    assert p['tono_fila'] == 'ok'
    assert data['totales']['ok'] == 1
    assert data['totales'].get('sin_fichar', 0) == 0
