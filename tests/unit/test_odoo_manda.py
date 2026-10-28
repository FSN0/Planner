"""«Odoo manda»: una corrección de RRHH en Odoo se acepta sin pedir acción a nadie."""
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

from app.models import Asignacion, Obra, RegistroFichaje
from app.services import auditoria_casos_service as acs
from app.services.desvio_fichaje_service import (
    ESTADO_ACEPTADO_ODOO,
    aplicar_correccion_odoo_dia,
    es_falta_automatica,
    usuarios_con_correccion_odoo,
)
from app.utils.timezone_utils import today_local


def _obra(session, nombre, codigo):
    o = Obra(nombre=nombre, codigo=codigo, estado='En Curso', is_deleted=False)
    session.add(o)
    session.flush()
    return o


def _search_path(session, tenant):
    session.execute(text(f'SET search_path TO {tenant.schema_name}'))


def test_pata_abierta_de_otra_obra_pasa_a_falta_automatica(
    session, tenant_soltec, user_operario,
):
    _search_path(session, tenant_soltec)
    dia = today_local() - timedelta(days=2)
    z = _obra(session, 'Obra Z', 'Z-1')
    y = _obra(session, 'Obra Y', 'Y-1')
    w = _obra(session, 'Obra W', 'W-1')
    for o in (z, w):
        session.add(Asignacion(user_id=user_operario.id, obra_id=o.id, fecha=dia))
    # RRHH corrigió el día en Odoo (cambió el fichaje a Y).
    session.add(RegistroFichaje(
        user_id=user_operario.id, fecha=dia, estado='Sobreescrito_RRHH',
        obra_real_id=y.id, notas_resolucion=f'{z.id}||Z-1||Obra Z||{y.id}||Y-1||Obra Y||Modificado de Obra||Correcto',
    ))
    pata_z = RegistroFichaje(
        user_id=user_operario.id, fecha=dia, estado='Sin_Registro', obra_planificada_id=z.id,
    )
    # Esta ya la resolvió una persona: no se toca.
    pata_w = RegistroFichaje(
        user_id=user_operario.id, fecha=dia, estado='Resuelto_Ignorado', obra_planificada_id=w.id,
    )
    session.add_all([pata_z, pata_w])
    session.commit()

    assert user_operario.id in usuarios_con_correccion_odoo(dia)
    assert aplicar_correccion_odoo_dia(user_operario.id, dia) == 1
    session.commit()

    pata_z = RegistroFichaje.query.get(pata_z.id)
    pata_w = RegistroFichaje.query.get(pata_w.id)
    assert pata_z.estado == 'Falta' and es_falta_automatica(pata_z)
    assert pata_z.resuelto_por_id is None
    assert pata_w.estado == 'Resuelto_Ignorado'
    assert acs.origen_registro(pata_z) == acs.ORIGEN_ODOO
    assert 'automática' in acs.resultado_registro(pata_z)
    # Idempotente.
    assert aplicar_correccion_odoo_dia(user_operario.id, dia) == 0


def test_fichaje_de_odoo_sin_plan_se_acepta_sin_desvio(
    session, tenant_soltec, user_operario,
):
    from app.services.sync_service import _procesar_fichaje_dia_corregido

    _search_path(session, tenant_soltec)
    dia = today_local() - timedelta(days=2)
    y = _obra(session, 'Obra Y', 'Y-2')
    session.commit()
    ci = datetime.combine(dia, time(7, 0))
    co = datetime.combine(dia, time(15, 0))
    f = {'note': 'corregido por RRHH'}

    # Con plan exacto en Y: lo gestiona el flujo normal (Correcto).
    assert _procesar_fichaje_dia_corregido(
        user_operario, y, dia, f, ci, co, plan_exacto=True,
    ) is False

    # Sin plan en Y: queda aceptado desde Odoo, no «Correcto», sin pendiente.
    assert _procesar_fichaje_dia_corregido(
        user_operario, y, dia, f, ci, co, plan_exacto=False,
    ) is True
    session.commit()
    reg = RegistroFichaje.query.filter_by(user_id=user_operario.id, fecha=dia, obra_real_id=y.id).one()
    assert reg.estado == ESTADO_ACEPTADO_ODOO
    assert reg.obra_planificada_id is None
    assert reg.estado not in acs.ESTADOS_PENDIENTES
    assert acs.origen_registro(reg) == acs.ORIGEN_ODOO

    # Una segunda sincronización no duplica ni cambia el estado.
    assert _procesar_fichaje_dia_corregido(
        user_operario, y, dia, f, ci, co, plan_exacto=False,
    ) is True
    session.commit()
    assert RegistroFichaje.query.filter_by(
        user_id=user_operario.id, fecha=dia, obra_real_id=y.id,
    ).count() == 1
