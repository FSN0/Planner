"""Casa e inercia del cuadrante: cálculo sin filas fantasma."""
from datetime import timedelta

from sqlalchemy import text

from app.models import Asignacion, InerciaCorte, Obra
from app.services.assignment_service import process_assignment_action, process_unassign_action
from app.services.inercia_service import (
    ESTADO_CAMBIO_TAJO,
    ESTADO_CONFLICTO,
    ESTADO_CORRECTO,
    ESTADO_INERCIA,
    ESTADO_PARACAIDISTA,
    casa_en_fecha,
    celdas_inercia,
    clasificar_entrada_fichaje,
    cortar_casa,
    ids_ocupados_en_fecha,
)
from app.utils.timezone_utils import today_local


def _laborable(start, offset):
    """offset=0 → ese día o el siguiente laborable; ±N laborables."""
    d = start
    if offset == 0:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d
    step = 1 if offset > 0 else -1
    seen = 0
    while seen < abs(offset):
        d += timedelta(days=step)
        if d.weekday() < 5:
            seen += 1
    return d


def test_clasificar_hecho_en_obra_fichada_es_correcto():
    assert clasificar_entrada_fichaje(
        obra_fichada_id=1,
        planificado_en_obra_fichada=True,
        otras_obras_planificadas_ids=[],
        casa_obra_id=None,
    ).estado == ESTADO_CORRECTO


def test_clasificar_hecho_en_otra_obra_es_conflicto():
    out = clasificar_entrada_fichaje(
        obra_fichada_id=2,
        planificado_en_obra_fichada=False,
        otras_obras_planificadas_ids=[1],
        casa_obra_id=1,
    )
    assert out.estado == ESTADO_CONFLICTO
    assert out.obra_planificada_id == 1
    assert out.materializar is False


def test_clasificar_ficha_en_casa_es_inercia():
    out = clasificar_entrada_fichaje(
        obra_fichada_id=1,
        planificado_en_obra_fichada=False,
        otras_obras_planificadas_ids=[],
        casa_obra_id=1,
    )
    assert out.estado == ESTADO_INERCIA
    assert out.materializar is True


def test_clasificar_cambio_de_tajo():
    out = clasificar_entrada_fichaje(
        obra_fichada_id=2,
        planificado_en_obra_fichada=False,
        otras_obras_planificadas_ids=[],
        casa_obra_id=1,
    )
    assert out.estado == ESTADO_CAMBIO_TAJO
    assert out.obra_planificada_id == 1
    assert out.materializar is True


def test_clasificar_primer_fichaje_auto():
    out = clasificar_entrada_fichaje(
        obra_fichada_id=1,
        planificado_en_obra_fichada=False,
        otras_obras_planificadas_ids=[],
        casa_obra_id=None,
        aceptar_primer_fichaje=True,
    )
    assert out.estado == ESTADO_INERCIA


def test_clasificar_primer_fichaje_paracaidista():
    out = clasificar_entrada_fichaje(
        obra_fichada_id=1,
        planificado_en_obra_fichada=False,
        otras_obras_planificadas_ids=[],
        casa_obra_id=None,
        aceptar_primer_fichaje=False,
    )
    assert out.estado == ESTADO_PARACAIDISTA
    assert out.materializar is False


def _path(session, tenant_soltec):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))


def test_casa_sigue_al_dia_siguiente(
    session, tenant_soltec, user_operario, obra_activa,
):
    _path(session, tenant_soltec)
    hoy = today_local()
    ancla = _laborable(hoy, -1)
    dia = _laborable(hoy, 0)
    manana = _laborable(dia, 1)
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=obra_activa.id, fecha=ancla,
        company_id=user_operario.company_id,
    ))
    session.commit()
    assert casa_en_fecha(user_operario.id, dia) == obra_activa.id
    celdas = celdas_inercia([user_operario.id], dia, manana)
    assert (user_operario.id, dia) in celdas
    assert (user_operario.id, manana) in celdas
    assert user_operario.id in ids_ocupados_en_fecha(dia, [user_operario.id])


def test_corte_a_libres_rompe_la_casa(
    session, tenant_soltec, user_operario, obra_activa,
):
    _path(session, tenant_soltec)
    ancla = _laborable(today_local(), -1)
    dia = _laborable(today_local(), 0)
    siguiente = _laborable(dia, 1)
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=obra_activa.id, fecha=ancla,
        company_id=user_operario.company_id,
    ))
    session.commit()
    cortar_casa(user_operario.id, dia)
    session.commit()
    assert casa_en_fecha(user_operario.id, dia) is None
    assert casa_en_fecha(user_operario.id, siguiente) is None
    assert (user_operario.id, dia) not in celdas_inercia(
        [user_operario.id], dia, siguiente,
    )


def test_inercia_no_abre_conflicto_al_asignar_otra_obra(
    session, tenant_soltec, user_admin, user_operario, obra_activa, user_jefe,
):
    _path(session, tenant_soltec)
    ancla = _laborable(today_local(), -1)
    dia = _laborable(today_local(), 0)
    siguiente = _laborable(dia, 1)
    otra = Obra(
        codigo='OBR-INERCIA',
        nombre='Tajo B',
        estado='En Curso',
        jefe_obra_id=user_jefe.id,
        fecha_inicio=ancla,
    )
    session.add(otra)
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=obra_activa.id, fecha=ancla,
        company_id=user_operario.company_id,
    ))
    session.commit()

    result = process_assignment_action(
        actor_user=user_admin,
        worker_id=user_operario.id,
        target_obra_id=otra.id,
        date_list=[dia.isoformat()],
        mode='check',
    )
    assert result.get('success') is True
    assert result.get('conflict') is not True
    assert Asignacion.query.filter_by(
        user_id=user_operario.id, obra_id=otra.id, fecha=dia,
    ).first() is not None
    assert casa_en_fecha(user_operario.id, siguiente) == otra.id


def test_soltar_inercia_a_libres_persiste_corte(
    session, tenant_soltec, user_admin, user_operario, obra_activa,
):
    _path(session, tenant_soltec)
    ancla = _laborable(today_local(), -1)
    dia = _laborable(today_local(), 0)
    siguiente = _laborable(dia, 1)
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=obra_activa.id, fecha=ancla,
        company_id=user_operario.company_id,
    ))
    session.commit()

    result = process_unassign_action(
        actor_user=user_admin,
        worker_id=user_operario.id,
        target_obra_id=obra_activa.id,
        date_list=[dia.isoformat()],
        mode='selected',
    )
    assert result.get('success') is True
    assert InerciaCorte.query.filter_by(
        user_id=user_operario.id, fecha=dia,
    ).first() is not None
    assert casa_en_fecha(user_operario.id, dia) is None
    assert casa_en_fecha(user_operario.id, siguiente) is None


def test_fin_de_semana_no_pinta_inercia(
    session, tenant_soltec, user_operario, obra_activa,
):
    _path(session, tenant_soltec)
    from datetime import date
    viernes = date(2026, 9, 4)
    sabado = date(2026, 9, 5)
    lunes_sig = date(2026, 9, 7)
    if today_local() > lunes_sig:
        viernes = _laborable(today_local(), -1)
        while viernes.weekday() != 4:
            viernes = _laborable(viernes, -1)
        sabado = viernes + timedelta(days=1)
        lunes_sig = viernes + timedelta(days=3)
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=obra_activa.id, fecha=viernes,
        company_id=user_operario.company_id,
    ))
    session.commit()
    assert casa_en_fecha(user_operario.id, sabado) == obra_activa.id
    assert (user_operario.id, sabado) not in celdas_inercia(
        [user_operario.id], sabado, sabado,
    )
    assert (user_operario.id, lunes_sig) in celdas_inercia(
        [user_operario.id], lunes_sig, lunes_sig,
    )
    from app.services.inercia_service import bloques_inercia_rango
    bloques = bloques_inercia_rango(
        [user_operario.id], lunes_sig, lunes_sig + timedelta(days=10),
    )
    assert len(bloques) == 1
    assert bloques[0]['fecha_inicio'] == lunes_sig
    assert bloques[0]['fecha_fin'] >= lunes_sig + timedelta(days=4)


def test_multiobra_no_inventa_casa(
    session, tenant_soltec, user_operario, obra_activa, user_jefe,
):
    _path(session, tenant_soltec)
    ancla = _laborable(today_local(), -1)
    dia = _laborable(today_local(), 0)
    otra = Obra(
        codigo='OBR-MULTI',
        nombre='Tajo C',
        estado='En Curso',
        jefe_obra_id=user_jefe.id,
        fecha_inicio=ancla,
    )
    session.add(otra)
    session.flush()
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=obra_activa.id, fecha=ancla,
        company_id=user_operario.company_id,
    ))
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=otra.id, fecha=ancla,
        company_id=user_operario.company_id,
    ))
    session.commit()
    assert casa_en_fecha(user_operario.id, dia) is None
    assert (user_operario.id, dia) not in celdas_inercia(
        [user_operario.id], dia, dia,
    )


def test_inercia_no_pinta_el_pasado(
    session, tenant_soltec, user_operario, obra_activa,
):
    _path(session, tenant_soltec)
    hoy = today_local()
    ancla = _laborable(hoy, -5)
    pasado = _laborable(hoy, -2)
    futuro = _laborable(hoy, 1)
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=obra_activa.id, fecha=ancla,
        company_id=user_operario.company_id,
    ))
    session.commit()
    celdas = celdas_inercia(
        [user_operario.id], ancla, futuro,
    )
    assert all(fecha >= hoy for (_uid, fecha) in celdas)
    assert celdas_inercia([user_operario.id], ancla, pasado) == {}
    assert (user_operario.id, pasado) not in celdas
    assert (user_operario.id, ancla) not in celdas
    assert (user_operario.id, futuro) not in celdas
    from app.services.inercia_service import bloques_inercia_rango
    assert bloques_inercia_rango(
        [user_operario.id], ancla, futuro,
    ) == []


def test_parado_varios_dias_no_genera_inercia(
    session, tenant_soltec, user_operario, obra_activa,
):
    _path(session, tenant_soltec)
    hoy = _laborable(today_local(), 0)
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=obra_activa.id,
        fecha=_laborable(today_local(), -5),
        company_id=user_operario.company_id,
    ))
    session.commit()
    assert casa_en_fecha(user_operario.id, hoy) is None
    assert (user_operario.id, hoy) not in celdas_inercia(
        [user_operario.id], hoy, hoy,
    )


def test_inercia_sigue_la_obra_de_ayer_no_una_vieja(
    session, tenant_soltec, user_operario, obra_activa, user_jefe,
):
    _path(session, tenant_soltec)
    hoy = _laborable(today_local(), 0)
    ayer = _laborable(today_local(), -1)
    vieja = _laborable(today_local(), -5)
    otra = Obra(
        codigo='OBR-AYER',
        nombre='Tajo de ayer',
        estado='En Curso',
        jefe_obra_id=user_jefe.id,
        fecha_inicio=vieja,
    )
    session.add(otra)
    session.flush()
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=obra_activa.id, fecha=vieja,
        company_id=user_operario.company_id,
    ))
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=otra.id, fecha=ayer,
        company_id=user_operario.company_id,
    ))
    session.commit()
    assert casa_en_fecha(user_operario.id, hoy) == otra.id
    celdas = celdas_inercia([user_operario.id], hoy, _laborable(hoy, 1))
    assert all(oid == otra.id for oid in celdas.values())
    assert (user_operario.id, hoy) in celdas


def test_inercia_no_pinta_mas_alla_de_un_mes(
    session, tenant_soltec, user_operario, obra_activa,
):
    _path(session, tenant_soltec)
    hoy = today_local()
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=obra_activa.id,
        fecha=_laborable(hoy, -1),
        company_id=user_operario.company_id,
    ))
    session.commit()
    lejano = hoy + timedelta(days=40)
    while lejano.weekday() >= 5:
        lejano += timedelta(days=1)
    celdas = celdas_inercia([user_operario.id], hoy, lejano)
    assert (user_operario.id, _laborable(hoy, 1)) in celdas
    assert (user_operario.id, lejano) not in celdas
    assert all((fecha - hoy).days <= 31 for (_uid, fecha) in celdas)


def test_inercia_no_pinta_dias_de_vacaciones(
    session, tenant_soltec, user_operario, obra_activa,
):
    """Vacaciones aprobadas: no fantasma (no se sabe a qué obra vuelve)."""
    from app.models import AusenciaPlanificada, LEAVE_STATUS_APROBADA, LEAVE_SOURCE_MANUAL

    _path(session, tenant_soltec)
    hoy = today_local()
    ancla = _laborable(hoy, -1)
    dia = _laborable(hoy, 0)
    manana = _laborable(dia, 1)
    session.add(Asignacion(
        user_id=user_operario.id, obra_id=obra_activa.id, fecha=ancla,
        company_id=user_operario.company_id,
    ))
    session.add(AusenciaPlanificada(
        user_id=user_operario.id,
        fecha_inicio=dia,
        fecha_fin=manana,
        dias=2,
        tipo='Vacaciones',
        estado=LEAVE_STATUS_APROBADA,
        origen=LEAVE_SOURCE_MANUAL,
    ))
    session.commit()

    celdas = celdas_inercia([user_operario.id], dia, manana)
    assert (user_operario.id, dia) not in celdas
    assert (user_operario.id, manana) not in celdas
    assert user_operario.id not in ids_ocupados_en_fecha(dia, [user_operario.id])

