"""Certificación de horario: dos propuestas por mes y cierre al aceptar."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal

from app import db
from app.models import (
    CertificacionLinea,
    CertificacionPropuesta,
    Company,
    Obra,
    RegistroFichaje,
    User,
)
from app.services.compliance_rules import (
    cuantizar,
    estado_fichaje_agregado,
    firma_lineas,
    horas_desde_datetimes,
    importe_linea,
    intervalos_solapan,
    propuestas_coinciden,
)
from app.services.config_service import get_tenant_config, set_tenant_config
from app.utils.timezone_utils import utc_now

CONFIG_PRECIO = 'precio_hora_defecto'
DIR_SUB = 'subcontrata_a_empresa'
DIR_EMP = 'empresa_a_subcontrata'


def precio_plataforma() -> Decimal:
    raw = get_tenant_config(CONFIG_PRECIO, default='0')
    return cuantizar(raw) or Decimal('0.00')


def guardar_precio_plataforma(valor) -> None:
    set_tenant_config(CONFIG_PRECIO, str(cuantizar(valor) or Decimal('0.00')))


def precio_empresa(company: Company) -> Decimal:
    if company.precio_hora is not None:
        return cuantizar(company.precio_hora) or Decimal('0.00')
    return precio_plataforma()


def guardar_precio_empresa(company: Company, valor) -> Decimal:
    """Precio hora de esta subcontrata. Vacío = hereda el de la plataforma."""
    raw = (str(valor) if valor is not None else '').strip()
    if not raw:
        company.precio_hora = None
        return precio_empresa(company)
    precio = cuantizar(valor)
    if precio is None:
        raise ValueError('El precio hora no es válido.')
    company.precio_hora = precio
    return precio


def aplicar_precio_borrador(company: Company, anio: int, mes: int, precio: Decimal) -> int:
    """Actualiza €/h de las líneas en borrador del mes con el nuevo precio por defecto."""
    props = CertificacionPropuesta.query.filter_by(
        company_id=company.id, anio=anio, mes=mes, estado='borrador',
    ).all()
    n = 0
    for prop in props:
        for ln in prop.lineas:
            ln.precio_hora = precio
            n += 1
    return n


def _mes_rango(anio: int, mes: int) -> tuple[date, date]:
    inicio = date(anio, mes, 1)
    if mes == 12:
        fin = date(anio + 1, 1, 1)
    else:
        fin = date(anio, mes + 1, 1)
    from datetime import timedelta
    return inicio, fin - timedelta(days=1)


def _esqueleto(company_id: int, anio: int, mes: int, obra_id: int | None = None) -> list[dict]:
    inicio, fin = _mes_rango(anio, mes)
    usuarios = {
        u.id: u for u in User.query.filter(
            User.company_id == company_id,
            User.is_deleted.is_(False),
        ).all()
    }
    if not usuarios:
        return []
    q = RegistroFichaje.query.filter(
        RegistroFichaje.user_id.in_(list(usuarios)),
        RegistroFichaje.fecha >= inicio,
        RegistroFichaje.fecha <= fin,
        RegistroFichaje.obra_real_id.isnot(None),
        RegistroFichaje.check_in.isnot(None),
    )
    if obra_id is not None:
        q = q.filter(RegistroFichaje.obra_real_id == obra_id)
    regs = q.all()
    grupos = defaultdict(list)
    for reg in regs:
        grupos[(reg.user_id, reg.obra_real_id, reg.fecha)].append(reg)

    por_persona_dia = defaultdict(list)
    for key, items in grupos.items():
        por_persona_dia[(key[0], key[2])].append((key, items))

    solapes = set()
    for pares in por_persona_dia.values():
        if len(pares) < 2:
            continue
        for i, (ka, ia) in enumerate(pares):
            for kb, ib in pares[i + 1:]:
                for a in ia:
                    for b in ib:
                        if intervalos_solapan(a.check_in, a.check_out, b.check_in, b.check_out):
                            solapes.add(ka)
                            solapes.add(kb)

    filas = []
    for key, items in grupos.items():
        user_id, obra_id, fecha = key
        horas = Decimal('0.00')
        alguna = False
        inicio_h = None
        fin_h = None
        for reg in items:
            trozo = horas_desde_datetimes(reg.check_in, reg.check_out)
            if trozo is not None:
                horas += trozo
                alguna = True
            if reg.check_in and (inicio_h is None or reg.check_in < inicio_h):
                inicio_h = reg.check_in
            if reg.check_out and (fin_h is None or reg.check_out > fin_h):
                fin_h = reg.check_out
        filas.append({
            'user_id': user_id,
            'obra_id': obra_id,
            'fecha': fecha,
            'hora_inicio': inicio_h.time().replace(second=0, microsecond=0) if inicio_h else None,
            'hora_fin': fin_h.time().replace(second=0, microsecond=0) if fin_h and alguna else None,
            'horas': horas if alguna else None,
            'estado_fichaje': estado_fichaje_agregado([r.estado_odoo for r in items]),
            'solape': key in solapes,
        })
    filas.sort(key=lambda f: (f['obra_id'], f['fecha'], f['user_id']))
    return filas


def repartir_propuesta_por_obras(prop: CertificacionPropuesta) -> list[CertificacionPropuesta]:
    """Si hay líneas de varias obras, crea una propuesta por obra (migración/reparación)."""
    by_obra: dict[int, list[CertificacionLinea]] = defaultdict(list)
    for ln in list(prop.lineas):
        if ln.obra_id is None:
            continue
        by_obra[int(ln.obra_id)].append(ln)
    if len(by_obra) <= 1:
        if by_obra and prop.obra_id not in by_obra:
            prop.obra_id = next(iter(by_obra))
        return [prop]
    obra_ids = sorted(by_obra.keys())
    prop.obra_id = obra_ids[0]
    out = [prop]
    for oid in obra_ids[1:]:
        nueva = CertificacionPropuesta(
            company_id=prop.company_id,
            obra_id=oid,
            anio=prop.anio,
            mes=prop.mes,
            direccion=prop.direccion,
            estado=prop.estado,
            comentario_rechazo=prop.comentario_rechazo,
            enviada_at=prop.enviada_at,
            aceptada_at=prop.aceptada_at,
            enviada_por_id=prop.enviada_por_id,
            respondida_por_id=prop.respondida_por_id,
            created_at=prop.created_at,
        )
        db.session.add(nueva)
        db.session.flush()
        for ln in by_obra[oid]:
            ln.propuesta_id = nueva.id
        out.append(nueva)
    db.session.flush()
    return out


def obras_ids_certificacion(
    company_id: int,
    anio: int,
    mes: int,
    *,
    obra_ids: set[int] | None = None,
) -> list[int]:
    """Obras con fichaje o propuesta existente en el mes (alcance opcional)."""
    ids: set[int] = set()
    for fila in _esqueleto(company_id, anio, mes):
        ids.add(int(fila['obra_id']))
    props = CertificacionPropuesta.query.filter_by(
        company_id=company_id, anio=anio, mes=mes,
    ).with_entities(CertificacionPropuesta.obra_id).distinct().all()
    for (oid,) in props:
        if oid is not None:
            ids.add(int(oid))
    if obra_ids is not None:
        ids &= set(obra_ids)
    return sorted(ids)


def _get_or_create(
    company: Company, anio: int, mes: int, direccion: str, obra_id: int,
) -> CertificacionPropuesta:
    row = CertificacionPropuesta.query.filter_by(
        company_id=company.id, obra_id=obra_id, anio=anio, mes=mes, direccion=direccion,
    ).first()
    if row:
        return row
    row = CertificacionPropuesta(
        company_id=company.id,
        obra_id=obra_id,
        anio=anio,
        mes=mes,
        direccion=direccion,
        estado='borrador',
    )
    db.session.add(row)
    db.session.flush()
    return row


def sincronizar(
    company: Company, anio: int, mes: int, obra_id: int,
) -> tuple[CertificacionPropuesta, CertificacionPropuesta]:
    """Crea o refresca el par DIR_SUB + DIR_EMP de una obra. Aceptadas no se tocan (salvo pastillas)."""
    precio = precio_empresa(company)
    esqueleto = _esqueleto(company.id, anio, mes, obra_id=obra_id)
    esqueleto_map = {(f['user_id'], f['obra_id'], f['fecha']): f for f in esqueleto}
    par = []
    for direccion in (DIR_SUB, DIR_EMP):
        prop = _get_or_create(company, anio, mes, direccion, obra_id)
        for ln in list(prop.lineas):
            fila = esqueleto_map.get((ln.user_id, ln.obra_id, ln.fecha))
            if fila:
                ln.estado_fichaje = fila['estado_fichaje']
                ln.solape = bool(fila['solape'])
        if prop.estado in ('aceptada', 'cerrada'):
            par.append(prop)
            continue
        if prop.estado != 'borrador':
            par.append(prop)
            continue
        actuales = {(ln.user_id, ln.obra_id, ln.fecha): ln for ln in prop.lineas}
        vistos = set()
        for fila in esqueleto:
            key = (fila['user_id'], fila['obra_id'], fila['fecha'])
            vistos.add(key)
            ln = actuales.get(key)
            if ln is None:
                ln = CertificacionLinea(
                    propuesta_id=prop.id,
                    user_id=fila['user_id'],
                    obra_id=fila['obra_id'],
                    fecha=fila['fecha'],
                    precio_hora=precio,
                    origen_horas='vacio',
                )
                db.session.add(ln)
                prop.lineas.append(ln)
            ln.estado_fichaje = fila['estado_fichaje']
            ln.solape = bool(fila['solape'])
            if ln.precio_hora is None:
                ln.precio_hora = precio
            if direccion == DIR_EMP and ln.origen_horas in ('vacio', 'fichaje'):
                ln.hora_inicio = fila['hora_inicio']
                ln.hora_fin = fila['hora_fin']
                ln.horas = fila['horas']
                ln.origen_horas = 'fichaje'
        for key, ln in actuales.items():
            if key not in vistos and ln.origen_horas in ('vacio', 'fichaje'):
                db.session.delete(ln)
        par.append(prop)
    db.session.flush()
    return par[0], par[1]


def sincronizar_mes(
    company: Company,
    anio: int,
    mes: int,
    *,
    obra_ids: set[int] | None = None,
) -> list[tuple[CertificacionPropuesta, CertificacionPropuesta]]:
    """Sincroniza el par de propuestas de cada obra del mes."""
    return [
        sincronizar(company, anio, mes, oid)
        for oid in obras_ids_certificacion(company.id, anio, mes, obra_ids=obra_ids)
    ]


def periodo_bloqueado(company_id: int, anio: int, mes: int, obra_id: int) -> bool:
    return CertificacionPropuesta.query.filter(
        CertificacionPropuesta.company_id == company_id,
        CertificacionPropuesta.obra_id == obra_id,
        CertificacionPropuesta.anio == anio,
        CertificacionPropuesta.mes == mes,
        CertificacionPropuesta.estado == 'aceptada',
    ).first() is not None


def _otra(direccion: str) -> str:
    return DIR_EMP if direccion == DIR_SUB else DIR_SUB


def guardar_linea(linea: CertificacionLinea, *, hora_inicio, hora_fin, horas, precio) -> None:
    if linea.propuesta.estado != 'borrador':
        raise ValueError('Esta propuesta ya no se puede editar.')
    if periodo_bloqueado(
        linea.propuesta.company_id, linea.propuesta.anio, linea.propuesta.mes, linea.propuesta.obra_id,
    ):
        raise ValueError('Esta obra ya está aceptada en el mes.')
    precio_q = cuantizar(precio)
    if precio_q is None:
        raise ValueError('El precio hora no es válido.')
    linea.precio_hora = precio_q
    # Si llega un total escrito, manda el total y se vacían inicio y fin.
    if horas is not None and horas != '':
        linea.horas = cuantizar(horas)
        linea.hora_inicio = None
        linea.hora_fin = None
        linea.origen_horas = 'manual_total'
        return
    if hora_inicio and hora_fin:
        linea.hora_inicio = hora_inicio
        linea.hora_fin = hora_fin
        linea.horas = horas_desde_datetimes(
            datetime.combine(linea.fecha, hora_inicio),
            datetime.combine(linea.fecha, hora_fin),
        )
        linea.origen_horas = 'manual_tramo'
        # Tramo inválido: se conservan las horas para marcar la fila en rojo al enviar.
        return
    linea.hora_inicio = None
    linea.hora_fin = None
    linea.horas = None
    linea.origen_horas = 'vacio'


def lineas_tramo_invalido(prop: CertificacionPropuesta) -> list[int]:
    """Inicio y fin rellenos pero fin ≤ inicio (horas calculadas a None)."""
    return [
        int(ln.id)
        for ln in prop.lineas
        if ln.hora_inicio is not None
        and ln.hora_fin is not None
        and ln.horas is None
    ]


def restablecer_linea_desde_fichaje(linea: CertificacionLinea) -> None:
    """Vuelve a poner inicio/fin/horas desde el fichaje de la plataforma."""
    prop = linea.propuesta
    if prop.estado != 'borrador':
        raise ValueError('Esta propuesta ya no se puede editar.')
    if periodo_bloqueado(prop.company_id, prop.anio, prop.mes, prop.obra_id):
        raise ValueError('Esta obra ya está aceptada en el mes.')
    filas = _esqueleto(prop.company_id, prop.anio, prop.mes, obra_id=prop.obra_id)
    match = next(
        (
            f for f in filas
            if f['user_id'] == linea.user_id
            and f['obra_id'] == linea.obra_id
            and f['fecha'] == linea.fecha
        ),
        None,
    )
    if not match:
        linea.hora_inicio = None
        linea.hora_fin = None
        linea.horas = None
        linea.origen_horas = 'vacio'
        linea.estado_fichaje = None
        linea.solape = False
        return
    linea.hora_inicio = match['hora_inicio']
    linea.hora_fin = match['hora_fin']
    linea.horas = match['horas']
    linea.origen_horas = 'fichaje'
    linea.estado_fichaje = match['estado_fichaje']
    linea.solape = bool(match['solape'])


def _lineas_completas(prop: CertificacionPropuesta) -> bool:
    if not prop.lineas:
        return True
    return all(ln.horas is not None and ln.precio_hora is not None for ln in prop.lineas)


def _limpiar_rechazo_mes(company_id: int, anio: int, mes: int, obra_id: int) -> None:
    """Quita comentarios de rechazo obsoletos al cerrar el mes."""
    rows = CertificacionPropuesta.query.filter_by(
        company_id=company_id, obra_id=obra_id, anio=anio, mes=mes,
    ).all()
    for row in rows:
        row.comentario_rechazo = None


def _intentar_autoaceptar(company_id: int, anio: int, mes: int, obra_id: int) -> bool:
    a = CertificacionPropuesta.query.filter_by(
        company_id=company_id, obra_id=obra_id, anio=anio, mes=mes,
        direccion=DIR_SUB, estado='enviada',
    ).first()
    b = CertificacionPropuesta.query.filter_by(
        company_id=company_id, obra_id=obra_id, anio=anio, mes=mes,
        direccion=DIR_EMP, estado='enviada',
    ).first()
    if not a or not b:
        return False
    if not propuestas_coinciden(a.lineas, b.lineas):
        return False
    ahora = utc_now()
    for prop in (a, b):
        prop.estado = 'aceptada'
        prop.aceptada_at = ahora
    _limpiar_rechazo_mes(company_id, anio, mes, obra_id)
    return True


def enviar(prop: CertificacionPropuesta, actor_id: int) -> None:
    if prop.estado != 'borrador':
        raise ValueError('Solo se envía un borrador.')
    if periodo_bloqueado(prop.company_id, prop.anio, prop.mes, prop.obra_id):
        raise ValueError('Esta obra ya está aceptada en el mes.')
    if not _lineas_completas(prop):
        raise ValueError('Rellena las horas de todas las filas antes de enviar.')
    prop.estado = 'enviada'
    prop.enviada_at = utc_now()
    prop.enviada_por_id = actor_id
    prop.comentario_rechazo = None
    auto = _intentar_autoaceptar(prop.company_id, prop.anio, prop.mes, prop.obra_id)
    if auto:
        otra = CertificacionPropuesta.query.filter_by(
            company_id=prop.company_id,
            obra_id=prop.obra_id,
            anio=prop.anio,
            mes=prop.mes,
            direccion=_otra(prop.direccion),
        ).first()
        _avisar(prop, actor_id, aceptada=True)
        if otra:
            _avisar(otra, actor_id, aceptada=True)
    else:
        _avisar(prop, actor_id)


def desenviar(prop: CertificacionPropuesta, actor_id: int) -> None:
    """Cancela el envío: vuelve a borrador y deja de verse en el panel de la otra parte."""
    if prop.estado != 'enviada':
        raise ValueError('Solo se puede desenviar una propuesta enviada.')
    if periodo_bloqueado(prop.company_id, prop.anio, prop.mes, prop.obra_id):
        raise ValueError('Esta obra ya está aceptada; no se puede desenviar.')
    prop.estado = 'borrador'
    prop.enviada_at = None
    prop.enviada_por_id = None
    prop.respondida_por_id = None
    prop.comentario_rechazo = None
    _avisar(prop, actor_id, retirada=True)


def aceptar(prop: CertificacionPropuesta, actor_id: int) -> None:
    if prop.estado != 'enviada':
        raise ValueError('No hay una propuesta pendiente de aceptar.')
    ahora = utc_now()
    prop.estado = 'aceptada'
    prop.aceptada_at = ahora
    prop.respondida_por_id = actor_id
    prop.comentario_rechazo = None
    otra = CertificacionPropuesta.query.filter_by(
        company_id=prop.company_id,
        obra_id=prop.obra_id,
        anio=prop.anio,
        mes=prop.mes,
        direccion=_otra(prop.direccion),
    ).first()
    if otra and otra.estado != 'aceptada':
        otra.estado = 'cerrada'
        otra.respondida_por_id = actor_id
        otra.comentario_rechazo = None
    _limpiar_rechazo_mes(prop.company_id, prop.anio, prop.mes, prop.obra_id)
    _avisar(prop, actor_id, aceptada=True)


def rechazar(prop: CertificacionPropuesta, actor_id: int, comentario: str) -> None:
    if prop.estado != 'enviada':
        raise ValueError('Solo se rechaza una propuesta enviada.')
    if not (comentario or '').strip():
        raise ValueError('Escribe por qué no cuadra.')
    prop.estado = 'borrador'
    prop.comentario_rechazo = comentario.strip()
    prop.respondida_por_id = actor_id
    _avisar(prop, actor_id, rechazo=comentario.strip())


def marcar_discrepancias(prop: CertificacionPropuesta, ids_marcados: set[int], notas: dict) -> None:
    """Marca filas con nota (o ids explícitos). Sin tick: la nota basta."""
    if prop.estado != 'enviada':
        return
    ids = set(ids_marcados or ())
    notas = notas or {}
    for lid, nota in notas.items():
        if (nota or '').strip():
            try:
                ids.add(int(lid))
            except (TypeError, ValueError):
                pass
    for ln in prop.lineas:
        nota = (notas.get(ln.id) or notas.get(str(ln.id)) or '').strip() or None
        ln.discrepancia = ln.id in ids or bool(nota)
        ln.nota_discrepancia = nota if ln.discrepancia else None


def _avisar(prop: CertificacionPropuesta, actor_id: int, *, aceptada=False, rechazo=None, retirada=False) -> None:
    """Avisa según la matriz de correos (grupo Certificación).

    - Enviar / retirar: avisa a la otra parte.
    - Aceptar / rechazar: avisa al dueño de la propuesta tocada.
    """
    from app.services.compliance_rules import email_es_real
    from app.services.notification_dispatch_service import (
        dispatch_notification,
        resolve_recipients,
    )

    company = Company.query.get(prop.company_id)
    obra = Obra.query.get(prop.obra_id) if prop.obra_id else None
    nombre = company.nombre if company else 'Subcontrata'
    obra_txt = (obra.nombre if obra else '') or f'obra {prop.obra_id}'
    periodo = f'{prop.mes:02d}/{prop.anio}'

    if aceptada:
        event_key = 'cert_aceptada'
        asunto = f'Certificación aceptada · {nombre} · {obra_txt} · {periodo}'
        cuerpo = f'La certificación de {obra_txt} ha quedado aceptada y ya no se puede modificar.'
        notify_sub = prop.direccion == DIR_SUB
        notify_office = prop.direccion == DIR_EMP
    elif rechazo:
        event_key = 'cert_rechazada'
        asunto = f'Certificación devuelta · {nombre} · {obra_txt} · {periodo}'
        cuerpo = f'La propuesta de {obra_txt} ha vuelto a borrador.\n\n{rechazo}'
        notify_sub = prop.direccion == DIR_SUB
        notify_office = prop.direccion == DIR_EMP
    elif retirada:
        event_key = 'cert_retirada'
        asunto = f'Certificación retirada · {nombre} · {obra_txt} · {periodo}'
        cuerpo = f'La propuesta enviada de {obra_txt} ha sido cancelada y ya no está pendiente de revisión.'
        notify_office = prop.direccion == DIR_SUB
        notify_sub = prop.direccion == DIR_EMP
    else:
        event_key = 'cert_pendiente'
        asunto = f'Certificación pendiente · {nombre} · {obra_txt} · {periodo}'
        cuerpo = f'Hay una propuesta de horas pendiente de revisar en {obra_txt}.'
        notify_office = prop.direccion == DIR_SUB
        notify_sub = prop.direccion == DIR_EMP

    try:
        users = resolve_recipients(
            event_key,
            obra_id=prop.obra_id,
            company_id=prop.company_id,
            include_office=notify_office,
            include_subcontrata=notify_sub,
        )
        users = [u for u in users if email_es_real(getattr(u, 'email', None))]
        if not users:
            return
        dispatch_notification(
            event_key,
            subject=asunto,
            body=cuerpo,
            users=users,
            batch_key=f'cert:{prop.company_id}:{prop.obra_id}:{prop.anio}:{prop.mes}:{event_key}',
        )
    except Exception:
        pass


def contar_borradores_odoo(prop: CertificacionPropuesta) -> int:
    return sum(1 for ln in prop.lineas if ln.estado_fichaje == 'borrador')


def nombre_archivo_pdf(prop: CertificacionPropuesta) -> str:
    import re
    company = prop.company
    obra = prop.obra
    raw_c = (company.nombre if company else 'certificacion') or 'certificacion'
    raw_o = (obra.nombre if obra else f'obra{prop.obra_id}') or 'obra'
    slug_c = re.sub(r'[^\w\-]+', '_', raw_c.strip(), flags=re.UNICODE)
    slug_c = re.sub(r'_+', '_', slug_c).strip('_')[:40] or 'certificacion'
    slug_o = re.sub(r'[^\w\-]+', '_', raw_o.strip(), flags=re.UNICODE)
    slug_o = re.sub(r'_+', '_', slug_o).strip('_')[:40] or 'obra'
    return f'certificacion_{slug_c}_{slug_o}_{prop.anio}-{prop.mes:02d}.pdf'


def agrupar(prop: CertificacionPropuesta) -> list[dict]:
    obras = {}
    for ln in sorted(prop.lineas, key=lambda x: (x.obra.nombre if x.obra else '', x.fecha, x.user.name if x.user else '')):
        obra = obras.setdefault(ln.obra_id, {
            'obra': ln.obra,
            'fechas': {},
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
        })
        fecha = obra['fechas'].setdefault(ln.fecha, {
            'fecha': ln.fecha,
            'lineas': [],
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
        })
        imp = importe_linea(ln.horas, ln.precio_hora) or Decimal('0.00')
        h = cuantizar(ln.horas) or Decimal('0.00')
        fecha['lineas'].append({'linea': ln, 'importe': imp})
        fecha['horas'] += h
        fecha['importe'] += imp
        obra['horas'] += h
        obra['importe'] += imp
    salida = []
    for obra in obras.values():
        obra['fechas'] = [obra['fechas'][k] for k in sorted(obra['fechas'])]
        salida.append(obra)
    salida.sort(key=lambda o: (o['obra'].nombre if o['obra'] else ''))
    return salida


def totales(prop: CertificacionPropuesta) -> dict:
    horas = Decimal('0.00')
    importe = Decimal('0.00')
    for ln in prop.lineas:
        horas += cuantizar(ln.horas) or Decimal('0.00')
        importe += importe_linea(ln.horas, ln.precio_hora) or Decimal('0.00')
    return {'horas': horas, 'importe': importe, 'filas': len(prop.lineas)}


def totales_grupos(grupos: list[dict]) -> dict:
    horas = Decimal('0.00')
    importe = Decimal('0.00')
    filas = 0
    for obra in grupos:
        horas += obra.get('horas') or Decimal('0.00')
        importe += obra.get('importe') or Decimal('0.00')
        for fecha in obra.get('fechas') or []:
            filas += len(fecha.get('lineas') or [])
    return {
        'horas': cuantizar(horas) or Decimal('0.00'),
        'importe': cuantizar(importe) or Decimal('0.00'),
        'filas': filas,
    }


def _estado_desde_par(rows: list[CertificacionPropuesta], *, vista_subcontrata: bool) -> str:
    if any(r.estado == 'aceptada' for r in rows):
        return 'aceptada'
    propia_dir = DIR_SUB if vista_subcontrata else DIR_EMP
    ajena_dir = _otra(propia_dir)
    by = {r.direccion: r for r in rows}
    if by.get(ajena_dir) and by[ajena_dir].estado == 'enviada':
        return 'recibida'
    if by.get(propia_dir) and by[propia_dir].estado == 'enviada':
        return 'enviada'
    # Solo "rechazada" si nos devolvieron NUESTRA propuesta (acción para nosotros).
    # Si fuimos nosotros quienes rechazamos la ajena, la alerta es de la otra parte.
    propia = by.get(propia_dir)
    if propia and propia.estado == 'borrador' and (propia.comentario_rechazo or '').strip():
        return 'rechazada'
    if propia and propia.estado == 'borrador':
        return 'borrador'
    return 'sin_movimiento'


def mapa_lineas_propuesta(prop: CertificacionPropuesta | None) -> dict:
    """Clave (user_id, obra_id, fecha) → línea, para comparar propuestas."""
    if not prop:
        return {}
    return {(ln.user_id, ln.obra_id, ln.fecha): ln for ln in prop.lineas}


def enriquecer_grupos_ref_app(grupos: list[dict], mapa_propia: dict) -> list[dict]:
    """Añade horas_app / importe_app (suma de tu propuesta) en obra y fecha."""
    for obra in grupos or []:
        h_obra = Decimal('0.00')
        i_obra = Decimal('0.00')
        for fecha in obra.get('fechas') or []:
            h_f = Decimal('0.00')
            i_f = Decimal('0.00')
            for item in fecha.get('lineas') or []:
                ln = item.get('linea')
                if not ln:
                    continue
                ref = mapa_propia.get((ln.user_id, ln.obra_id, ln.fecha))
                if not ref:
                    continue
                h = cuantizar(ref.horas) or Decimal('0.00')
                imp = importe_linea(ref.horas, ref.precio_hora) or Decimal('0.00')
                h_f += h
                i_f += imp
            fecha['horas_app'] = cuantizar(h_f) or Decimal('0.00')
            fecha['importe_app'] = cuantizar(i_f) or Decimal('0.00')
            h_obra += h_f
            i_obra += i_f
        obra['horas_app'] = cuantizar(h_obra) or Decimal('0.00')
        obra['importe_app'] = cuantizar(i_obra) or Decimal('0.00')
    return grupos


def estado_propuesta(
    company_id: int, obra_id: int, anio: int, mes: int, *, vista_subcontrata: bool,
) -> str:
    rows = CertificacionPropuesta.query.filter_by(
        company_id=company_id, obra_id=obra_id, anio=anio, mes=mes,
    ).all()
    return _estado_desde_par(rows, vista_subcontrata=vista_subcontrata)


def _shift_ym(anio: int, mes: int, delta: int) -> tuple[int, int]:
    idx = anio * 12 + (mes - 1) + delta
    return idx // 12, idx % 12 + 1


def panel_meses_obra(
    company_id: int,
    obra_id: int,
    *,
    anio_ref: int,
    mes_ref: int,
    vista_subcontrata: bool,
    meses_atras: int = 17,
    meses_adelante: int = 1,
) -> list[dict]:
    """Meses con propuesta o fichaje de esta empresa+obra (ventana alrededor del mes actual)."""
    propia_dir = DIR_SUB if vista_subcontrata else DIR_EMP
    props = CertificacionPropuesta.query.filter_by(
        company_id=company_id, obra_id=obra_id,
    ).all()
    props_by_ym: dict[tuple[int, int], list[CertificacionPropuesta]] = defaultdict(list)
    for p in props:
        props_by_ym[(p.anio, p.mes)].append(p)

    usuarios = [
        u.id for u in User.query.filter(
            User.company_id == company_id,
            User.is_deleted.is_(False),
        ).all()
    ]
    fichaje_ym: set[tuple[int, int]] = set()
    if usuarios:
        inicio_a, inicio_m = _shift_ym(anio_ref, mes_ref, -meses_atras)
        fin_a, fin_m = _shift_ym(anio_ref, mes_ref, meses_adelante)
        inicio = date(inicio_a, inicio_m, 1)
        fa, fm = _shift_ym(fin_a, fin_m, 1)
        fin = date(fa, fm, 1)
        fechas = (
            db.session.query(RegistroFichaje.fecha)
            .filter(
                RegistroFichaje.user_id.in_(usuarios),
                RegistroFichaje.obra_real_id == obra_id,
                RegistroFichaje.fecha >= inicio,
                RegistroFichaje.fecha < fin,
                RegistroFichaje.check_in.isnot(None),
            )
            .distinct()
            .all()
        )
        for (f,) in fechas:
            if f:
                fichaje_ym.add((f.year, f.month))

    candidatos: set[tuple[int, int]] = set(props_by_ym) | set(fichaje_ym)
    for d in range(-meses_atras, meses_adelante + 1):
        candidatos.add(_shift_ym(anio_ref, mes_ref, d))

    # Solo meses con señal real, más el mes de referencia
    out = []
    for anio, mes in sorted(candidatos, reverse=True):
        rows = props_by_ym.get((anio, mes), [])
        tiene_fichaje = (anio, mes) in fichaje_ym
        if not rows and not tiene_fichaje and (anio, mes) != (anio_ref, mes_ref):
            continue
        propia = next((r for r in rows if r.direccion == propia_dir), None)
        tot = totales(propia) if propia else {'horas': Decimal('0.00'), 'importe': Decimal('0.00'), 'filas': 0}
        aceptada = next((r for r in rows if r.estado == 'aceptada'), None)
        estado = _estado_desde_par(rows, vista_subcontrata=vista_subcontrata)
        out.append({
            'anio': anio,
            'mes': mes,
            'estado': estado,
            'horas': tot['horas'],
            'importe': tot['importe'],
            'aceptada_at': aceptada.aceptada_at if aceptada else None,
            'actual': (anio, mes) == (anio_ref, mes_ref),
            'requiere_accion': estado in ('recibida', 'rechazada'),
        })
    return out


def _nombres_certificacion(company: Company, *, vista_subcontrata: bool) -> tuple[str, str, str, str]:
    """(propia, ajena, subcontrata, oficina) según quién mira."""
    from app.services.contratacion_service import empresa_interna

    sub = ((company.nombre if company else None) or '').strip() or 'Subcontrata'
    ofi_row = empresa_interna()
    ofi = ((ofi_row.nombre if ofi_row else None) or '').strip() or 'Oficina'
    if vista_subcontrata:
        return sub, ofi, sub, ofi
    return ofi, sub, sub, ofi


def _nombre_por_direccion(direccion: str, nombre_sub: str, nombre_ofi: str) -> str:
    return nombre_sub if direccion == DIR_SUB else nombre_ofi


def resumen_actividad(
    propia: CertificacionPropuesta | None,
    ajena: CertificacionPropuesta | None,
    *,
    bloqueado: bool,
    company: Company | None = None,
    vista_subcontrata: bool = False,
) -> list[dict]:
    """Resumen breve con actores claros (no es un historial completo)."""
    propia_n, ajena_n, sub_n, ofi_n = _nombres_certificacion(
        company or (propia.company if propia else None) or (ajena.company if ajena else None),
        vista_subcontrata=vista_subcontrata,
    )
    items: list[dict] = []

    def _add_envio(prop: CertificacionPropuesta | None) -> None:
        if not prop or not prop.enviada_at:
            return
        if prop.estado not in ('enviada', 'aceptada', 'cerrada', 'borrador'):
            return
        if prop.estado == 'borrador' and not (prop.comentario_rechazo or '').strip():
            return
        actor = _nombre_por_direccion(prop.direccion, sub_n, ofi_n)
        destino = ofi_n if prop.direccion == DIR_SUB else sub_n
        items.append({
            'tipo': 'enviada',
            'cuando': prop.enviada_at,
            'actor': actor,
            'destino': destino,
        })

    _add_envio(propia)
    _add_envio(ajena)

    if not bloqueado and propia and (propia.comentario_rechazo or '').strip():
        items.append({
            'tipo': 'rechazo',
            'cuando': None,
            'actor': ajena_n,
            'origen': propia_n,
            'detalle': (propia.comentario_rechazo or '').strip(),
        })

    if bloqueado:
        aceptada = None
        for p in (propia, ajena):
            if p and p.estado == 'aceptada' and p.aceptada_at:
                aceptada = p
                break
        if not aceptada:
            for p in (propia, ajena):
                if p and p.aceptada_at:
                    aceptada = p
                    break
        if aceptada and aceptada.aceptada_at:
            origen = _nombre_por_direccion(aceptada.direccion, sub_n, ofi_n)
            actor = ofi_n if aceptada.direccion == DIR_SUB else sub_n
            items.append({
                'tipo': 'aceptada',
                'cuando': aceptada.aceptada_at,
                'actor': actor,
                'origen': origen,
            })

    dated = [i for i in items if i.get('cuando')]
    undated = [i for i in items if not i.get('cuando')]
    dated.sort(key=lambda i: i['cuando'])
    return dated + undated


def estado_empresa_mes(company_id: int, anio: int, mes: int, *, vista_subcontrata: bool) -> str:
    """Pill agregada: recibida > rechazada > enviada > borrador > aceptada > sin_movimiento."""
    rows = CertificacionPropuesta.query.filter_by(
        company_id=company_id, anio=anio, mes=mes,
    ).all()
    if not rows:
        return 'sin_movimiento'
    por_obra: dict[int, list] = defaultdict(list)
    for r in rows:
        por_obra[r.obra_id].append(r)
    estados = [
        _estado_desde_par(props, vista_subcontrata=vista_subcontrata)
        for props in por_obra.values()
    ]
    for key in ('recibida', 'rechazada', 'enviada', 'borrador', 'aceptada'):
        if key in estados:
            return key
    return 'sin_movimiento'


def resumen_estados_empresa(
    company_id: int, anio: int, mes: int, *, vista_subcontrata: bool = False,
) -> dict:
    rows = CertificacionPropuesta.query.filter_by(
        company_id=company_id, anio=anio, mes=mes,
    ).all()
    por_obra: dict[int, list] = defaultdict(list)
    for r in rows:
        por_obra[r.obra_id].append(r)
    cont = {
        'aceptada': 0, 'recibida': 0, 'enviada': 0, 'rechazada': 0,
        'borrador': 0, 'sin_movimiento': 0,
    }
    for props in por_obra.values():
        est = _estado_desde_par(props, vista_subcontrata=vista_subcontrata)
        cont[est] = cont.get(est, 0) + 1
    n_obras = len(por_obra)
    estado = estado_empresa_mes(company_id, anio, mes, vista_subcontrata=vista_subcontrata)
    return {
        'n_obras': n_obras,
        'contadores': cont,
        'estado': estado,
        'tiene_recibida': cont.get('recibida', 0) > 0,
        'tiene_rechazada': cont.get('rechazada', 0) > 0,
        'requiere_accion': cont.get('recibida', 0) > 0 or cont.get('rechazada', 0) > 0,
    }


def estado_mes(company_id: int, anio: int, mes: int, *, vista_subcontrata: bool) -> str:
    """Compat: estado agregado del mes (portal / listados)."""
    return estado_empresa_mes(company_id, anio, mes, vista_subcontrata=vista_subcontrata)


def lineas_incompletas(prop: CertificacionPropuesta) -> list[int]:
    return [
        int(ln.id)
        for ln in prop.lineas
        if ln.horas is None or ln.precio_hora is None
    ]


def propuestas_entrantes_oficina() -> int:
    return CertificacionPropuesta.query.filter_by(direccion=DIR_SUB, estado='enviada').count()


def _rango_periodo(anio: int, mes: int, desde: date | None = None, hasta: date | None = None) -> tuple[date, date]:
    """Rango de vista. Con desde/hasta manda el filtro (puede cruzar meses). Sin ellos = mes completo."""
    if desde is not None or hasta is not None:
        d0 = desde or hasta
        d1 = hasta or desde
        if d0 > d1:
            d0, d1 = d1, d0
        return d0, d1
    return _mes_rango(anio, mes)


def _interseccion_mes(anio: int, mes: int, desde: date | None, hasta: date | None) -> tuple[date | None, date | None]:
    """Para la ficha de empresa (propuesta mensual): recorta el filtro al mes de la propuesta."""
    if not desde and not hasta:
        return None, None
    ini, fin = _mes_rango(anio, mes)
    d0, d1 = _rango_periodo(anio, mes, desde, hasta)
    lo, hi = max(d0, ini), min(d1, fin)
    if lo > hi:
        return None, None  # sin solape: el filtro no pilla este mes
    return lo, hi


def interseccion_mes(anio: int, mes: int, desde: date | None, hasta: date | None) -> tuple[date | None, date | None]:
    return _interseccion_mes(anio, mes, desde, hasta)


def _meses_en_rango(desde: date, hasta: date) -> list[tuple[int, int]]:
    out = []
    y, m = desde.year, desde.month
    while (y, m) <= (hasta.year, hasta.month):
        out.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


def _volumen_periodo(
    *,
    anio: int,
    mes: int,
    desde: date | None = None,
    hasta: date | None = None,
    obra_ids: set[int] | None = None,
) -> list[dict]:
    """Agrega horas de fichaje por empresa y obra en el periodo (alcance ya aplicado)."""
    inicio, fin = _rango_periodo(anio, mes, desde, hasta)
    q = (
        db.session.query(
            RegistroFichaje.user_id,
            RegistroFichaje.obra_real_id,
            RegistroFichaje.fecha,
            RegistroFichaje.check_in,
            RegistroFichaje.check_out,
            User.company_id,
        )
        .join(User, User.id == RegistroFichaje.user_id)
        .join(Company, Company.id == User.company_id)
        .filter(
            RegistroFichaje.fecha >= inicio,
            RegistroFichaje.fecha <= fin,
            RegistroFichaje.obra_real_id.isnot(None),
            RegistroFichaje.check_in.isnot(None),
            User.is_deleted.is_(False),
            Company.active.is_(True),
            Company.is_internal.is_(False),
        )
    )
    if obra_ids is not None:
        if not obra_ids:
            return []
        q = q.filter(RegistroFichaje.obra_real_id.in_(list(obra_ids)))
    rows = q.all()
    out = []
    for user_id, obra_id, fecha, check_in, check_out, company_id in rows:
        horas = horas_desde_datetimes(check_in, check_out) or Decimal('0.00')
        out.append({
            'user_id': user_id,
            'obra_id': obra_id,
            'fecha': fecha,
            'company_id': company_id,
            'horas': horas,
        })
    return out


def panel_certificacion_oficina(
    user,
    *,
    anio: int,
    mes: int,
    desde: date | None = None,
    hasta: date | None = None,
) -> list[dict]:
    """Listado de subcontratas: resumen por obra/estado (sin total €/h del mes)."""
    from app.services.panel_scope_service import certificacion_obra_ids

    allowed = certificacion_obra_ids(user)
    if allowed is not None and not allowed:
        return []

    filas = _volumen_periodo(anio=anio, mes=mes, desde=desde, hasta=hasta, obra_ids=allowed)
    company_ids: set[int] = {f['company_id'] for f in filas}

    if desde and hasta:
        periodos = _meses_en_rango(desde, hasta)
    else:
        periodos = [(anio, mes)]
    pend = (
        CertificacionPropuesta.query
        .filter(
            CertificacionPropuesta.direccion == DIR_SUB,
            CertificacionPropuesta.estado == 'enviada',
            db.or_(
                *[
                    db.and_(
                        CertificacionPropuesta.anio == ay,
                        CertificacionPropuesta.mes == mo,
                    )
                    for ay, mo in periodos
                ]
            ),
        )
        .all()
    ) if periodos else []
    for prop in pend:
        if allowed is None or prop.obra_id in allowed:
            company_ids.add(prop.company_id)

    # Propuestas del mes ancla en alcance
    props_mes = CertificacionPropuesta.query.filter_by(anio=anio, mes=mes).all()
    for prop in props_mes:
        if allowed is None or prop.obra_id in allowed:
            company_ids.add(prop.company_id)

    if not company_ids:
        return []

    companies = {
        c.id: c for c in Company.query.filter(Company.id.in_(list(company_ids))).all()
    }
    out = []
    for cid in company_ids:
        company = companies.get(cid)
        if not company or company.is_internal or not company.active:
            continue
        oids = obras_ids_certificacion(
            cid, anio, mes, obra_ids=None if allowed is None else allowed,
        )
        if not oids:
            continue
        props = CertificacionPropuesta.query.filter(
            CertificacionPropuesta.company_id == cid,
            CertificacionPropuesta.anio == anio,
            CertificacionPropuesta.mes == mes,
            CertificacionPropuesta.obra_id.in_(oids),
        ).all()
        por_obra: dict[int, list] = defaultdict(list)
        for p in props:
            por_obra[p.obra_id].append(p)
        cont = {
            'aceptada': 0, 'recibida': 0, 'enviada': 0, 'rechazada': 0,
            'borrador': 0, 'sin_movimiento': 0,
        }
        for oid in oids:
            est = _estado_desde_par(por_obra.get(oid, []), vista_subcontrata=False)
            cont[est] = cont.get(est, 0) + 1
        estado = 'sin_movimiento'
        for key in ('recibida', 'rechazada', 'enviada', 'borrador', 'aceptada'):
            if cont.get(key, 0):
                estado = key
                break
        out.append({
            'company': company,
            'estado': estado,
            'requiere_accion': cont.get('recibida', 0) > 0 or cont.get('rechazada', 0) > 0,
            'n_obras': len(oids),
            'n_recibida': cont.get('recibida', 0),
            'n_rechazada': cont.get('rechazada', 0),
            'n_aceptada': cont.get('aceptada', 0),
            'n_enviada': cont.get('enviada', 0),
            'n_borrador': cont.get('borrador', 0),
            'tiene_recibida': cont.get('recibida', 0) > 0,
            'tiene_rechazada': cont.get('rechazada', 0) > 0,
        })
    out.sort(key=lambda row: (
        0 if row['estado'] == 'recibida' else (1 if row['estado'] == 'rechazada' else 2),
        -(row['n_obras'] or 0),
        (row['company'].nombre or '').lower(),
    ))
    return out


def panel_certificacion_empresa_obras(
    user,
    company_id: int,
    *,
    anio: int,
    mes: int,
    desde: date | None = None,
    hasta: date | None = None,
) -> list[dict]:
    """Hub empresa: obras del mes con estado y horas."""
    from app.services.panel_scope_service import certificacion_obra_ids

    allowed = certificacion_obra_ids(user)
    if allowed is not None and not allowed:
        return []

    company = Company.query.get(company_id)
    if not company:
        return []

    oids = obras_ids_certificacion(
        company_id, anio, mes,
        obra_ids=None if allowed is None else allowed,
    )
    if not oids:
        return []

    filas = _volumen_periodo(
        anio=anio, mes=mes, desde=desde, hasta=hasta,
        obra_ids=set(oids),
    )
    horas_obra: dict[int, Decimal] = defaultdict(lambda: Decimal('0.00'))
    for f in filas:
        if f['company_id'] == company_id:
            horas_obra[f['obra_id']] += f['horas']

    obras = {o.id: o for o in Obra.query.filter(Obra.id.in_(oids)).all()}
    out = []
    for oid in oids:
        obra = obras.get(oid)
        if not obra:
            continue
        sincronizar(company, anio, mes, oid)
        estado = estado_propuesta(company_id, oid, anio, mes, vista_subcontrata=False)
        horas = cuantizar(horas_obra.get(oid, Decimal('0.00'))) or Decimal('0.00')
        out.append({
            'obra': obra,
            'estado': estado,
            'horas': horas,
            'requiere_accion': estado in ('recibida', 'rechazada'),
        })
    out.sort(key=lambda row: (
        0 if row['estado'] == 'recibida' else (1 if row['estado'] == 'rechazada' else 2),
        -(row['horas'] or 0),
        (row['obra'].nombre or '').lower(),
    ))
    return out


def panel_certificacion_subcontrata_obras(
    company: Company,
    *,
    anio: int,
    mes: int,
) -> list[dict]:
    """Lista de obras del mes para el portal subcontrata."""
    oids = obras_ids_certificacion(company.id, anio, mes)
    if not oids:
        return []
    filas = _volumen_periodo(anio=anio, mes=mes, obra_ids=set(oids))
    horas_obra: dict[int, Decimal] = defaultdict(lambda: Decimal('0.00'))
    for f in filas:
        if f['company_id'] == company.id:
            horas_obra[f['obra_id']] += f['horas']
    obras = {o.id: o for o in Obra.query.filter(Obra.id.in_(oids)).all()}
    out = []
    for oid in oids:
        obra = obras.get(oid)
        if not obra:
            continue
        sincronizar(company, anio, mes, oid)
        estado = estado_propuesta(company.id, oid, anio, mes, vista_subcontrata=True)
        out.append({
            'obra': obra,
            'estado': estado,
            'horas': cuantizar(horas_obra.get(oid, Decimal('0.00'))) or Decimal('0.00'),
            'requiere_accion': estado in ('recibida', 'rechazada'),
        })
    out.sort(key=lambda row: (
        0 if row['estado'] == 'recibida' else (1 if row['estado'] == 'rechazada' else 2),
        -(row['horas'] or 0),
        (row['obra'].nombre or '').lower(),
    ))
    return out


def panel_certificacion_obras(
    user,
    *,
    anio: int,
    mes: int,
    desde: date | None = None,
    hasta: date | None = None,
) -> list[dict]:
    """Listado de obras del alcance con volumen, para vista por obra."""
    from app.services.panel_scope_service import certificacion_obra_ids

    allowed = certificacion_obra_ids(user)
    if allowed is not None and not allowed:
        return []

    filas = _volumen_periodo(anio=anio, mes=mes, desde=desde, hasta=hasta, obra_ids=allowed)
    por_obra: dict[int, dict] = {}
    for f in filas:
        oid = f['obra_id']
        bucket = por_obra.setdefault(oid, {
            'horas': Decimal('0.00'),
            'companies': set(),
        })
        bucket['horas'] += f['horas']
        bucket['companies'].add(f['company_id'])

    if not por_obra:
        return []

    obras = {o.id: o for o in Obra.query.filter(Obra.id.in_(list(por_obra))).all()}
    out = []
    for oid, data in por_obra.items():
        obra = obras.get(oid)
        if not obra:
            continue
        horas = cuantizar(data['horas']) or Decimal('0.00')
        out.append({
            'obra': obra,
            'horas': horas,
            'n_empresas': len(data['companies']),
            'importe': None,  # se calcula en detalle (precios por empresa)
        })
    out.sort(key=lambda row: (-(row['horas'] or 0), (row['obra'].nombre or '').lower()))
    return out


def detalle_certificacion_obra(
    user,
    obra_id: int,
    *,
    anio: int,
    mes: int,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict | None:
    """Detalle obra: agrupaciones por empresa y por fecha, con estado de propuesta."""
    from app.services.panel_scope_service import certificacion_obra_ids

    allowed = certificacion_obra_ids(user)
    if allowed is not None and obra_id not in allowed:
        return None
    obra = Obra.query.get(obra_id)
    if not obra:
        return None

    filas = _volumen_periodo(
        anio=anio, mes=mes, desde=desde, hasta=hasta,
        obra_ids={obra_id} if allowed is None else ({obra_id} & allowed),
    )
    # Incluir empresas con propuesta aunque el filtro de fechas no pille fichaje
    props_obra = CertificacionPropuesta.query.filter_by(obra_id=obra_id, anio=anio, mes=mes).all()
    company_ids = {f['company_id'] for f in filas} | {p.company_id for p in props_obra}
    user_ids = {f['user_id'] for f in filas}
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    companies = {
        c.id: c for c in Company.query.filter(Company.id.in_(list(company_ids))).all()
    } if company_ids else {}

    dias: dict[date, dict] = {}
    por_empresa: dict[int, dict] = {}
    total_horas = Decimal('0.00')
    total_importe = Decimal('0.00')
    for f in filas:
        company = companies.get(f['company_id'])
        persona = users.get(f['user_id'])
        if not company or not persona:
            continue
        precio = precio_empresa(company)
        importe = cuantizar(f['horas'] * precio) or Decimal('0.00')
        total_horas += f['horas']
        total_importe += importe
        dia = dias.setdefault(f['fecha'], {
            'fecha': f['fecha'],
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
            'empresas': {},
        })
        dia['horas'] += f['horas']
        dia['importe'] += importe
        emp_dia = dia['empresas'].setdefault(company.id, {
            'company': company,
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
            'precio': precio,
            'personas': [],
        })
        emp_dia['horas'] += f['horas']
        emp_dia['importe'] += importe
        emp_dia['personas'].append({
            'user': persona,
            'horas': cuantizar(f['horas']) or Decimal('0.00'),
            'importe': importe,
            'precio': precio,
            'fecha': f['fecha'],
        })

        emp = por_empresa.setdefault(company.id, {
            'company': company,
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
            'precio': precio,
            'fechas': {},
        })
        emp['horas'] += f['horas']
        emp['importe'] += importe
        fecha_b = emp['fechas'].setdefault(f['fecha'], {
            'fecha': f['fecha'],
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
            'personas': [],
        })
        fecha_b['horas'] += f['horas']
        fecha_b['importe'] += importe
        fecha_b['personas'].append({
            'user': persona,
            'horas': cuantizar(f['horas']) or Decimal('0.00'),
            'importe': importe,
            'precio': precio,
        })

    for cid in company_ids:
        company = companies.get(cid)
        if not company:
            continue
        sincronizar(company, anio, mes, obra_id)
        if cid not in por_empresa:
            por_empresa[cid] = {
                'company': company,
                'horas': Decimal('0.00'),
                'importe': Decimal('0.00'),
                'precio': precio_empresa(company),
                'fechas': {},
            }

    fechas = []
    for fecha in sorted(dias.keys(), reverse=True):
        d = dias[fecha]
        empresas = sorted(
            d['empresas'].values(),
            key=lambda e: (-(e['horas'] or 0), (e['company'].nombre or '').lower()),
        )
        for emp in empresas:
            emp['horas'] = cuantizar(emp['horas']) or Decimal('0.00')
            emp['importe'] = cuantizar(emp['importe']) or Decimal('0.00')
            emp['personas'].sort(key=lambda p: (-(p['horas'] or 0), (p['user'].name or '').lower()))
            emp['estado'] = estado_propuesta(
                emp['company'].id, obra_id, anio, mes, vista_subcontrata=False,
            )
        fechas.append({
            'fecha': fecha,
            'horas': cuantizar(d['horas']) or Decimal('0.00'),
            'importe': cuantizar(d['importe']) or Decimal('0.00'),
            'empresas': empresas,
        })

    empresas_out = []
    for cid, emp in por_empresa.items():
        emp['horas'] = cuantizar(emp['horas']) or Decimal('0.00')
        emp['importe'] = cuantizar(emp['importe']) or Decimal('0.00')
        emp['estado'] = estado_propuesta(cid, obra_id, anio, mes, vista_subcontrata=False)
        fechas_emp = []
        for fecha in sorted(emp['fechas'].keys(), reverse=True):
            fb = emp['fechas'][fecha]
            fb['horas'] = cuantizar(fb['horas']) or Decimal('0.00')
            fb['importe'] = cuantizar(fb['importe']) or Decimal('0.00')
            fb['personas'].sort(key=lambda p: (-(p['horas'] or 0), (p['user'].name or '').lower()))
            fechas_emp.append(fb)
        emp['fechas'] = fechas_emp
        empresas_out.append(emp)
    empresas_out.sort(key=lambda e: (
        0 if e['estado'] == 'recibida' else (1 if e['estado'] == 'rechazada' else 2),
        -(e['horas'] or 0),
        (e['company'].nombre or '').lower(),
    ))

    return {
        'obra': obra,
        'fechas': fechas,
        'empresas': empresas_out,
        'horas': cuantizar(total_horas) or Decimal('0.00'),
        'importe': cuantizar(total_importe) or Decimal('0.00'),
    }


def agrupar_por_fecha(prop: CertificacionPropuesta) -> list[dict]:
    """fecha → personas (propuesta ya acotada a una obra)."""
    fechas: dict = {}
    for ln in sorted(prop.lineas, key=lambda x: (x.fecha, x.user.name if x.user else '')):
        fecha = fechas.setdefault(ln.fecha, {
            'fecha': ln.fecha,
            'lineas': [],
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
        })
        imp = importe_linea(ln.horas, ln.precio_hora) or Decimal('0.00')
        h = cuantizar(ln.horas) or Decimal('0.00')
        fecha['lineas'].append({'linea': ln, 'importe': imp})
        fecha['horas'] += h
        fecha['importe'] += imp
    return [fechas[k] for k in sorted(fechas)]


def agrupar_por_persona(prop: CertificacionPropuesta) -> list[dict]:
    """persona → fechas (portal subcontrata)."""
    personas: dict = {}
    for ln in sorted(prop.lineas, key=lambda x: (x.user.name if x.user else '', x.fecha)):
        uid = ln.user_id
        bucket = personas.setdefault(uid, {
            'user': ln.user,
            'fechas': [],
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
        })
        imp = importe_linea(ln.horas, ln.precio_hora) or Decimal('0.00')
        h = cuantizar(ln.horas) or Decimal('0.00')
        bucket['fechas'].append({'fecha': ln.fecha, 'linea': ln, 'importe': imp, 'horas': h})
        bucket['horas'] += h
        bucket['importe'] += imp
    out = list(personas.values())
    for p in out:
        p['horas'] = cuantizar(p['horas']) or Decimal('0.00')
        p['importe'] = cuantizar(p['importe']) or Decimal('0.00')
        p['fechas'].sort(key=lambda x: x['fecha'])
    out.sort(key=lambda p: (p['user'].name or '').lower() if p['user'] else '')
    return out


def aplicar_precio_plataforma_herederos(*, anio: int, mes: int, precio: Decimal) -> int:
    """Aplica el precio plataforma a borradores de empresas sin precio propio."""
    herederas = Company.query.filter(
        Company.active.is_(True),
        Company.is_internal.is_(False),
        Company.precio_hora.is_(None),
    ).all()
    n = 0
    for company in herederas:
        n += aplicar_precio_borrador(company, anio, mes, precio)
    return n


def filtrar_grupos_por_obras(grupos: list[dict], obra_ids: set[int] | None) -> list[dict]:
    if obra_ids is None:
        return grupos
    return [g for g in grupos if g.get('obra') and g['obra'].id in obra_ids]


def filtrar_grupos_por_rango(grupos: list[dict], desde: date | None, hasta: date | None) -> list[dict]:
    if not desde and not hasta:
        return grupos
    d0, d1 = desde, hasta
    if d0 and d1 and d0 > d1:
        d0, d1 = d1, d0
    out = []
    for obra in grupos:
        fechas = []
        horas = Decimal('0.00')
        importe = Decimal('0.00')
        for fecha in obra.get('fechas') or []:
            f = fecha.get('fecha')
            if d0 and f < d0:
                continue
            if d1 and f > d1:
                continue
            fechas.append(fecha)
            horas += fecha.get('horas') or Decimal('0.00')
            importe += fecha.get('importe') or Decimal('0.00')
        if not fechas:
            continue
        out.append({
            **obra,
            'fechas': fechas,
            'horas': cuantizar(horas) or Decimal('0.00'),
            'importe': cuantizar(importe) or Decimal('0.00'),
        })
    return out


def parse_hora(raw: str | None) -> time | None:
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%H:%M').time()
    except ValueError:
        return None


CERT_PDF_HEADER_MM = 14
CERT_PDF_PAGE_MM = 297


def _pdfkit_options_cert(*, header_html_path: str | None = None) -> dict:
    opts = {
        'page-size': 'A4',
        'encoding': 'UTF-8',
        # Margen superior nativo: wkhtmltopdf lo respeta en TODAS las hojas.
        'margin-top': f'{CERT_PDF_HEADER_MM}mm',
        'margin-bottom': '0',
        'margin-left': '0',
        'margin-right': '0',
        'quiet': '',
        'enable-local-file-access': None,
        'disable-smart-shrinking': None,
        'print-media-type': None,
        'no-outline': None,
    }
    if header_html_path:
        opts['header-html'] = header_html_path
        opts['header-spacing'] = '0'
        opts['javascript-delay'] = '300'
    return opts


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    try:
        from io import BytesIO
        from pypdf import PdfReader
        return max(1, len(PdfReader(BytesIO(pdf_bytes)).pages))
    except Exception:
        return 1


def _estimate_cert_pages(grupos: list[dict]) -> int:
    filas = 0
    for obra in grupos:
        for fecha in obra.get('fechas') or []:
            filas += len(fecha.get('lineas') or [])
    return max(1, 1 + (max(filas, 1) + 27) // 28)


def _build_cert_pdf_context(
    prop: CertificacionPropuesta,
    *,
    schema_name: str | None = None,
    overlay_page_count: int = 0,
    include_inline_banner: bool = True,
) -> dict:
    from app.services.i18n_service import translate
    from app.services.tenant_branding_service import (
        get_brand_stripe_color,
        get_organization_display_name,
        header_data_uri,
        logo_stripe_data_uri,
        mark_data_uri,
    )
    company = prop.company
    grupos = agrupar(prop)
    tot = totales(prop)
    empresa = company.nombre if company else translate('Certificación')
    mes_txt = f'{prop.mes:02d}/{prop.anio}'
    sentido = (
        translate('Subcontrata → empresa')
        if prop.direccion == DIR_SUB
        else translate('Empresa → subcontrata')
    )
    obras = []
    for obra in grupos:
        filas = []
        for fecha in obra['fechas']:
            fecha_txt = fecha['fecha'].strftime('%d/%m/%Y')
            for idx, item in enumerate(fecha['lineas']):
                ln = item['linea']
                persona = ''
                if ln.user:
                    persona = f'{ln.user.name or ""} {ln.user.lastname or ""}'.strip()
                filas.append({
                    'fecha': fecha_txt if idx == 0 else '',
                    'persona': persona,
                    'inicio': ln.hora_inicio.strftime('%H:%M') if ln.hora_inicio else '—',
                    'fin': ln.hora_fin.strftime('%H:%M') if ln.hora_fin else '—',
                    'horas': ln.horas if ln.horas is not None else '—',
                    'precio': ln.precio_hora if ln.precio_hora is not None else '—',
                    'importe': item['importe'] if item.get('importe') is not None else '—',
                })
        obras.append({
            'nombre': obra['obra'].nombre if obra['obra'] else translate('Obra'),
            'horas': obra['horas'],
            'importe': obra['importe'],
            'filas': filas,
        })
    stripe_label = f'{empresa} · {mes_txt}'
    # Dejar sitio al periodo completo (p. ej. 09/2026); el motor PDF corta el final.
    max_emp = 36
    if len(stripe_label) > 44:
        stripe_label = f'{(empresa[:max_emp]).rstrip()} · {mes_txt}'
    if len(stripe_label) > 48:
        stripe_label = mes_txt
    # Con margin-top, el área de contenido por hoja es más baja.
    page_height_mm = CERT_PDF_PAGE_MM - CERT_PDF_HEADER_MM
    return {
        'doc_title': f'{translate("Certificación")} · {empresa} · {mes_txt}',
        'empresa': empresa,
        'mes_txt': mes_txt,
        'sentido': sentido,
        'estado_txt': (prop.estado or '').capitalize(),
        'total_horas': tot['horas'],
        'total_importe': tot['importe'],
        'obras': obras,
        'organizacion': get_organization_display_name(),
        'logo_data_uri': logo_stripe_data_uri(schema_name),
        'header_data_uri': header_data_uri(schema_name),
        'mark_data_uri': mark_data_uri(schema_name, opacity=0.14),
        'stripe_color': get_brand_stripe_color(),
        'stripe_label': stripe_label,
        'overlay_page_count': max(0, int(overlay_page_count)),
        'page_height_mm': page_height_mm,
        'include_inline_banner': bool(include_inline_banner),
    }


def html_propuesta(
    prop: CertificacionPropuesta,
    *,
    schema_name: str | None = None,
    overlay_page_count: int | None = None,
    include_inline_banner: bool = True,
) -> str:
    from flask import current_app, g
    from app.services.i18n_service import translate

    if schema_name is None:
        tenant = getattr(g, 'current_tenant', None)
        schema_name = getattr(tenant, 'schema_name', None) if tenant else None
    if overlay_page_count is None:
        overlay_page_count = _estimate_cert_pages(agrupar(prop))
    ctx = _build_cert_pdf_context(
        prop,
        schema_name=schema_name,
        overlay_page_count=overlay_page_count,
        include_inline_banner=include_inline_banner,
    )
    template = current_app.jinja_env.get_template('compliance/certificacion_pdf.html')
    return template.render(_=translate, **ctx)


def _render_cert_header_html(prop: CertificacionPropuesta, *, schema_name: str | None) -> str:
    from flask import current_app
    from app.services.i18n_service import translate
    ctx = _build_cert_pdf_context(
        prop, schema_name=schema_name, overlay_page_count=0, include_inline_banner=False,
    )
    template = current_app.jinja_env.get_template('compliance/certificacion_pdf_header.html')
    return template.render(_=translate, **ctx)


def pdf_propuesta(prop: CertificacionPropuesta, *, schema_name: str | None = None) -> bytes | None:
    import os
    import tempfile

    header_path = None
    try:
        import pdfkit
        from flask import current_app, g

        if schema_name is None:
            tenant = getattr(g, 'current_tenant', None)
            schema_name = getattr(tenant, 'schema_name', None) if tenant else None

        config = None
        wkhtml = current_app.config.get('WKHTMLTOPDF_CMD') or current_app.config.get('PDFKIT_WKHTMLTOPDF')
        if wkhtml:
            config = pdfkit.configuration(wkhtmltopdf=wkhtml)

        header_html = _render_cert_header_html(prop, schema_name=schema_name)
        fd, header_path = tempfile.mkstemp(suffix='.html', prefix='cert_hdr_')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(header_html)

        opts = _pdfkit_options_cert(header_html_path=header_path)

        # Cuerpo sin banner inline: la cabecera la pinta wkhtmltopdf en cada hoja.
        probe_html = html_propuesta(
            prop,
            schema_name=schema_name,
            overlay_page_count=0,
            include_inline_banner=False,
        )
        page_count = _count_pdf_pages(
            pdfkit.from_string(probe_html, False, options=opts, configuration=config)
        )
        final_html = html_propuesta(
            prop,
            schema_name=schema_name,
            overlay_page_count=page_count,
            include_inline_banner=False,
        )
        return pdfkit.from_string(final_html, False, options=opts, configuration=config)
    except Exception:
        return None
    finally:
        if header_path:
            try:
                os.unlink(header_path)
            except OSError:
                pass
