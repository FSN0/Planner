"""Datos del panel de una subcontrata: dónde están, sin horas."""
from __future__ import annotations

from collections import defaultdict

from app.models import Company, RegistroFichaje, User
from app.services.certificacion_service import estado_mes
from app.services.compliance_rules import fichaje_verificado
from app.services.documentacion_service import filas_empresa, filas_persona, resumir
from app.utils.timezone_utils import today_local


def _usuarios(company_id: int) -> list[User]:
    return User.query.filter_by(company_id=company_id, is_deleted=False).order_by(User.name).all()


def panel(company: Company) -> dict:
    from datetime import timedelta
    hoy = today_local()
    usuarios = _usuarios(company.id)
    ids = [u.id for u in usuarios]
    nombres = {u.id: f'{u.name} {u.lastname}'.strip() for u in usuarios}
    fichajes_hoy = []
    if ids:
        fichajes_hoy = RegistroFichaje.query.filter(
            RegistroFichaje.user_id.in_(ids),
            RegistroFichaje.fecha == hoy,
            RegistroFichaje.obra_real_id.isnot(None),
            RegistroFichaje.check_in.isnot(None),
        ).all()
    obras_hoy = defaultdict(list)
    vistos_persona = set()
    for reg in fichajes_hoy:
        nombre_obra = reg.obra_real.nombre if reg.obra_real else 'Obra'
        obras_hoy[nombre_obra].append({
            'nombre': nombres.get(reg.user_id, ''),
            'verificado': fichaje_verificado(reg.estado_odoo),
        })
        vistos_persona.add(reg.user_id)

    desde = hoy.replace(day=1)
    if hoy.month == 12:
        hasta = hoy.replace(month=12, day=31)
    else:
        hasta = hoy.replace(month=hoy.month + 1, day=1) - timedelta(days=1)
    fichajes_mes = []
    if ids:
        fichajes_mes = RegistroFichaje.query.filter(
            RegistroFichaje.user_id.in_(ids),
            RegistroFichaje.fecha >= desde,
            RegistroFichaje.fecha <= hasta,
            RegistroFichaje.obra_real_id.isnot(None),
            RegistroFichaje.check_in.isnot(None),
        ).all()
    personas_mes = {r.user_id for r in fichajes_mes}
    obras_mes = {r.obra_real.nombre for r in fichajes_mes if r.obra_real}
    jornadas = {(r.user_id, r.obra_real_id, r.fecha) for r in fichajes_mes}

    filas = filas_empresa(company)
    for persona in usuarios:
        filas.extend(filas_persona(persona))
    docs = resumir(filas)
    return {
        'hoy': hoy,
        'en_obra_hoy': len(vistos_persona),
        'obras_hoy': [{'obra': nombre, 'personas': personas} for nombre, personas in sorted(obras_hoy.items())],
        'obras_hoy_count': len(obras_hoy),
        'personas_mes': len(personas_mes),
        'obras_mes': sorted(obras_mes),
        'jornadas_mes': len(jornadas),
        'certificacion': estado_mes(company.id, hoy.year, hoy.month, vista_subcontrata=True),
        'documentacion': docs,
    }


def donde_estan(company: Company, fecha) -> list[dict]:
    usuarios = _usuarios(company.id)
    ids = [u.id for u in usuarios]
    if not ids:
        return []
    nombres = {u.id: f'{u.name} {u.lastname}'.strip() for u in usuarios}
    regs = RegistroFichaje.query.filter(
        RegistroFichaje.user_id.in_(ids),
        RegistroFichaje.fecha == fecha,
        RegistroFichaje.obra_real_id.isnot(None),
        RegistroFichaje.check_in.isnot(None),
    ).all()
    obras = defaultdict(list)
    for reg in regs:
        nombre_obra = reg.obra_real.nombre if reg.obra_real else 'Obra'
        obras[nombre_obra].append({
            'nombre': nombres.get(reg.user_id, ''),
            'verificado': fichaje_verificado(reg.estado_odoo),
        })
    return [{'obra': k, 'personas': v} for k, v in sorted(obras.items())]
