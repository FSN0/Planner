"""Datos del portal de una subcontrata: inicio, equipo, sin horas sensibles."""
from __future__ import annotations

from collections import defaultdict

from app.models import Company, RegistroFichaje, User
from app.services.certificacion_service import estado_mes, panel_certificacion_subcontrata_obras
from app.services.compliance_rules import fichaje_verificado
from app.services.documentacion_service import filas_empresa, filas_persona, resumir
from app.utils.timezone_utils import today_local


def _usuarios(company_id: int, *, solo_activos: bool = False) -> list[User]:
    q = User.query.filter_by(company_id=company_id, is_deleted=False)
    if solo_activos:
        q = q.filter_by(active=True)
    return q.order_by(User.name, User.lastname).all()


def panel(company: Company) -> dict:
    from datetime import timedelta

    hoy = today_local()
    usuarios = _usuarios(company.id)
    activos = [u for u in usuarios if u.active]
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

    cert_estado = estado_mes(company.id, hoy.year, hoy.month, vista_subcontrata=True)
    cert_pendientes = 0
    try:
        filas_cert = panel_certificacion_subcontrata_obras(
            company, anio=hoy.year, mes=hoy.month,
        )
        cert_pendientes = sum(1 for f in filas_cert if f.get('requiere_accion'))
    except Exception:
        cert_pendientes = 0

    docs_pendientes = int(docs.get('errores') or 0)
    docs_avisos = int(docs.get('avisos') or 0)

    # CTA principal: lo más urgente
    if docs_pendientes:
        cta = 'documentacion'
    elif cert_pendientes or cert_estado in ('recibida', 'rechazada', 'borrador'):
        cta = 'certificacion'
    elif not vistos_persona:
        cta = 'calendario'
    else:
        cta = 'certificacion'

    return {
        'hoy': hoy,
        'en_obra_hoy': len(vistos_persona),
        'obras_hoy': [
            {'obra': nombre, 'personas': personas}
            for nombre, personas in sorted(obras_hoy.items())
        ],
        'obras_hoy_count': len(obras_hoy),
        'personas_mes': len(personas_mes),
        'obras_mes': sorted(obras_mes),
        'jornadas_mes': len(jornadas),
        'certificacion': cert_estado,
        'cert_pendientes': cert_pendientes,
        'documentacion': docs,
        'docs_pendientes': docs_pendientes,
        'docs_avisos': docs_avisos,
        'equipo_activo': len(activos),
        'equipo_total': len(usuarios),
        'cta_principal': cta,
    }


def listado_personal(company: Company) -> list[dict]:
    """Equipo de la subcontrata para el listado del portal."""
    usuarios = _usuarios(company.id)
    out = []
    for u in usuarios:
        filas = filas_persona(u)
        docs = resumir(filas) if filas else {'errores': 0, 'avisos': 0}
        out.append({
            'user': u,
            'nombre': f'{u.name or ""} {u.lastname or ""}'.strip() or (u.email or '—'),
            'rol': u.role or '',
            'activo': bool(u.active),
            'docs_errores': int(docs.get('errores') or 0),
            'docs_avisos': int(docs.get('avisos') or 0),
        })
    return out


def usuario_de_company(company: Company, user_id: int) -> User | None:
    u = User.query.filter_by(
        id=int(user_id),
        company_id=company.id,
        is_deleted=False,
    ).first()
    return u


def ficha_trabajador(company: Company, worker: User) -> dict:
    """KPIs de ficha portal: docs + días asignados / por obra (mes en curso)."""
    from collections import Counter
    from datetime import timedelta

    from app.models import Asignacion, Obra

    hoy = today_local()
    mes_ini = hoy.replace(day=1)
    if hoy.month == 12:
        mes_fin = hoy.replace(month=12, day=31)
    else:
        mes_fin = hoy.replace(month=hoy.month + 1, day=1) - timedelta(days=1)

    filas_docs = filas_persona(worker)
    docs = resumir(filas_docs) if filas_docs else {
        'errores': 0, 'avisos': 0, 'ok': 0, 'total': 0,
    }
    docs_ok = int(docs.get('ok') or 0)
    docs_err = int(docs.get('errores') or 0)
    docs_avi = int(docs.get('avisos') or 0)

    asignaciones = Asignacion.query.filter(
        Asignacion.user_id == worker.id,
        Asignacion.fecha >= mes_ini,
        Asignacion.fecha <= mes_fin,
    ).all()
    dias_mes = len({a.fecha for a in asignaciones})
    cont = Counter()
    for a in asignaciones:
        if a.obra_id:
            cont[a.obra_id] += 1
    obras_ids = list(cont.keys())
    nombres = {}
    if obras_ids:
        for o in Obra.query.filter(Obra.id.in_(obras_ids)).all():
            nombres[o.id] = o.nombre or f'#{o.id}'
    por_obra = [
        {'obra_id': oid, 'nombre': nombres.get(oid, f'#{oid}'), 'dias': cont[oid]}
        for oid in sorted(cont.keys(), key=lambda i: (-cont[i], nombres.get(i, '').lower()))
    ]

    hoy_asigs = [a for a in asignaciones if a.fecha == hoy]
    obra_hoy = None
    if hoy_asigs:
        oid = hoy_asigs[0].obra_id
        obra_hoy = nombres.get(oid) if oid in nombres else (
            hoy_asigs[0].obra.nombre if hoy_asigs[0].obra else None
        )
        if not obra_hoy and oid:
            o = Obra.query.get(oid)
            obra_hoy = o.nombre if o else None

    return {
        'hoy': hoy,
        'docs_ok': docs_ok,
        'docs_errores': docs_err,
        'docs_avisos': docs_avi,
        'docs_total': int(docs.get('total') or 0),
        'dias_mes': dias_mes,
        'obras_mes': len(por_obra),
        'por_obra': por_obra,
        'obra_hoy': obra_hoy,
        'asignado_hoy': len(hoy_asigs) > 0,
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
