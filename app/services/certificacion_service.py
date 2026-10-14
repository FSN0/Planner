"""Certificación de horario: dos propuestas por mes y cierre al aceptar."""
from __future__ import annotations

import re
import threading
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal

from app import db
from app.models import (
    CertificacionChatMensaje,
    CertificacionLinea,
    CertificacionPropuesta,
    CertificacionRonda,
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

CONFIG_PRECIO = 'precio_hora_defecto'  # legacy; ya no es origen de tarifa
DIR_SUB = 'subcontrata_a_empresa'
DIR_EMP = 'empresa_a_subcontrata'


def _ext_odoo_id(entity) -> int | None:
    if entity is None:
        return None
    raw = (getattr(entity, 'external_ids', None) or {}).get('odoo')
    if raw in (None, '', False):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _user_contract_odoo_ids(user: User | None) -> set[int]:
    """IDs Odoo del operario que pueden aparecer en líneas de contrato de asistencia.

    Incluye el vínculo principal (partner o employee), aliases y claves partner
    explícitas en external_ids.
    """
    if user is None:
        return set()
    out: set[int] = set()
    ext = getattr(user, 'external_ids', None) or {}
    for key in ('odoo', 'odoo_partner', 'partner'):
        raw = ext.get(key)
        if raw in (None, '', False):
            continue
        try:
            out.add(int(raw))
        except (TypeError, ValueError):
            pass
    try:
        from app.services.personal_conciliation_service import odoo_ids_for_user
        for raw in odoo_ids_for_user(user):
            try:
                out.add(int(raw))
            except (TypeError, ValueError):
                pass
    except Exception:
        pass
    return out


def _user_partner_odoo_id(user: User | None) -> int | None:
    """partner_id Odoo del operario (compat); preferir _user_contract_odoo_ids."""
    ids = _user_contract_odoo_ids(user)
    if not ids:
        return None
    from app.services.odoo_employee_metadata import is_odoo_partner_link
    primary = _ext_odoo_id(user)
    if primary and is_odoo_partner_link(user):
        return primary
    ext = getattr(user, 'external_ids', None) or {}
    for key in ('odoo_partner', 'partner'):
        raw = ext.get(key)
        if raw in (None, '', False):
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return next(iter(ids), None)


def precio_plataforma() -> Decimal:
    """Legacy: ya no es origen de tarifa. Se mantiene por compatibilidad."""
    raw = get_tenant_config(CONFIG_PRECIO, default='0')
    return cuantizar(raw) or Decimal('0.00')


def guardar_precio_plataforma(valor) -> None:
    set_tenant_config(CONFIG_PRECIO, str(cuantizar(valor) or Decimal('0.00')))


def _parse_fecha_contrato(raw) -> date | None:
    if raw in (None, False, ''):
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def contrato_asistencia(
    company: Company,
    obra: Obra | None,
    *,
    fecha: date | None = None,
    cache: dict | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict | None:
    """Lee el contrato de asistencia Odoo (empresa+obra) vigente en fecha o rango."""
    if company is None or obra is None:
        return None
    partner_id = _ext_odoo_id(company)
    project_id = _ext_odoo_id(obra)
    if not partner_id or not project_id:
        return None
    store = cache if cache is not None else {}
    if date_from is not None and date_to is not None:
        key = (partner_id, project_id, f'{date_from.isoformat()}:{date_to.isoformat()}')
        kwargs = {
            'partner_id': partner_id,
            'project_id': project_id,
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
        }
    else:
        on_date = (fecha or date.today()).isoformat()
        key = (partner_id, project_id, on_date)
        kwargs = {
            'partner_id': partner_id,
            'project_id': project_id,
            'on_date': on_date,
        }
    if key in store:
        return store[key]
    try:
        from app.sync.dispatcher import get_sync_adapter
        adapter = get_sync_adapter()
        getter = getattr(adapter, 'get_attendance_contract_rates', None)
        payload = getter(**kwargs) if callable(getter) else None
    except Exception:
        payload = None
    store[key] = payload
    return payload


def contrato_asistencia_mes(
    company: Company,
    obra: Obra | None,
    anio: int,
    mes: int,
    *,
    cache: dict | None = None,
) -> dict | None:
    """Contrato de asistencia que solapa el mes de certificación (si existe)."""
    inicio, fin = _mes_rango(anio, mes)
    return contrato_asistencia(
        company, obra, date_from=inicio, date_to=fin, cache=cache,
    )


def rango_vigencia_contrato(contrato: dict | None) -> tuple[date | None, date | None]:
    if not contrato:
        return None, None
    return (
        _parse_fecha_contrato(contrato.get('date_start')),
        _parse_fecha_contrato(contrato.get('date_end')),
    )


def lineas_fuera_vigencia_contrato(
    prop: CertificacionPropuesta | None,
    contrato: dict | None,
) -> list:
    """Filas con horas cuya fecha cae fuera de date_start..date_end del contrato."""
    if not prop or not contrato:
        return []
    inicio, fin = rango_vigencia_contrato(contrato)
    if inicio is None and fin is None:
        return []
    fuera = []
    for ln in prop.lineas or []:
        if ln.fecha is None:
            continue
        if ln.horas is None and ln.hora_inicio is None and ln.hora_fin is None:
            continue
        if inicio is not None and ln.fecha < inicio:
            fuera.append(ln)
            continue
        if fin is not None and ln.fecha > fin:
            fuera.append(ln)
    return fuera


def precio_contrato(
    company: Company,
    obra: Obra | None = None,
    *,
    user: User | None = None,
    fecha: date | None = None,
    cache: dict | None = None,
) -> Decimal | None:
    """€/h del contrato: línea del operario > coste hora base. None si no hay contrato."""
    payload = contrato_asistencia(company, obra, fecha=fecha, cache=cache)
    if not payload:
        return None
    lines = payload.get('lines') or {}
    for op_id in _user_contract_odoo_ids(user):
        if op_id in lines:
            rate = cuantizar(lines[op_id])
            if rate is not None:
                return rate
    base = payload.get('hourly_rate')
    if base not in (None, False):
        rate = cuantizar(base)
        # hourly_rate 0 en Odoo suele significar «solo hay tarifa por línea».
        if rate is not None and rate > 0:
            return rate
    # Sin operario (cabecera) o base vacía: primera tarifa > 0 de las líneas.
    for raw in lines.values():
        rate = cuantizar(raw)
        if rate is not None and rate > 0:
            return rate
    return None


def precio_empresa(company: Company) -> Decimal:
    """Override manual de empresa, o 0 si no hay (el contrato manda por obra)."""
    if company.precio_hora is not None:
        return cuantizar(company.precio_hora) or Decimal('0.00')
    return Decimal('0.00')


def precio_obra(obra: Obra | None) -> Decimal | None:
    """€/h propio de la obra (override manual), o None si usa contrato/empresa."""
    if obra is None or obra.precio_hora is None:
        return None
    return cuantizar(obra.precio_hora) or Decimal('0.00')


def precio_para(
    company: Company,
    obra: Obra | None = None,
    *,
    user: User | None = None,
    fecha: date | None = None,
    cache: dict | None = None,
) -> Decimal:
    """Tarifa efectiva: override obra > override empresa > contrato (persona > base) > 0."""
    propio = precio_obra(obra)
    if propio is not None:
        return propio
    if company is not None and company.precio_hora is not None:
        return cuantizar(company.precio_hora) or Decimal('0.00')
    contrato = precio_contrato(
        company, obra, user=user, fecha=fecha, cache=cache,
    )
    if contrato is not None:
        return contrato
    return Decimal('0.00')


def guardar_precio_empresa(company: Company, valor) -> Decimal:
    """Override manual de empresa. Vacío = vuelve al contrato de asistencia."""
    raw = (str(valor) if valor is not None else '').strip()
    if not raw:
        company.precio_hora = None
        return Decimal('0.00')
    precio = cuantizar(valor)
    if precio is None:
        raise ValueError('El precio hora no es válido.')
    company.precio_hora = precio
    return precio


def guardar_precio_obra(obra: Obra, valor) -> Decimal:
    """Override manual de obra. Vacío = vuelve a empresa/contrato."""
    raw = (str(valor) if valor is not None else '').strip()
    if not raw:
        obra.precio_hora = None
        return Decimal('0.00')
    precio = cuantizar(valor)
    if precio is None:
        raise ValueError('El precio hora no es válido.')
    obra.precio_hora = precio
    return precio


def aplicar_precio_borrador(company: Company, anio: int, mes: int, precio: Decimal) -> int:
    """Actualiza €/h de borradores del mes; omite obras con tarifa propia."""
    props = CertificacionPropuesta.query.filter_by(
        company_id=company.id, anio=anio, mes=mes, estado='borrador',
    ).all()
    obras = {
        o.id: o for o in Obra.query.filter(
            Obra.id.in_({p.obra_id for p in props if p.obra_id} or {-1}),
        ).all()
    }
    n = 0
    for prop in props:
        if precio_obra(obras.get(prop.obra_id)) is not None:
            continue
        for ln in prop.lineas:
            ln.precio_hora = precio
            n += 1
    return n


def aplicar_precio_obra_borrador(obra_id: int, anio: int, mes: int, precio: Decimal) -> int:
    """Actualiza €/h de todas las líneas en borrador de esta obra/mes."""
    props = CertificacionPropuesta.query.filter_by(
        obra_id=obra_id, anio=anio, mes=mes, estado='borrador',
    ).all()
    n = 0
    for prop in props:
        for ln in prop.lineas:
            ln.precio_hora = precio
            n += 1
    return n


def reaplicar_precios_obra_borrador(obra: Obra, anio: int, mes: int) -> int:
    """Tras quitar el override de obra, reaplica contrato/empresa a cada línea."""
    props = CertificacionPropuesta.query.filter_by(
        obra_id=obra.id, anio=anio, mes=mes, estado='borrador',
    ).all()
    companies = {
        c.id: c for c in Company.query.filter(
            Company.id.in_({p.company_id for p in props} or {-1}),
        ).all()
    }
    user_ids = {ln.user_id for p in props for ln in p.lineas}
    users = {
        u.id: u for u in User.query.filter(User.id.in_(user_ids or {-1})).all()
    }
    cache: dict = {}
    n = 0
    for prop in props:
        company = companies.get(prop.company_id)
        if not company:
            continue
        for ln in prop.lineas:
            ln.precio_hora = precio_para(
                company, obra,
                user=users.get(ln.user_id),
                fecha=ln.fecha,
                cache=cache,
            )
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

    # check_in/out en BD son naive UTC; la certificación muestra reloj local del tenant.
    from app.utils.timezone_utils import utc_to_local

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
        inicio_local = utc_to_local(inicio_h) if inicio_h else None
        fin_local = utc_to_local(fin_h) if fin_h else None
        filas.append({
            'user_id': user_id,
            'obra_id': obra_id,
            'fecha': fecha,
            'hora_inicio': (
                inicio_local.time().replace(second=0, microsecond=0) if inicio_local else None
            ),
            'hora_fin': (
                fin_local.time().replace(second=0, microsecond=0)
                if fin_local and alguna else None
            ),
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


def _propuesta_tiene_senal(prop: CertificacionPropuesta | None) -> bool:
    """True si hay envío/cierre o al menos una fila con horas (no borrador vacío)."""
    if not prop:
        return False
    if prop.estado in ('enviada', 'aceptada', 'cerrada'):
        return True
    for ln in prop.lineas or []:
        if ln.origen_horas and str(ln.origen_horas).startswith('manual'):
            return True
        if ln.hora_inicio is not None or ln.hora_fin is not None:
            return True
        h = cuantizar(ln.horas)
        if h is not None and h > 0:
            return True
    return False


def _obra_mes_certificable(
    company: Company | None,
    obra: Obra | None,
    props: list[CertificacionPropuesta],
    *,
    anio: int,
    mes: int,
    tiene_fichaje: bool,
    cache: dict | None = None,
) -> bool:
    """Hay que listar la obra ese mes: fichaje, propuesta con contenido, o contrato."""
    if tiene_fichaje:
        return True
    if any(_propuesta_tiene_senal(p) for p in props):
        return True
    if not company or not obra:
        return False
    try:
        fecha_tarifa = date(anio, mes, 15)
    except ValueError:
        fecha_tarifa = date(anio, mes, 1)
    return bool(contrato_asistencia(company, obra, fecha=fecha_tarifa, cache=cache))


def obras_ids_certificacion(
    company_id: int,
    anio: int,
    mes: int,
    *,
    obra_ids: set[int] | None = None,
) -> list[int]:
    """Obras certificables del mes: fichaje, propuesta con contenido, o contrato.

    Los borradores vacíos (p. ej. abiertos un mes sin movimiento) no cuentan:
    sin fichaje y sin contrato de asistencia ese mes → no salen para enviar.
    """
    ids: set[int] = set()
    for fila in _esqueleto(company_id, anio, mes):
        ids.add(int(fila['obra_id']))

    props = CertificacionPropuesta.query.filter_by(
        company_id=company_id, anio=anio, mes=mes,
    ).all()
    por_obra: dict[int, list[CertificacionPropuesta]] = defaultdict(list)
    for p in props:
        if p.obra_id is not None:
            por_obra[int(p.obra_id)].append(p)

    pendientes = [oid for oid in por_obra if oid not in ids]
    if pendientes:
        company = Company.query.get(company_id)
        obras = {
            o.id: o for o in Obra.query.filter(Obra.id.in_(pendientes)).all()
        }
        cache: dict = {}
        for oid in pendientes:
            if _obra_mes_certificable(
                company, obras.get(oid), por_obra.get(oid) or [],
                anio=anio, mes=mes, tiene_fichaje=False, cache=cache,
            ):
                ids.add(oid)

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
    *,
    refrescar_precios: bool = True,
) -> tuple[CertificacionPropuesta, CertificacionPropuesta]:
    """Crea o refresca el par DIR_SUB + DIR_EMP de una obra. Aceptadas no se tocan (salvo pastillas).

    refrescar_precios=False evita pegarse a Odoo (útil en portal subcontrata / post-guardado).
    """
    obra = Obra.query.get(obra_id)
    esqueleto = _esqueleto(company.id, anio, mes, obra_id=obra_id)
    esqueleto_map = {(f['user_id'], f['obra_id'], f['fecha']): f for f in esqueleto}
    user_ids = {f['user_id'] for f in esqueleto}
    users = {
        u.id: u for u in User.query.filter(User.id.in_(user_ids or {-1})).all()
    }
    cache: dict = {}
    # Una sola fecha de tarifa por mes (el contrato suele cubrir el mes entero).
    try:
        fecha_tarifa = date(anio, mes, 15)
    except ValueError:
        fecha_tarifa = date(anio, mes, 1)
    par = []
    for direccion in (DIR_SUB, DIR_EMP):
        prop = _get_or_create(company, anio, mes, direccion, obra_id)
        # Metadatos de fichaje (Odoo/solape) solo en la propuesta de la oficina.
        if direccion == DIR_EMP:
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
            user = users.get(fila['user_id'])
            ln = actuales.get(key)
            # €/h del contrato: siempre si falta (subcontrata entra con refrescar_precios=False
            # y antes las filas nuevas quedaban a 0). refrescar_precios=True además
            # actualiza tarifas no editadas a mano.
            manual = bool(ln and ln.origen_horas and str(ln.origen_horas).startswith('manual'))
            sin_precio = (
                ln is None
                or ln.precio_hora is None
                or (cuantizar(ln.precio_hora) or Decimal('0.00')) <= 0
            )
            need_precio = sin_precio or (
                refrescar_precios
                and not manual
                and ln is not None
                and ln.origen_horas in ('vacio', 'fichaje')
            )
            if need_precio:
                precio = precio_para(
                    company, obra, user=user, fecha=fecha_tarifa, cache=cache,
                )
            elif ln is not None:
                precio = ln.precio_hora
            else:
                precio = Decimal('0.00')
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
            elif need_precio:
                ln.precio_hora = precio
            if direccion == DIR_EMP:
                ln.estado_fichaje = fila['estado_fichaje']
                ln.solape = bool(fila['solape'])
                if ln.origen_horas in ('vacio', 'fichaje'):
                    ln.hora_inicio = fila['hora_inicio']
                    ln.hora_fin = fila['hora_fin']
                    ln.horas = fila['horas']
                    ln.origen_horas = 'fichaje'
            else:
                # Subcontrata: filas vacías, sin datos del fichaje de la plataforma.
                ln.estado_fichaje = None
                ln.solape = False
        if direccion == DIR_SUB and prop.estado == 'borrador':
            # La sub certifica totales (h × €/h), no el reloj del fichaje de la App.
            for ln in list(prop.lineas or []):
                _limpiar_tramo_subcontrata(ln)
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


def _escribir_campos_linea(linea: CertificacionLinea, *, hora_inicio, hora_fin, horas, precio) -> None:
    """Escribe horas/tramo/precio sin reconsultar bloqueo (uso interno / lotes)."""
    precio_q = cuantizar(precio)
    if precio_q is None:
        precio_q = cuantizar(linea.precio_hora)
    if precio_q is None:
        # Permite guardar horas aunque el contrato aún no haya materializado €/h.
        precio_q = Decimal('0.00')
    linea.precio_hora = precio_q
    # Si la fila se añadió a mano (sin fichaje), conservar la marca al editar.
    anadido = (linea.origen_horas == 'manual_anadido')
    # Si llega un total escrito, manda el total y se vacían inicio y fin.
    if horas is not None and horas != '':
        linea.horas = cuantizar(horas)
        linea.hora_inicio = None
        linea.hora_fin = None
        linea.origen_horas = 'manual_anadido' if anadido else 'manual_total'
        return
    if hora_inicio and hora_fin:
        linea.hora_inicio = hora_inicio
        linea.hora_fin = hora_fin
        linea.horas = horas_desde_datetimes(
            datetime.combine(linea.fecha, hora_inicio),
            datetime.combine(linea.fecha, hora_fin),
        )
        linea.origen_horas = 'manual_anadido' if anadido else 'manual_tramo'
        # Tramo inválido: se conservan las horas para marcar la fila en rojo al enviar.
        return
    linea.hora_inicio = None
    linea.hora_fin = None
    linea.horas = None
    linea.origen_horas = 'manual_anadido' if anadido else 'vacio'


def guardar_linea(linea: CertificacionLinea, *, hora_inicio, hora_fin, horas, precio) -> None:
    if linea.propuesta.estado != 'borrador':
        raise ValueError('Esta propuesta ya no se puede editar.')
    if periodo_bloqueado(
        linea.propuesta.company_id, linea.propuesta.anio, linea.propuesta.mes, linea.propuesta.obra_id,
    ):
        raise ValueError('Esta obra ya está aceptada en el mes.')
    _escribir_campos_linea(
        linea, hora_inicio=hora_inicio, hora_fin=hora_fin, horas=horas, precio=precio,
    )


def lineas_tramo_invalido(prop: CertificacionPropuesta) -> list[int]:
    """Inicio y fin rellenos pero fin ≤ inicio (horas calculadas a None)."""
    return [
        int(ln.id)
        for ln in prop.lineas
        if ln.hora_inicio is not None
        and ln.hora_fin is not None
        and ln.horas is None
    ]


def _esqueleto_mapa(
    company_id: int,
    anio: int,
    mes: int,
    obra_id: int | None = None,
) -> dict[tuple, dict]:
    """Índice (user_id, obra_id, fecha) → fila de fichaje del mes."""
    return {
        (f['user_id'], f['obra_id'], f['fecha']): f
        for f in _esqueleto(company_id, anio, mes, obra_id=obra_id)
    }


def _aplicar_fichaje_a_linea(linea: CertificacionLinea, match: dict | None) -> None:
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


def restablecer_linea_desde_fichaje(
    linea: CertificacionLinea,
    *,
    fichaje_mapa: dict | None = None,
) -> None:
    """Vuelve a poner inicio/fin/horas desde el fichaje de la plataforma."""
    prop = linea.propuesta
    if prop.direccion != DIR_EMP:
        raise ValueError('El restablecimiento desde fichaje solo está disponible para la oficina.')
    if prop.estado != 'borrador':
        raise ValueError('Esta propuesta ya no se puede editar.')
    if periodo_bloqueado(prop.company_id, prop.anio, prop.mes, prop.obra_id):
        raise ValueError('Esta obra ya está aceptada en el mes.')
    mapa = fichaje_mapa
    if mapa is None:
        mapa = _esqueleto_mapa(
            prop.company_id, prop.anio, prop.mes, obra_id=prop.obra_id,
        )
    match = mapa.get((linea.user_id, linea.obra_id, linea.fecha))
    _aplicar_fichaje_a_linea(linea, match)


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


def _limpiar_tramo_subcontrata(ln: CertificacionLinea) -> None:
    """Subcontrata: conserva horas; quita inicio/fin heredados del fichaje."""
    if ln.hora_inicio is None and ln.hora_fin is None:
        return
    if ln.horas is None and ln.hora_inicio and ln.hora_fin and ln.fecha:
        ln.horas = horas_desde_datetimes(
            datetime.combine(ln.fecha, ln.hora_inicio),
            datetime.combine(ln.fecha, ln.hora_fin),
        )
    ln.hora_inicio = None
    ln.hora_fin = None
    if ln.origen_horas == 'manual_tramo':
        ln.origen_horas = 'manual_total' if ln.horas is not None else 'vacio'


def _snapshot_lineas(prop: CertificacionPropuesta) -> list[dict]:
    # Query explícita: la collection lazy puede estar stale tras borrar/recrear filas.
    lineas = (
        CertificacionLinea.query.filter_by(propuesta_id=prop.id).all()
        if prop.id else list(prop.lineas or [])
    )
    out = []
    es_sub = prop.direccion == DIR_SUB
    for ln in sorted(lineas, key=lambda x: (x.fecha, x.user_id or 0)):
        if es_sub:
            _limpiar_tramo_subcontrata(ln)
        nombre = ''
        if ln.user:
            nombre = f'{(ln.user.name or "").strip()} {(ln.user.lastname or "").strip()}'.strip()
        imp = importe_linea(ln.horas, ln.precio_hora)
        # Subcontrata: el envío es por totales; no persistir reloj de fichaje.
        hi = None if es_sub else (ln.hora_inicio.strftime('%H:%M') if ln.hora_inicio else None)
        hf = None if es_sub else (ln.hora_fin.strftime('%H:%M') if ln.hora_fin else None)
        out.append({
            'user_id': ln.user_id,
            'user_name': nombre,
            'obra_id': ln.obra_id,
            'fecha': ln.fecha.isoformat() if ln.fecha else None,
            'hora_inicio': hi,
            'hora_fin': hf,
            'horas': str(ln.horas) if ln.horas is not None else None,
            'precio_hora': str(ln.precio_hora) if ln.precio_hora is not None else None,
            'importe': str(imp) if imp is not None else None,
            'origen_horas': ln.origen_horas,
        })
    return out


def _rondas_periodo(company_id: int, obra_id: int, anio: int, mes: int) -> list[CertificacionRonda]:
    return (
        CertificacionRonda.query.filter_by(
            company_id=company_id, obra_id=obra_id, anio=anio, mes=mes,
        )
        .order_by(CertificacionRonda.secuencia.asc(), CertificacionRonda.id.asc())
        .all()
    )


def ronda_en_mesa(company_id: int, obra_id: int, anio: int, mes: int) -> CertificacionRonda | None:
    return (
        CertificacionRonda.query.filter_by(
            company_id=company_id, obra_id=obra_id, anio=anio, mes=mes,
            resultado='en_mesa',
        )
        .order_by(CertificacionRonda.secuencia.desc())
        .first()
    )


def _siguiente_secuencia(company_id: int, obra_id: int, anio: int, mes: int) -> int:
    last = (
        CertificacionRonda.query.filter(
            CertificacionRonda.company_id == company_id,
            CertificacionRonda.obra_id == obra_id,
            CertificacionRonda.anio == anio,
            CertificacionRonda.mes == mes,
            CertificacionRonda.resultado != 'retirada',
        )
        .order_by(CertificacionRonda.secuencia.desc())
        .first()
    )
    return (last.secuencia if last else 0) + 1


def etiquetas_rondas(rondas: list[CertificacionRonda] | None) -> dict[int, str]:
    """Número de propuesta visible: 1, 1.2, 1.3…; sube a 2 solo tras un rechazo.

    La ``secuencia`` interna sigue siendo 1, 2, 3… (orden). La etiqueta
    agrupa contrapropuestas en la misma negociación.
    """
    vivos = sorted(
        [r for r in (rondas or []) if r and r.resultado != 'retirada' and r.id],
        key=lambda r: (r.secuencia or 0, r.id or 0),
    )
    out: dict[int, str] = {}
    major = 0
    rev = 0
    nueva_cadena = True
    for r in vivos:
        if nueva_cadena:
            major += 1
            rev = 1
            out[int(r.id)] = str(major)
        else:
            rev += 1
            out[int(r.id)] = f'{major}.{rev}'
        nueva_cadena = r.resultado == 'rechazada'
    return out


def etiqueta_ronda(ronda: CertificacionRonda | None, etiquetas: dict[int, str] | None = None) -> str:
    if not ronda or not ronda.id:
        return ''
    if etiquetas is None:
        etiquetas = etiquetas_rondas(
            _rondas_periodo(ronda.company_id, ronda.obra_id, ronda.anio, ronda.mes)
        )
    return etiquetas.get(int(ronda.id), str(ronda.secuencia or ''))


def siguiente_etiqueta_propuesta(etiqueta: str | None) -> str:
    """Etiqueta del próximo envío en la misma negociación (3 → 3.2 → 3.3 → 3.4)."""
    et = (etiqueta or '').strip()
    if not et:
        return '1'
    if '.' not in et:
        return f'{et}.2'
    major, rev = et.rsplit('.', 1)
    try:
        return f'{major}.{int(rev) + 1}'
    except ValueError:
        return f'{et}.2'


def cadena_rondas_negociacion(
    rondas: list[CertificacionRonda] | None,
    ancla: CertificacionRonda | None,
    etiquetas: dict[int, str] | None = None,
) -> list[dict]:
    """Rondas de la misma negociación (mismo nº mayor) hasta el ancla inclusive.

    Pensado para columnas de comparación al corregir: #3, #3.2, #3.3…
    """
    if not ancla or not ancla.id:
        return []
    et = etiquetas if etiquetas is not None else etiquetas_rondas(rondas)
    ancla_et = et.get(int(ancla.id), '')
    if not ancla_et:
        return []
    major = ancla_et.split('.', 1)[0]
    ancla_key = (ancla.secuencia or 0, ancla.id or 0)
    vivos = sorted(
        [r for r in (rondas or []) if r and r.resultado != 'retirada' and r.id],
        key=lambda r: (r.secuencia or 0, r.id or 0),
    )
    out: list[dict] = []
    for r in vivos:
        e = et.get(int(r.id), '')
        if not e or e.split('.', 1)[0] != major:
            continue
        if (r.secuencia or 0, r.id or 0) > ancla_key:
            continue
        out.append({
            'id': int(r.id),
            'etiqueta': e,
            'ronda': r,
            'mapa': mapa_lineas_ronda(r),
            'totales': totales_comparar_ronda(r),
            'direccion': r.direccion,
            'resultado': r.resultado,
        })
    return out


def _purgar_retiradas_y_renumerar(company_id: int, obra_id: int, anio: int, mes: int) -> None:
    """Corregir no deja carta fantasma: borra retiradas y resecuencia 1..N sin huecos."""
    todas = _rondas_periodo(company_id, obra_id, anio, mes)
    for r in list(todas):
        if r.resultado == 'retirada':
            db.session.delete(r)
    db.session.flush()
    vivas = sorted(
        _rondas_periodo(company_id, obra_id, anio, mes),
        key=lambda x: (x.secuencia or 0, x.id or 0),
    )
    for i, r in enumerate(vivas, start=1):
        if r.secuencia != i:
            r.secuencia = i
    db.session.flush()


def _crear_ronda(prop: CertificacionPropuesta, actor_id: int, *, resultado: str = 'en_mesa') -> CertificacionRonda:
    tot = totales(prop)
    ronda = CertificacionRonda(
        company_id=prop.company_id,
        obra_id=prop.obra_id,
        anio=prop.anio,
        mes=prop.mes,
        direccion=prop.direccion,
        secuencia=_siguiente_secuencia(prop.company_id, prop.obra_id, prop.anio, prop.mes),
        resultado=resultado,
        propuesta_id=prop.id,
        enviada_at=utc_now(),
        enviada_por_id=actor_id,
        horas_total=tot['horas'],
        importe_total=tot['importe'],
        lineas_json=_snapshot_lineas(prop),
    )
    db.session.add(ronda)
    db.session.flush()
    return ronda


def _lineas_coinciden_con_ronda(prop: CertificacionPropuesta, ronda: CertificacionRonda | None) -> bool:
    """Compara la propuesta viva con el snapshot de una ronda (misma firma)."""
    if not ronda or not ronda.lineas_json:
        return False
    fake = []
    for row in ronda.lineas_json:
        fecha = row.get('fecha')
        if isinstance(fecha, str):
            try:
                fecha = date.fromisoformat(fecha)
            except ValueError:
                fecha = None
        fake.append({
            'user_id': row.get('user_id'),
            'obra_id': row.get('obra_id'),
            'fecha': fecha,
            'horas': row.get('horas'),
            'precio_hora': row.get('precio_hora'),
        })
    return propuestas_coinciden(prop.lineas, fake)


def asegurar_rondas_periodo(company_id: int, obra_id: int, anio: int, mes: int) -> None:
    """Backfill: si hay propuestas enviadas/aceptadas/rechazadas sin rondas, crea snapshot."""
    existing = _rondas_periodo(company_id, obra_id, anio, mes)
    if existing:
        return
    props = CertificacionPropuesta.query.filter_by(
        company_id=company_id, obra_id=obra_id, anio=anio, mes=mes,
    ).all()
    enviadas = [p for p in props if p.estado in ('enviada', 'aceptada', 'cerrada') and p.enviada_at]
    enviadas.sort(key=lambda p: (p.enviada_at or utc_now(), p.id))
    seq = 0
    for i, prop in enumerate(enviadas, start=1):
        seq = i
        if prop.estado == 'aceptada':
            resultado = 'aceptada'
        elif prop.estado == 'enviada' and i == len(enviadas):
            resultado = 'en_mesa'
        else:
            resultado = 'sustituida'
        tot = totales(prop)
        db.session.add(CertificacionRonda(
            company_id=company_id,
            obra_id=obra_id,
            anio=anio,
            mes=mes,
            direccion=prop.direccion,
            secuencia=i,
            resultado=resultado,
            propuesta_id=prop.id,
            enviada_at=prop.enviada_at or utc_now(),
            enviada_por_id=prop.enviada_por_id,
            respondida_at=prop.aceptada_at if prop.estado == 'aceptada' else None,
            respondida_por_id=prop.respondida_por_id,
            horas_total=tot['horas'],
            importe_total=tot['importe'],
            lineas_json=_snapshot_lineas(prop),
        ))
    # Rechazos ya vueltos a borrador sin snapshot (antes del historial / sin commit).
    for prop in props:
        motivo = (prop.comentario_rechazo or '').strip()
        if prop.estado != 'borrador' or not motivo:
            continue
        if any(p.id == prop.id for p in enviadas):
            continue
        seq += 1
        tot = totales(prop)
        db.session.add(CertificacionRonda(
            company_id=company_id,
            obra_id=obra_id,
            anio=anio,
            mes=mes,
            direccion=prop.direccion,
            secuencia=seq,
            resultado='rechazada',
            propuesta_id=prop.id,
            enviada_at=utc_now(),
            enviada_por_id=prop.enviada_por_id,
            respondida_at=utc_now(),
            respondida_por_id=prop.respondida_por_id,
            comentario_rechazo=motivo,
            horas_total=tot['horas'],
            importe_total=tot['importe'],
            lineas_json=_snapshot_lineas(prop),
        ))
    if seq:
        db.session.flush()


def _nombre_actor(actor_id: int | None) -> str:
    if not actor_id:
        return ''
    u = User.query.get(actor_id)
    if not u:
        return ''
    return f'{(u.name or "").strip()} {(u.lastname or "").strip()}'.strip()


def mapa_lineas_ronda(ronda: CertificacionRonda | None) -> dict:
    """Clave (user_id, obra_id, fecha) → dict snapshot para comparar bajo cada fila."""
    out = {}
    if not ronda or not ronda.lineas_json:
        return out
    obra_fallback = getattr(ronda, 'obra_id', None)
    for row in ronda.lineas_json:
        fecha = row.get('fecha')
        if isinstance(fecha, str):
            try:
                fecha_d = date.fromisoformat(fecha)
            except ValueError:
                continue
        elif isinstance(fecha, date):
            fecha_d = fecha
        else:
            continue
        oid = row.get('obra_id') if row.get('obra_id') is not None else obra_fallback
        key = (row.get('user_id'), oid, fecha_d)
        out[key] = row
    return out


def totales_comparar_ronda(ronda: CertificacionRonda | None) -> dict:
    """Totales + agregados por persona, día y (persona, día) para la UI de comparación."""
    vacio = {
        'horas': Decimal('0.00'),
        'importe': Decimal('0.00'),
        'por_persona': {},
        'por_persona_fecha': {},
        'por_fecha': {},
    }
    if not ronda or not ronda.lineas_json:
        if ronda and ronda.horas_total is not None:
            vacio['horas'] = cuantizar(ronda.horas_total) or Decimal('0.00')
            vacio['importe'] = cuantizar(ronda.importe_total) or Decimal('0.00')
        return vacio
    th = Decimal('0.00')
    ti = Decimal('0.00')
    por_p: dict = {}
    por_pf: dict = {}
    por_f: dict = {}
    for row in ronda.lineas_json:
        uid = row.get('user_id')
        fecha = _parse_fecha_snap(row.get('fecha'))
        h = _snap_dec(row.get('horas')) or Decimal('0.00')
        p = _snap_dec(row.get('precio_hora'))
        imp = _snap_dec(row.get('importe'))
        if imp is None:
            imp = importe_linea(h, p) or Decimal('0.00')
        th += h
        ti += imp
        if fecha is not None:
            bf = por_f.setdefault(fecha, {'horas': Decimal('0.00'), 'importe': Decimal('0.00')})
            bf['horas'] += h
            bf['importe'] += imp
        if uid is not None:
            bucket = por_p.setdefault(uid, {'horas': Decimal('0.00'), 'importe': Decimal('0.00')})
            bucket['horas'] += h
            bucket['importe'] += imp
            if fecha is not None:
                key = (uid, fecha)
                b2 = por_pf.setdefault(key, {'horas': Decimal('0.00'), 'importe': Decimal('0.00')})
                b2['horas'] += h
                b2['importe'] += imp
    for b in por_p.values():
        b['horas'] = cuantizar(b['horas']) or Decimal('0.00')
        b['importe'] = cuantizar(b['importe']) or Decimal('0.00')
    for b in por_pf.values():
        b['horas'] = cuantizar(b['horas']) or Decimal('0.00')
        b['importe'] = cuantizar(b['importe']) or Decimal('0.00')
    for b in por_f.values():
        b['horas'] = cuantizar(b['horas']) or Decimal('0.00')
        b['importe'] = cuantizar(b['importe']) or Decimal('0.00')
    return {
        'horas': cuantizar(th) or Decimal('0.00'),
        'importe': cuantizar(ti) or Decimal('0.00'),
        'por_persona': por_p,
        'por_persona_fecha': por_pf,
        'por_fecha': por_f,
    }


def _parse_fecha_snap(raw) -> date | None:
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _snap_dec(raw) -> Decimal | None:
    if raw in (None, ''):
        return None
    return cuantizar(raw)


def agrupar_snapshot(
    lineas_json: list | None,
    *,
    modo: str = 'persona',
    obra_id: int | None = None,
) -> list[dict]:
    """Misma forma que la propuesta viva: persona→días o fecha→líneas (solo lectura)."""
    rows = []
    for row in lineas_json or []:
        fecha = _parse_fecha_snap(row.get('fecha'))
        if not fecha:
            continue
        h = _snap_dec(row.get('horas')) or Decimal('0.00')
        p = _snap_dec(row.get('precio_hora'))
        imp = _snap_dec(row.get('importe'))
        if imp is None:
            imp = importe_linea(h, p) or Decimal('0.00')
        oid = row.get('obra_id')
        if oid is None:
            oid = obra_id
        rows.append({
            'user_id': row.get('user_id'),
            'user_name': (row.get('user_name') or '').strip() or 'Persona',
            'obra_id': oid,
            'fecha': fecha,
            'hora_inicio': row.get('hora_inicio'),
            'hora_fin': row.get('hora_fin'),
            'horas': h,
            'precio_hora': p,
            'importe': imp,
            'origen_horas': row.get('origen_horas'),
        })

    if modo == 'fecha':
        fechas: dict = {}
        for r in sorted(rows, key=lambda x: (x['fecha'], x['user_name'].lower())):
            bucket = fechas.setdefault(r['fecha'], {
                'fecha': r['fecha'],
                'lineas': [],
                'horas': Decimal('0.00'),
                'importe': Decimal('0.00'),
            })
            bucket['lineas'].append(r)
            bucket['horas'] += r['horas']
            bucket['importe'] += r['importe']
        out = []
        for k in sorted(fechas):
            b = fechas[k]
            b['horas'] = cuantizar(b['horas']) or Decimal('0.00')
            b['importe'] = cuantizar(b['importe']) or Decimal('0.00')
            out.append(b)
        return out

    personas: dict = {}
    for r in sorted(rows, key=lambda x: (x['user_name'].lower(), x['fecha'])):
        uid = r['user_id'] if r['user_id'] is not None else r['user_name']
        bucket = personas.setdefault(uid, {
            'nombre': r['user_name'],
            'user_id': r['user_id'],
            'fechas': [],
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
        })
        bucket['fechas'].append(r)
        bucket['horas'] += r['horas']
        bucket['importe'] += r['importe']
    out = []
    for b in personas.values():
        # Agrupa filas del mismo día bajo un día desplegable.
        by_day: dict = {}
        for r in b['fechas']:
            day = by_day.setdefault(r['fecha'], {
                'fecha': r['fecha'],
                'lineas': [],
                'horas': Decimal('0.00'),
                'importe': Decimal('0.00'),
            })
            day['lineas'].append(r)
            day['horas'] += r['horas']
            day['importe'] += r['importe']
        fechas = []
        for k in sorted(by_day):
            d = by_day[k]
            d['horas'] = cuantizar(d['horas']) or Decimal('0.00')
            d['importe'] = cuantizar(d['importe']) or Decimal('0.00')
            fechas.append(d)
        out.append({
            'nombre': b['nombre'],
            'user_id': b.get('user_id'),
            'fechas': fechas,
            'horas': cuantizar(b['horas']) or Decimal('0.00'),
            'importe': cuantizar(b['importe']) or Decimal('0.00'),
        })
    out.sort(key=lambda p: (p['nombre'] or '').lower())
    return out


def _plat_fila_snapshot(row: dict, mapa_plat: dict, *, obra_id, precio_fb, fecha=None):
    uid = row.get('user_id')
    oid = row.get('obra_id') or obra_id
    fch = fecha or row.get('fecha')
    ref = mapa_plat.get((uid, oid, fch)) if uid and oid and fch else None
    if not ref or ref.get('horas') is None:
        row['plat_horas'] = None
        row['plat_importe'] = None
        return Decimal('0.00'), Decimal('0.00')
    h = cuantizar(ref['horas']) or Decimal('0.00')
    precio = row.get('precio_hora')
    if precio is None:
        precio = precio_fb
    imp = importe_linea(h, precio) or Decimal('0.00')
    row['plat_horas'] = h
    row['plat_importe'] = imp
    return h, imp


def enriquecer_snapshot_plataforma(
    grupos: list[dict],
    mapa_plat: dict,
    *,
    precio_fallback=None,
    obra_id: int | None = None,
) -> list[dict]:
    """Añade plat_horas / plat_importe a grupos de historial (snapshot)."""
    precio_fb = cuantizar(precio_fallback) if precio_fallback is not None else None
    for grupo in grupos or []:
        # Modo persona: persona → fechas → líneas
        if grupo.get('fechas') is not None:
            h_obra = Decimal('0.00')
            i_obra = Decimal('0.00')
            for fecha in grupo.get('fechas') or []:
                h_f = Decimal('0.00')
                i_f = Decimal('0.00')
                for row in fecha.get('lineas') or []:
                    h, imp = _plat_fila_snapshot(
                        row, mapa_plat,
                        obra_id=obra_id, precio_fb=precio_fb,
                        fecha=fecha.get('fecha'),
                    )
                    h_f += h
                    i_f += imp
                fecha['plat_horas'] = cuantizar(h_f) or Decimal('0.00')
                fecha['plat_importe'] = cuantizar(i_f) or Decimal('0.00')
                h_obra += h_f
                i_obra += i_f
            grupo['plat_horas'] = cuantizar(h_obra) or Decimal('0.00')
            grupo['plat_importe'] = cuantizar(i_obra) or Decimal('0.00')
            continue
        # Modo fecha: día → líneas
        h_f = Decimal('0.00')
        i_f = Decimal('0.00')
        for row in grupo.get('lineas') or []:
            h, imp = _plat_fila_snapshot(
                row, mapa_plat,
                obra_id=obra_id, precio_fb=precio_fb,
                fecha=grupo.get('fecha'),
            )
            h_f += h
            i_f += imp
        grupo['plat_horas'] = cuantizar(h_f) or Decimal('0.00')
        grupo['plat_importe'] = cuantizar(i_f) or Decimal('0.00')
    return grupos


def sembrar_borrador_desde_mesa(
    prop: CertificacionPropuesta,
    mesa: CertificacionRonda | None,
) -> int:
    """Al responder: copia al borrador la propuesta recibida (horas/tramos/€).

    Así la subcontrata (u oficina) ve lo mismo que le han enviado y puede
    aceptar sin tener que pulsar «Copiar su propuesta» fila a fila.
    No pisa si ya hay edición manual en el borrador.
    """
    if not prop or prop.estado != 'borrador' or not mesa:
        return 0
    if mesa.resultado != 'en_mesa':
        return 0
    if mesa.direccion == prop.direccion:
        return 0
    # No pisar una corrección que el usuario ya ha tocado.
    if any(
        ln.origen_horas and str(ln.origen_horas).startswith('manual')
        for ln in (prop.lineas or [])
    ):
        return 0
    return aplicar_ronda_a_borrador(prop, mesa)


def sembrar_borrador_desde_ronda_propia(
    prop: CertificacionPropuesta,
    *,
    propia_dir: str,
) -> int:
    """Compat: delega en la siembra desde la carta en mesa si existe."""
    mesa = ronda_en_mesa(prop.company_id, prop.obra_id, prop.anio, prop.mes)
    if mesa and mesa.direccion != propia_dir:
        return sembrar_borrador_desde_mesa(prop, mesa)
    return 0


def publicar_chat(
    company_id: int,
    obra_id: int,
    anio: int,
    mes: int,
    *,
    texto: str,
    tipo: str = 'nota',
    direccion: str = 'sistema',
    autor_id: int | None = None,
) -> CertificacionChatMensaje:
    msg = CertificacionChatMensaje(
        company_id=company_id,
        obra_id=obra_id,
        anio=anio,
        mes=mes,
        texto=(texto or '').strip(),
        tipo=tipo,
        direccion=direccion,
        autor_id=autor_id,
        created_at=utc_now(),
    )
    if not msg.texto:
        raise ValueError('Escribe un mensaje.')
    db.session.add(msg)
    db.session.flush()
    return msg


def listar_chat(
    company_id: int, obra_id: int, anio: int, mes: int,
) -> list[CertificacionChatMensaje]:
    return (
        CertificacionChatMensaje.query.filter_by(
            company_id=company_id, obra_id=obra_id, anio=anio, mes=mes,
        )
        .order_by(CertificacionChatMensaje.created_at.asc(), CertificacionChatMensaje.id.asc())
        .all()
    )


def _chat_evento(prop: CertificacionPropuesta, actor_id: int, tipo: str, texto: str) -> None:
    try:
        publicar_chat(
            prop.company_id, prop.obra_id, prop.anio, prop.mes,
            texto=texto, tipo=tipo, direccion=prop.direccion, autor_id=actor_id,
        )
    except Exception:
        # El flujo principal (enviar/rechazar) no debe fallar por el chat.
        db.session.flush()


_CHAT_TOTALES_RE = re.compile(
    r'\s*[·•]\s*[\d]+(?:[.,]\d+)?\s*h\s*[·•]\s*[\d]+(?:[.,]\d+)?\s*€\s*',
    re.IGNORECASE,
)


def _texto_chat_ui(texto: str, autor: str = '', tipo: str = '') -> str:
    """Quita nombre duplicado y totales (h/€) del cuerpo: el autor ya va en la cabecera."""
    out = (texto or '').strip()
    if not out:
        return out
    nombre = (autor or '').strip()
    if nombre and out.lower().startswith(nombre.lower()):
        out = out[len(nombre):].lstrip(' :·—-')
    if tipo in ('envio', 'aceptacion', 'desenvio', 'rechazo') or _CHAT_TOTALES_RE.search(out):
        out = _CHAT_TOTALES_RE.sub('', out).strip(' ·•')
    # Capitaliza tras quitar el nombre ("ha enviado…" → "Ha enviado…")
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    return out


def enviar(
    prop: CertificacionPropuesta,
    actor_id: int,
    *,
    company: Company | None = None,
    obra: Obra | None = None,
    contrato: dict | None = None,
) -> None:
    """Envía borrador a la mesa: una sola carta activa; historial en rondas."""
    if prop.estado != 'borrador':
        raise ValueError('Solo se envía un borrador.')
    if periodo_bloqueado(prop.company_id, prop.anio, prop.mes, prop.obra_id):
        raise ValueError('Esta obra ya está aceptada en el mes.')

    company = company or Company.query.get(prop.company_id)
    obra = obra or (Obra.query.get(prop.obra_id) if prop.obra_id else None)
    if contrato is None and company is not None and obra is not None:
        contrato = contrato_asistencia_mes(company, obra, prop.anio, prop.mes)
    if not contrato:
        raise ValueError(
            'No hay un contrato de asistencia vinculado a este periodo. '
            'No se puede enviar la propuesta.'
        )
    con_horas = [
        ln for ln in (prop.lineas or [])
        if ln.horas is not None or (ln.hora_inicio and ln.hora_fin)
    ]
    if not con_horas:
        raise ValueError('No hay horas que enviar en este periodo.')
    if not _lineas_completas(prop):
        raise ValueError('Rellena las horas de todas las filas antes de enviar.')

    asegurar_rondas_periodo(prop.company_id, prop.obra_id, prop.anio, prop.mes)
    previa = ronda_en_mesa(prop.company_id, prop.obra_id, prop.anio, prop.mes)

    # Autoaceptar si la mesa era de la otra parte y coincide línea a línea.
    if previa and previa.direccion != prop.direccion and _lineas_coinciden_con_ronda(prop, previa):
        prop.estado = 'enviada'
        prop.enviada_at = utc_now()
        prop.enviada_por_id = actor_id
        prop.comentario_rechazo = None
        prop.requerida_at = None
        prop.requerida_por_id = None
        _crear_ronda(prop, actor_id, resultado='aceptada')
        previa.resultado = 'aceptada'
        previa.respondida_at = utc_now()
        previa.respondida_por_id = actor_id
        ahora = utc_now()
        prop.estado = 'aceptada'
        prop.aceptada_at = ahora
        otra = CertificacionPropuesta.query.filter_by(
            company_id=prop.company_id,
            obra_id=prop.obra_id,
            anio=prop.anio,
            mes=prop.mes,
            direccion=_otra(prop.direccion),
        ).first()
        if otra:
            otra.estado = 'aceptada'
            otra.aceptada_at = ahora
            otra.comentario_rechazo = None
        _limpiar_rechazo_mes(prop.company_id, prop.anio, prop.mes, prop.obra_id)
        _chat_evento(
            prop, actor_id, 'aceptacion',
            'Ha enviado y se ha aceptado automáticamente (coinciden).',
        )
        try:
            from app.services.certificacion_avisos_service import reactivar_avisos_mes
            reactivar_avisos_mes(prop.anio, prop.mes, company_id=prop.company_id, obra_id=prop.obra_id)
        except Exception:
            pass
        _avisar(prop, actor_id, aceptada=True)
        if otra:
            _avisar(otra, actor_id, aceptada=True)
        return

    # Sustituye lo que hubiera en la mesa (de cualquiera).
    if previa:
        previa.resultado = 'sustituida'
        if previa.direccion != prop.direccion:
            otra = CertificacionPropuesta.query.filter_by(
                company_id=prop.company_id,
                obra_id=prop.obra_id,
                anio=prop.anio,
                mes=prop.mes,
                direccion=previa.direccion,
            ).first()
            if otra and otra.estado == 'enviada':
                otra.estado = 'borrador'
                otra.enviada_at = None
                # Conserva el rechazo vacío; la ronda guarda el historial.

    prop.estado = 'enviada'
    prop.enviada_at = utc_now()
    prop.enviada_por_id = actor_id
    prop.comentario_rechazo = None
    # Al enviar, el requerimiento de completar queda satisfecho.
    prop.requerida_at = None
    prop.requerida_por_id = None
    # El rechazo anterior queda en la ronda del historial; la otra parte ya no es "rechazada".
    otra_viva = CertificacionPropuesta.query.filter_by(
        company_id=prop.company_id,
        obra_id=prop.obra_id,
        anio=prop.anio,
        mes=prop.mes,
        direccion=_otra(prop.direccion),
    ).first()
    if otra_viva and otra_viva.estado == 'borrador':
        otra_viva.comentario_rechazo = None
    ronda = _crear_ronda(prop, actor_id, resultado='en_mesa')
    etiqueta = etiqueta_ronda(ronda)
    _chat_evento(
        prop, actor_id, 'envio',
        f'Ha enviado la propuesta #{etiqueta}.',
    )
    try:
        from app.services.certificacion_avisos_service import reactivar_avisos_mes
        reactivar_avisos_mes(prop.anio, prop.mes, company_id=prop.company_id, obra_id=prop.obra_id)
    except Exception:
        pass
    _avisar(prop, actor_id)


def requerir_accion(
    company: Company,
    obra_id: int,
    anio: int,
    mes: int,
    actor_id: int,
) -> CertificacionPropuesta:
    """SaaS pide a la subcontrata que complete/envíe la certificación de esta obra+mes."""
    if periodo_bloqueado(company.id, anio, mes, obra_id):
        raise ValueError('Esta obra ya está aceptada en el mes.')
    sub, emp = sincronizar(company, anio, mes, obra_id, refrescar_precios=False)
    if not sub:
        raise ValueError('No se pudo preparar la propuesta de la subcontrata.')
    if sub.estado == 'enviada':
        raise ValueError('Ya hay una propuesta enviada pendiente de revisar.')
    if sub.estado == 'aceptada':
        raise ValueError('El mes ya está aceptado.')
    if emp and emp.estado == 'enviada':
        raise ValueError(
            'La subcontrata ya tiene una propuesta nuestra pendiente de respuesta.'
        )
    if sub.requerida_at:
        return sub
    sub.requerida_at = utc_now()
    sub.requerida_por_id = actor_id
    try:
        publicar_chat(
            company.id, obra_id, anio, mes,
            texto='Ha requerido completar la certificación de horario.',
            tipo='requerimiento',
            direccion=DIR_EMP,
            autor_id=actor_id,
        )
    except Exception:
        db.session.flush()
    try:
        from app.services.certificacion_avisos_service import reactivar_avisos_mes
        reactivar_avisos_mes(anio, mes, company_id=company.id, obra_id=obra_id)
    except Exception:
        pass
    _avisar(sub, actor_id, requerida=True)
    return sub


def desenviar(prop: CertificacionPropuesta, actor_id: int) -> None:
    """Corrige el envío: vuelve a borrador y elimina la carta (no deja # fantasma)."""
    if prop.estado != 'enviada':
        raise ValueError('Solo se puede corregir una propuesta enviada.')
    if periodo_bloqueado(prop.company_id, prop.anio, prop.mes, prop.obra_id):
        raise ValueError('Esta obra ya está aceptada; no se puede corregir.')
    mesa = ronda_en_mesa(prop.company_id, prop.obra_id, prop.anio, prop.mes)
    if mesa and mesa.propuesta_id == prop.id:
        # No marcar «retirada»: al reenviar debe reutilizar el mismo número.
        db.session.delete(mesa)
        db.session.flush()
        _purgar_retiradas_y_renumerar(prop.company_id, prop.obra_id, prop.anio, prop.mes)
    prop.estado = 'borrador'
    prop.enviada_at = None
    prop.enviada_por_id = None
    prop.respondida_por_id = None
    prop.comentario_rechazo = None
    _chat_evento(
        prop, actor_id, 'desenvio',
        'Ha corregido la propuesta (vuelve a borrador).',
    )
    try:
        from app.services.certificacion_avisos_service import reactivar_avisos_mes
        reactivar_avisos_mes(prop.anio, prop.mes, company_id=prop.company_id, obra_id=prop.obra_id)
    except Exception:
        pass
    _avisar(prop, actor_id, retirada=True)


def aceptar(prop: CertificacionPropuesta, actor_id: int) -> None:
    if prop.estado != 'enviada':
        raise ValueError('No hay una propuesta pendiente de aceptar.')
    ahora = utc_now()
    prop.estado = 'aceptada'
    prop.aceptada_at = ahora
    prop.respondida_por_id = actor_id
    prop.comentario_rechazo = None
    mesa = ronda_en_mesa(prop.company_id, prop.obra_id, prop.anio, prop.mes)
    if mesa and (mesa.propuesta_id == prop.id or mesa.direccion == prop.direccion):
        mesa.resultado = 'aceptada'
        mesa.respondida_at = ahora
        mesa.respondida_por_id = actor_id
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
    # El actor es quien acepta (lado contrario al de la propuesta aceptada).
    publicar_chat(
        prop.company_id, prop.obra_id, prop.anio, prop.mes,
        texto='Ha aceptado la propuesta. Mes cerrado.',
        tipo='aceptacion',
        direccion=_otra(prop.direccion),
        autor_id=actor_id,
    )
    try:
        from app.services.certificacion_avisos_service import reactivar_avisos_mes
        reactivar_avisos_mes(prop.anio, prop.mes, company_id=prop.company_id, obra_id=prop.obra_id)
    except Exception:
        pass
    _avisar(prop, actor_id, aceptada=True)


def _reiniciar_lineas_propuesta(prop: CertificacionPropuesta) -> None:
    """Horas/tramos a punto de partida (oficina = fichaje; subcontrata = vacío)."""
    lineas = list(prop.lineas or [])
    if not lineas:
        return
    if prop.direccion != DIR_EMP:
        for ln in lineas:
            ln.hora_inicio = None
            ln.hora_fin = None
            ln.horas = None
            ln.origen_horas = 'vacio'
        return
    mapa = _esqueleto_mapa(prop.company_id, prop.anio, prop.mes, obra_id=prop.obra_id)
    for ln in lineas:
        _aplicar_fichaje_a_linea(ln, mapa.get((ln.user_id, ln.obra_id, ln.fecha)))


def _reiniciar_a_propuesta_nueva(prop: CertificacionPropuesta) -> None:
    """Tras un rechazo: la carta queda en historial y el borrador vuelve a cero."""
    prop.estado = 'borrador'
    prop.enviada_at = None
    prop.enviada_por_id = None
    prop.comentario_rechazo = None
    prop.respondida_por_id = None
    prop.aceptada_at = None
    _reiniciar_lineas_propuesta(prop)


def reabrir_periodo(
    company_id: int,
    obra_id: int,
    anio: int,
    mes: int,
    actor_id: int,
) -> CertificacionRonda | None:
    """SaaS: vuelve a abrir un mes aceptado o una propuesta rechazada.

    Desbloquea el periodo y pone de nuevo sobre la mesa la última carta
    aceptada/rechazada (si existe), para poder aceptar o corregir otra vez.
    """
    if ronda_en_mesa(company_id, obra_id, anio, mes):
        raise ValueError('Ya hay una propuesta sobre la mesa.')

    props = list(
        CertificacionPropuesta.query.filter_by(
            company_id=company_id, obra_id=obra_id, anio=anio, mes=mes,
        ).all()
    )
    by_dir = {p.direccion: p for p in props}
    estaba_cerrado = any((p.estado or '') == 'aceptada' for p in props)

    rondas = _rondas_periodo(company_id, obra_id, anio, mes)
    candidata = None
    for r in reversed(rondas):
        if (r.resultado or '') in ('aceptada', 'rechazada'):
            candidata = r
            break

    if not estaba_cerrado and candidata is None:
        raise ValueError('No hay una certificación aceptada o rechazada que reabrir.')

    # 1) Quitar el candado (aceptada) antes de tocar líneas.
    for p in props:
        p.estado = 'borrador'
        p.aceptada_at = None
        p.enviada_at = None
        p.enviada_por_id = None
        p.respondida_por_id = None
        p.comentario_rechazo = None
    db.session.flush()

    mesa = None
    if candidata is not None:
        prop = by_dir.get(candidata.direccion)
        if prop is None and candidata.propuesta_id:
            prop = CertificacionPropuesta.query.get(candidata.propuesta_id)
        if prop is None:
            raise ValueError('No se encuentra la propuesta a reabrir.')
        # No hace falta vaciar antes: aplicar_ronda_a_borrador pisa horas/tramos.
        aplicar_ronda_a_borrador(prop, candidata)
        prop.estado = 'enviada'
        prop.enviada_at = candidata.enviada_at or utc_now()
        prop.enviada_por_id = candidata.enviada_por_id or actor_id
        candidata.resultado = 'en_mesa'
        candidata.respondida_at = None
        candidata.respondida_por_id = None
        candidata.comentario_rechazo = None
        mesa = candidata

        otra = by_dir.get(_otra(prop.direccion))
        if otra is not None:
            _reiniciar_lineas_propuesta(otra)
    else:
        for p in props:
            _reiniciar_lineas_propuesta(p)

    etiqueta = etiqueta_ronda(mesa) if mesa else ''
    texto = (
        f'Ha vuelto a abrir la certificación (propuesta #{etiqueta} sobre la mesa).'
        if etiqueta
        else 'Ha vuelto a abrir la certificación.'
    )
    # Actor SaaS = lado empresa.
    publicar_chat(
        company_id, obra_id, anio, mes,
        texto=texto,
        tipo='desenvio',
        direccion=DIR_EMP,
        autor_id=actor_id,
    )
    try:
        from app.services.certificacion_avisos_service import reactivar_avisos_mes
        reactivar_avisos_mes(anio, mes, company_id=company_id, obra_id=obra_id)
    except Exception:
        pass
    return mesa


def rechazar(prop: CertificacionPropuesta, actor_id: int, comentario: str) -> None:
    if prop.estado != 'enviada':
        raise ValueError('Solo se rechaza una propuesta enviada.')
    if not (comentario or '').strip():
        raise ValueError('Escribe por qué no cuadra.')
    motivo = comentario.strip()
    ahora = utc_now()
    asegurar_rondas_periodo(prop.company_id, prop.obra_id, prop.anio, prop.mes)
    mesa = ronda_en_mesa(prop.company_id, prop.obra_id, prop.anio, prop.mes)
    if mesa and (mesa.propuesta_id == prop.id or mesa.direccion == prop.direccion):
        mesa.resultado = 'rechazada'
        mesa.comentario_rechazo = motivo
        mesa.respondida_at = ahora
        mesa.respondida_por_id = actor_id
    else:
        # No había carta en mesa (envío antiguo / backfill fallido): crea snapshot al rechazar.
        ronda = _crear_ronda(prop, prop.enviada_por_id or actor_id, resultado='rechazada')
        ronda.comentario_rechazo = motivo
        ronda.respondida_at = ahora
        ronda.respondida_por_id = actor_id
    publicar_chat(
        prop.company_id, prop.obra_id, prop.anio, prop.mes,
        texto=f'Ha rechazado la propuesta: {motivo}',
        tipo='rechazo',
        direccion=_otra(prop.direccion),
        autor_id=actor_id,
    )
    try:
        from app.services.certificacion_avisos_service import reactivar_avisos_mes
        reactivar_avisos_mes(prop.anio, prop.mes, company_id=prop.company_id, obra_id=prop.obra_id)
    except Exception:
        pass
    _avisar(prop, actor_id, rechazo=motivo)
    # Cierra el ciclo: ambos borradores parten de cero (el rechazo queda en el historial/chat).
    _reiniciar_a_propuesta_nueva(prop)
    otra = CertificacionPropuesta.query.filter_by(
        company_id=prop.company_id,
        obra_id=prop.obra_id,
        anio=prop.anio,
        mes=prop.mes,
        direccion=_otra(prop.direccion),
    ).first()
    if otra and otra.estado != 'aceptada':
        _reiniciar_a_propuesta_nueva(otra)


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


def _avisar(
    prop: CertificacionPropuesta,
    actor_id: int,
    *,
    aceptada=False,
    rechazo=None,
    retirada=False,
    requerida=False,
) -> None:
    """Avisa según la matriz de correos (grupo Certificación).

    - Enviar / retirar: avisa a la otra parte.
    - Aceptar / rechazar: avisa al dueño de la propuesta tocada.
    - Requerir: avisa a la subcontrata.
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
    elif requerida:
        event_key = 'cert_pendiente'
        asunto = f'Certificación requerida · {nombre} · {obra_txt} · {periodo}'
        cuerpo = (
            f'Se te ha requerido completar y enviar la certificación de horario '
            f'de {obra_txt} ({periodo}).'
        )
        notify_sub = True
        notify_office = False
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


def _prorratear_lineas(lineas: list, horas_total) -> int:
    """Reparte horas a partes iguales entre las filas (centavos; el resto al inicio)."""
    total = cuantizar(horas_total)
    if total is None or total < 0:
        raise ValueError('El total de horas no es válido.')
    lineas = list(lineas)
    if not lineas:
        raise ValueError('No hay fichajes para prorratear.')
    n = len(lineas)
    cents = int((total * 100).to_integral_value())
    base, resto = divmod(cents, n)
    for i, ln in enumerate(lineas):
        parte = base + (1 if i < resto else 0)
        ln.horas = cuantizar(Decimal(parte) / Decimal(100)) or Decimal('0.00')
        ln.hora_inicio = None
        ln.hora_fin = None
        ln.origen_horas = 'manual_total'
    return n


def prorratear_horas_persona(
    prop: CertificacionPropuesta,
    user_id: int,
    horas_total,
    *,
    fecha: date | None = None,
) -> int:
    """Reparte un total de horas entre las filas de esa persona (mes o un día concreto)."""
    if prop.estado != 'borrador':
        raise ValueError('Esta propuesta ya no se puede editar.')
    if periodo_bloqueado(prop.company_id, prop.anio, prop.mes, prop.obra_id):
        raise ValueError('Esta obra ya está aceptada en el mes.')
    lineas = [
        ln for ln in prop.lineas
        if ln.user_id == int(user_id) and (fecha is None or ln.fecha == fecha)
    ]
    lineas = sorted(lineas, key=lambda ln: (ln.fecha, ln.id or 0))
    if not lineas:
        raise ValueError(
            'No hay fichajes de esa persona en ese día.'
            if fecha is not None
            else 'No hay días de esa persona en la propuesta.'
        )
    return _prorratear_lineas(lineas, horas_total)


def prorratear_horas_fecha(
    prop: CertificacionPropuesta,
    fecha: date,
    horas_total,
) -> int:
    """Reparte un total de horas del día entre todas las personas/filas de esa fecha."""
    if prop.estado != 'borrador':
        raise ValueError('Esta propuesta ya no se puede editar.')
    if periodo_bloqueado(prop.company_id, prop.anio, prop.mes, prop.obra_id):
        raise ValueError('Esta obra ya está aceptada en el mes.')
    if fecha is None:
        raise ValueError('Fecha no válida.')
    lineas = sorted(
        [ln for ln in prop.lineas if ln.fecha == fecha],
        key=lambda ln: (ln.user_id or 0, ln.id or 0),
    )
    if not lineas:
        raise ValueError('No hay fichajes en ese día.')
    return _prorratear_lineas(lineas, horas_total)


def operarios_empresa_certificacion(company_id: int) -> list[User]:
    """Personal activo de la subcontrata (únicos que se pueden añadir a mano)."""
    return (
        User.query.filter(
            User.company_id == int(company_id),
            User.is_deleted.is_(False),
            User.active.is_(True),
        )
        .order_by(User.name.asc(), User.lastname.asc(), User.id.asc())
        .all()
    )


def anadir_dia_manual(
    prop: CertificacionPropuesta,
    *,
    user_id: int,
    fecha: date,
    horas=None,
    company: Company | None = None,
    obra: Obra | None = None,
) -> CertificacionLinea:
    """Añade un día de un trabajador de la empresa a la propuesta (sin fichaje).

    origen_horas = ``manual_anadido`` para que la oficina vea que no fichó en App.
    """
    if prop.estado != 'borrador':
        raise ValueError('Esta propuesta ya no se puede editar.')
    if periodo_bloqueado(prop.company_id, prop.anio, prop.mes, prop.obra_id):
        raise ValueError('Esta obra ya está aceptada en el mes.')
    uid = int(user_id)
    user = User.query.filter_by(id=uid, is_deleted=False).first()
    if not user or user.company_id != prop.company_id:
        raise ValueError('Solo puedes añadir personal de esta empresa.')
    if not user.active:
        raise ValueError('Ese trabajador no está activo.')
    if not isinstance(fecha, date):
        raise ValueError('Fecha no válida.')
    if fecha.year != prop.anio or fecha.month != prop.mes:
        raise ValueError('La fecha tiene que estar dentro del mes de la certificación.')
    obra_id = prop.obra_id
    existente = next(
        (
            ln for ln in (prop.lineas or [])
            if ln.user_id == uid and ln.obra_id == obra_id and ln.fecha == fecha
        ),
        None,
    )
    if existente:
        raise ValueError('Ese trabajador ya tiene una fila ese día.')

    company = company or Company.query.get(prop.company_id)
    obra = obra or Obra.query.get(obra_id)
    # Sin Odoo: tarifa de obra/empresa o la de otra fila del mismo trabajador.
    precio = _precio_rapido_sin_odoo(company, obra, user=user, prop=prop)
    horas_q = cuantizar(horas) if horas not in (None, '') else None
    ln = CertificacionLinea(
        propuesta_id=prop.id,
        user_id=uid,
        obra_id=obra_id,
        fecha=fecha,
        horas=horas_q,
        precio_hora=precio if precio is not None else Decimal('0.00'),
        hora_inicio=None,
        hora_fin=None,
        origen_horas='manual_anadido',
        estado_fichaje=None,
        solape=False,
    )
    db.session.add(ln)
    prop.lineas.append(ln)
    db.session.flush()
    return ln


def _precio_rapido_sin_odoo(
    company: Company | None,
    obra: Obra | None,
    *,
    user: User | None = None,
    prop: CertificacionPropuesta | None = None,
) -> Decimal:
    """€/h local (obra > empresa > filas ya en la propuesta). No llama a Odoo."""
    propio = precio_obra(obra)
    if propio is not None:
        return propio
    if company is not None and company.precio_hora is not None:
        return cuantizar(company.precio_hora) or Decimal('0.00')
    if prop and user:
        for ln in prop.lineas or []:
            if ln.user_id == user.id and ln.precio_hora is not None and ln.precio_hora > 0:
                return cuantizar(ln.precio_hora) or Decimal('0.00')
    if prop:
        for ln in prop.lineas or []:
            if ln.precio_hora is not None and ln.precio_hora > 0:
                return cuantizar(ln.precio_hora) or Decimal('0.00')
    return Decimal('0.00')


def marcar_sin_fichaje_grupos(grupos: list[dict] | None) -> list[dict]:
    """Marca trabajador/día con filas ``manual_anadido`` (asterisco en UI SaaS)."""
    for g in grupos or []:
        g_sin = False
        for f in g.get('fechas') or []:
            f_sin = False
            for item in f.get('lineas') or []:
                ln = item.get('linea') if isinstance(item, dict) else None
                if ln is not None and getattr(ln, 'origen_horas', None) == 'manual_anadido':
                    f_sin = True
                    break
            f['sin_fichaje'] = f_sin
            if f_sin:
                g_sin = True
        g['sin_fichaje'] = g_sin
    return grupos or []


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
    # Tras un rechazo la carta vive en el historial; el borrador vivo es solo borrador.
    propia = by.get(propia_dir)
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


def mapa_fichaje_plataforma(
    company_id: int, anio: int, mes: int, obra_id: int,
) -> dict:
    """Clave (user_id, obra_id, fecha) → fila de ``_esqueleto`` (fichaje real)."""
    return {
        (f['user_id'], f['obra_id'], f['fecha']): f
        for f in _esqueleto(company_id, anio, mes, obra_id=obra_id)
    }


def enriquecer_grupos_plataforma(
    grupos: list[dict],
    mapa_plat: dict,
    *,
    precio_fallback=None,
) -> list[dict]:
    """Añade plat_horas / plat_importe (fichaje real) en línea, día y trabajador.

    Solo para la oficina SaaS: la subcontrata no ve el fichaje de plataforma.
    El importe usa el €/h de la línea (o el fallback del contrato).
    """
    precio_fb = cuantizar(precio_fallback) if precio_fallback is not None else None
    for obra in grupos or []:
        h_obra = Decimal('0.00')
        i_obra = Decimal('0.00')
        for fecha in obra.get('fechas') or []:
            h_f = Decimal('0.00')
            i_f = Decimal('0.00')
            for item in fecha.get('lineas') or []:
                ln = item.get('linea')
                if not ln:
                    item['plat_horas'] = None
                    item['plat_importe'] = None
                    continue
                ref = mapa_plat.get((ln.user_id, ln.obra_id, ln.fecha))
                if not ref or ref.get('horas') is None:
                    item['plat_horas'] = None
                    item['plat_importe'] = None
                    continue
                h = cuantizar(ref['horas']) or Decimal('0.00')
                precio = ln.precio_hora if ln.precio_hora is not None else precio_fb
                imp = importe_linea(h, precio) or Decimal('0.00')
                item['plat_horas'] = h
                item['plat_importe'] = imp
                h_f += h
                i_f += imp
            fecha['plat_horas'] = cuantizar(h_f) or Decimal('0.00')
            fecha['plat_importe'] = cuantizar(i_f) or Decimal('0.00')
            # Vista por fecha: personas anidadas bajo el día.
            for pers in fecha.get('personas') or []:
                hp = Decimal('0.00')
                ip = Decimal('0.00')
                for item in pers.get('lineas') or []:
                    if item.get('plat_horas') is not None:
                        hp += item['plat_horas'] or Decimal('0.00')
                    if item.get('plat_importe') is not None:
                        ip += item['plat_importe'] or Decimal('0.00')
                pers['plat_horas'] = cuantizar(hp) or Decimal('0.00')
                pers['plat_importe'] = cuantizar(ip) or Decimal('0.00')
            h_obra += h_f
            i_obra += i_f
        obra['plat_horas'] = cuantizar(h_obra) or Decimal('0.00')
        obra['plat_importe'] = cuantizar(i_obra) or Decimal('0.00')
    return grupos


def totales_plataforma_grupos(grupos: list[dict] | None) -> dict:
    th = Decimal('0.00')
    ti = Decimal('0.00')
    for obra in grupos or []:
        th += obra.get('plat_horas') or Decimal('0.00')
        ti += obra.get('plat_importe') or Decimal('0.00')
    return {
        'horas': cuantizar(th) or Decimal('0.00'),
        'importe': cuantizar(ti) or Decimal('0.00'),
    }


def delta_vs_plataforma(
    *,
    propuesto_horas,
    propuesto_importe,
    plataforma_horas,
    plataforma_importe,
) -> dict | None:
    """Desviación de una propuesta (p. ej. subcontrata) frente al fichaje real."""
    ph = cuantizar(propuesto_horas) or Decimal('0.00')
    pi = cuantizar(propuesto_importe) or Decimal('0.00')
    rh = cuantizar(plataforma_horas) or Decimal('0.00')
    ri = cuantizar(plataforma_importe) or Decimal('0.00')
    if rh == 0 and ri == 0 and ph == 0 and pi == 0:
        return None
    dh = cuantizar(ph - rh) or Decimal('0.00')
    di = cuantizar(pi - ri) or Decimal('0.00')
    pct_h = None
    pct_i = None
    if rh != 0:
        pct_h = cuantizar((dh / rh) * Decimal('100')) or Decimal('0.00')
    if ri != 0:
        pct_i = cuantizar((di / ri) * Decimal('100')) or Decimal('0.00')
    return {
        'horas_propuesto': ph,
        'importe_propuesto': pi,
        'horas_plataforma': rh,
        'importe_plataforma': ri,
        'delta_horas': dh,
        'delta_importe': di,
        'pct_horas': pct_h,
        'pct_importe': pct_i,
    }


def frase_delta_plataforma(
    delta: dict | None,
    *,
    etiqueta: str = 'propuesta',
    nombre_empresa: str | None = None,
) -> str | None:
    """Frase legible desde vista SaaS (Soltec).

    etiqueta:
      - su_propuesta → carta de la subcontrata en mesa
      - aceptada     → ya cerrada (no «vas a enviar»)
      - enviada      → ya mandada, esperando respuesta
      - propuesta    → borrador propio
    """
    if not delta:
        return None
    from app.services.i18n_service import translate

    if etiqueta == 'su_propuesta':
        nombre = (nombre_empresa or '').strip()
        sujeto = (
            translate('La propuesta que envía {empresa}', empresa=nombre)
            if nombre
            else translate('La propuesta que envían')
        )
    elif etiqueta == 'aceptada':
        sujeto = translate('La propuesta aceptada')
    elif etiqueta == 'enviada':
        sujeto = translate('La propuesta enviada')
    else:
        sujeto = translate('La propuesta que vas a enviar')
    pct = delta.get('pct_importe')
    if pct is not None:
        pct_f = float(pct)
        abs_pct = abs(pct_f)
        # Evitar decimales absurdos en la frase
        abs_txt = (
            f'{abs_pct:.0f}' if abs_pct >= 10 or abs_pct == int(abs_pct)
            else f'{abs_pct:.1f}'.rstrip('0').rstrip('.')
        )
        if pct_f > 0.05:
            return translate(
                '{sujeto} es un {pct}% más cara que el fichaje (desfavorable).',
                sujeto=sujeto, pct=abs_txt,
            )
        if pct_f < -0.05:
            return translate(
                '{sujeto} es un {pct}% más barata que el fichaje (favorable).',
                sujeto=sujeto, pct=abs_txt,
            )
        return translate(
            '{sujeto} cuadra exacto con el fichaje de la plataforma.',
            sujeto=sujeto,
        )
    pct_h = delta.get('pct_horas')
    if pct_h is not None:
        pct_f = float(pct_h)
        abs_pct = abs(pct_f)
        abs_txt = (
            f'{abs_pct:.0f}' if abs_pct >= 10 or abs_pct == int(abs_pct)
            else f'{abs_pct:.1f}'.rstrip('0').rstrip('.')
        )
        if pct_f > 0.05:
            return translate(
                '{sujeto} tiene un {pct}% más de horas que el fichaje (desfavorable).',
                sujeto=sujeto, pct=abs_txt,
            )
        if pct_f < -0.05:
            return translate(
                '{sujeto} tiene un {pct}% menos de horas que el fichaje (favorable).',
                sujeto=sujeto, pct=abs_txt,
            )
        return translate(
            '{sujeto} cuadra exacto con el fichaje de la plataforma.',
            sujeto=sujeto,
        )
    return None


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


def _ym_range(desde: date, hasta: date) -> set[tuple[int, int]]:
    """Meses calendario (anio, mes) entre dos fechas inclusive."""
    if desde > hasta:
        desde, hasta = hasta, desde
    out: set[tuple[int, int]] = set()
    y, m = desde.year, desde.month
    y1, m1 = hasta.year, hasta.month
    while (y, m) <= (y1, m1):
        out.add((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _meses_contrato_asistencia_obra(
    company: Company | None,
    obra: Obra | None,
    *,
    hasta: date,
) -> set[tuple[int, int]]:
    """Meses cubiertos por algún contrato de asistencia empresa+obra (1 RPC)."""
    if not company or not obra:
        return set()
    partner_id = _ext_odoo_id(company)
    project_id = _ext_odoo_id(obra)
    if not partner_id or not project_id:
        return set()
    try:
        from app.sync.dispatcher import get_sync_adapter
        adapter = get_sync_adapter()
        lister = getattr(adapter, 'list_attendance_contracts', None)
        rows = lister(partner_id, project_id) if callable(lister) else []
    except Exception:
        rows = []
    meses: set[tuple[int, int]] = set()
    for row in rows or []:
        d0 = _parse_fecha_contrato(row.get('date_start'))
        if not d0:
            continue
        d1 = _parse_fecha_contrato(row.get('date_end')) or hasta
        if d1 < d0:
            continue
        # No proyectar indefinidamente: hasta el tope pedido (mes abierto + adelante).
        if d1 > hasta:
            d1 = hasta
        meses |= _ym_range(d0, d1)
    return meses


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
    """Meses de la obra: con contrato de asistencia, fichaje/propuesta, o el mes abierto."""
    propia_dir = DIR_SUB if vista_subcontrata else DIR_EMP
    props = CertificacionPropuesta.query.filter_by(
        company_id=company_id, obra_id=obra_id,
    ).all()
    props_by_ym: dict[tuple[int, int], list[CertificacionPropuesta]] = defaultdict(list)
    for p in props:
        props_by_ym[(p.anio, p.mes)].append(p)

    company = Company.query.get(int(company_id))
    obra = Obra.query.get(int(obra_id))
    tope_a, tope_m = _shift_ym(anio_ref, mes_ref, meses_adelante)
    tope = date(tope_a, tope_m, 1)
    # Último día del mes tope.
    _, tope_fin = _mes_rango(tope_a, tope_m)
    meses_contrato = _meses_contrato_asistencia_obra(company, obra, hasta=tope_fin)

    usuarios = [
        u.id for u in User.query.filter(
            User.company_id == company_id,
            User.is_deleted.is_(False),
        ).all()
    ]
    fichaje_ym: set[tuple[int, int]] = set()
    if usuarios:
        # Ventana amplia: desde el contrato más antiguo o meses_atras.
        if meses_contrato:
            min_c = min(meses_contrato)
            inicio_a, inicio_m = min_c
        else:
            inicio_a, inicio_m = _shift_ym(anio_ref, mes_ref, -meses_atras)
        inicio = date(inicio_a, inicio_m, 1)
        fa, fm = _shift_ym(tope_a, tope_m, 1)
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

    # Contrato + fichaje + propuesta con señal + mes que estás viendo.
    candidatos: set[tuple[int, int]] = set(meses_contrato) | set(fichaje_ym)
    candidatos.add((anio_ref, mes_ref))
    for ym, rows in props_by_ym.items():
        if any(_propuesta_tiene_senal(p) for p in rows):
            candidatos.add(ym)

    # No listar indefinido hacia el futuro: corta en mes_ref + adelante.
    candidatos = {
        ym for ym in candidatos
        if ym <= (tope_a, tope_m)
    }

    out = []
    for anio, mes in sorted(candidatos, reverse=True):
        rows = props_by_ym.get((anio, mes), [])
        tiene_fichaje = (anio, mes) in fichaje_ym
        tiene_contrato = (anio, mes) in meses_contrato
        es_actual = (anio, mes) == (anio_ref, mes_ref)
        if (
            not es_actual
            and not tiene_fichaje
            and not tiene_contrato
            and not any(_propuesta_tiene_senal(p) for p in rows)
        ):
            continue
        propia = next((r for r in rows if r.direccion == propia_dir), None)
        tot = totales(propia) if propia else {'horas': Decimal('0.00'), 'importe': Decimal('0.00'), 'filas': 0}
        aceptada = next((r for r in rows if r.estado == 'aceptada'), None)
        estado = _estado_desde_par(rows, vista_subcontrata=vista_subcontrata)
        horas = tot['horas']
        # Sin contrato y sin movimiento real → etiqueta clara (p. ej. mes abierto).
        if (
            not tiene_contrato
            and estado in ('borrador', 'sin_movimiento')
            and not any(_propuesta_tiene_senal(p) for p in rows)
            and (horas is None or horas == 0)
        ):
            estado = 'sin_contrato'
            horas = None
        elif (
            tiene_contrato
            and estado in ('borrador', 'sin_movimiento')
            and not any(_propuesta_tiene_senal(p) for p in rows)
            and (horas is None or horas == 0)
        ):
            # Con contrato pero sin horas aún: «—», no «0 h».
            horas = None
        out.append({
            'anio': anio,
            'mes': mes,
            'estado': estado,
            'horas': horas,
            'importe': tot['importe'] if estado != 'sin_contrato' else None,
            'aceptada_at': aceptada.aceptada_at if aceptada else None,
            'actual': es_actual,
            'requiere_accion': estado in ('recibida', 'rechazada'),
            'tiene_contrato': tiene_contrato,
        })
    return out


def _nombre_oficina_certificacion(ofi_row: Company | None = None) -> str:
    """Nombre visible del lado SaaS: marca del tenant, no «Empresa principal»."""
    from app.services.tenant_branding_service import get_organization_display_name

    marca = (get_organization_display_name() or '').strip()
    ficha = ((ofi_row.nombre if ofi_row else None) or '').strip()
    genericos = {
        'empresa principal',
        'empresa interna',
        'empresa',
        'oficina',
        'main company',
        'entreprise principale',
    }
    if not ficha:
        return marca or 'Oficina'
    low = ficha.lower()
    if low in genericos:
        return marca or ficha
    for pref in ('empresa principal', 'empresa interna', 'main company'):
        if low.startswith(pref):
            resto = ficha[len(pref):].lstrip(' ,·-–:')
            return resto or marca or ficha
    return ficha


def _nombres_certificacion(company: Company, *, vista_subcontrata: bool) -> tuple[str, str, str, str]:
    """(propia, ajena, subcontrata, oficina) según quién mira."""
    from app.services.contratacion_service import empresa_interna

    sub = ((company.nombre if company else None) or '').strip() or 'Subcontrata'
    ofi = _nombre_oficina_certificacion(empresa_interna())
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

    # Rechazos: se leen del historial de rondas (ya no viven en el borrador).
    if not bloqueado and propia and ajena:
        for r in reversed(_rondas_periodo(propia.company_id, propia.obra_id, propia.anio, propia.mes)):
            if r.resultado != 'rechazada':
                continue
            if r.direccion != propia.direccion:
                continue
            items.append({
                'tipo': 'rechazo',
                'cuando': r.respondida_at or r.enviada_at,
                'actor': ajena_n,
                'origen': propia_n,
                'detalle': (r.comentario_rechazo or '').strip(),
            })
            break

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


def propuestas_entrantes_oficina(user=None) -> int:
    """Propuestas de subcontrata enviadas pendientes de revisar en oficina."""
    q = CertificacionPropuesta.query.filter_by(direccion=DIR_SUB, estado='enviada')
    if user is not None:
        from app.services.panel_scope_service import certificacion_obra_ids
        allowed = certificacion_obra_ids(user)
        if allowed is not None:
            if not allowed:
                return 0
            q = q.filter(CertificacionPropuesta.obra_id.in_(allowed))
    return q.count()


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

    from app.services.certificacion_avisos_service import pares_pendientes_mes
    pares_aviso = pares_pendientes_mes(anio=anio, mes=mes, user=user)
    for cid, oid in pares_aviso:
        if allowed is not None and oid not in allowed:
            continue
        company_ids.add(cid)

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
        # Incluir obras con aviso aunque no salgan en obras_ids_certificacion.
        oids = set(oids) | {oid for (c, oid) in pares_aviso if c == cid}
        if allowed is not None:
            oids = {oid for oid in oids if oid in allowed}
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
        avisos_obra = [pares_aviso[(cid, oid)] for oid in oids if (cid, oid) in pares_aviso]
        motivo_aviso = None
        if 'recibida' in avisos_obra:
            motivo_aviso = 'recibida'
        elif 'requerida' in avisos_obra:
            motivo_aviso = 'requerida'
        out.append({
            'company': company,
            'estado': estado,
            'requiere_accion': (
                cont.get('recibida', 0) > 0
                or cont.get('rechazada', 0) > 0
                or bool(avisos_obra)
            ),
            'aviso_pendiente': bool(avisos_obra),
            'motivo_aviso': motivo_aviso,
            'n_aviso': len(avisos_obra),
            'n_obras': len(oids),
            'n_recibida': cont.get('recibida', 0),
            'n_rechazada': cont.get('rechazada', 0),
            'n_enviada': cont.get('enviada', 0),
            'n_borrador': cont.get('borrador', 0),
            'n_aceptada': cont.get('aceptada', 0),
            'n_sin_movimiento': cont.get('sin_movimiento', 0),
            'tiene_recibida': cont.get('recibida', 0) > 0,
            'tiene_rechazada': cont.get('rechazada', 0) > 0,
            'tiene_requerida': 'requerida' in avisos_obra,
        })
    out.sort(key=lambda row: (
        0 if row['estado'] == 'recibida' else (1 if row['estado'] == 'rechazada' else (2 if row.get('aviso_pendiente') else 3)),
        -(row.get('n_aviso') or 0),
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

    from app.services.certificacion_avisos_service import pares_pendientes_mes
    pares_aviso = pares_pendientes_mes(
        anio=anio, mes=mes, company_id=company_id, user=user,
    )

    oids = set(obras_ids_certificacion(
        company_id, anio, mes,
        obra_ids=None if allowed is None else allowed,
    ))
    oids |= {oid for (cid, oid) in pares_aviso if cid == company_id}
    if allowed is not None:
        oids = {oid for oid in oids if oid in allowed}
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
    props = CertificacionPropuesta.query.filter(
        CertificacionPropuesta.company_id == company_id,
        CertificacionPropuesta.anio == anio,
        CertificacionPropuesta.mes == mes,
        CertificacionPropuesta.obra_id.in_(oids),
    ).all()
    por_obra: dict[int, list] = defaultdict(list)
    for p in props:
        por_obra[p.obra_id].append(p)

    out = []
    for oid in oids:
        obra = obras.get(oid)
        if not obra:
            continue
        rows = por_obra.get(oid) or []
        propia = next((r for r in rows if r.direccion == DIR_EMP), None)
        estado = _estado_desde_par(rows, vista_subcontrata=False)
        horas = cuantizar(horas_obra.get(oid, Decimal('0.00'))) or Decimal('0.00')
        motivo = ''
        if propia and propia.estado == 'borrador':
            motivo = (propia.comentario_rechazo or '').strip()
        motivo_aviso = pares_aviso.get((company_id, oid))
        out.append({
            'obra': obra,
            'estado': estado,
            'horas': horas,
            'requiere_accion': (
                estado in ('recibida', 'rechazada')
                or motivo_aviso in ('recibida', 'requerida')
            ),
            'aviso_pendiente': bool(motivo_aviso),
            'motivo_aviso': motivo_aviso,
            'contrato': None,
            'comentario_rechazo': motivo,
        })
    out.sort(key=lambda row: (
        0 if row['estado'] == 'recibida' else (
            1 if row['estado'] == 'rechazada' else (
                2 if row.get('motivo_aviso') == 'requerida' else (
                    3 if row.get('aviso_pendiente') else 4
                )
            )
        ),
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
    """Lista de obras del mes para el portal subcontrata.

    Las horas mostradas son solo las de su propuesta (DIR_SUB), nunca el fichaje
    de la plataforma. No sincroniza ni llama a Odoo: eso ocurre al abrir la obra.
    """
    from app.services.certificacion_avisos_service import pares_pendientes_mes

    pares_aviso = pares_pendientes_mes(
        anio=anio, mes=mes, company_id=company.id, vista_subcontrata=True,
    )
    oids = set(obras_ids_certificacion(company.id, anio, mes))
    oids |= {oid for (cid, oid) in pares_aviso if cid == company.id}
    if not oids:
        return []
    obras = {o.id: o for o in Obra.query.filter(Obra.id.in_(oids)).all()}
    props = CertificacionPropuesta.query.filter(
        CertificacionPropuesta.company_id == company.id,
        CertificacionPropuesta.anio == anio,
        CertificacionPropuesta.mes == mes,
        CertificacionPropuesta.obra_id.in_(oids),
    ).all()
    por_obra: dict[int, list] = defaultdict(list)
    for p in props:
        por_obra[p.obra_id].append(p)

    out = []
    for oid in oids:
        obra = obras.get(oid)
        if not obra:
            continue
        rows = por_obra.get(oid) or []
        propia = next((r for r in rows if r.direccion == DIR_SUB), None)
        tot = totales(propia) if propia else {
            'horas': Decimal('0.00'), 'importe': Decimal('0.00'), 'filas': 0,
        }
        estado = _estado_desde_par(rows, vista_subcontrata=True)
        motivo = ''
        if propia and propia.estado == 'borrador':
            motivo = (propia.comentario_rechazo or '').strip()
        motivo_aviso = pares_aviso.get((company.id, oid))
        out.append({
            'obra': obra,
            'estado': estado,
            'horas': tot['horas'],
            'requiere_accion': (
                estado in ('recibida', 'rechazada') or motivo_aviso in ('recibida', 'requerida')
            ),
            'aviso_pendiente': bool(motivo_aviso),
            'motivo_aviso': motivo_aviso,
            'contrato': None,
            'comentario_rechazo': motivo,
        })
    out.sort(key=lambda row: (
        0 if row['estado'] == 'recibida' else (
            1 if row['estado'] == 'rechazada' else (2 if row.get('aviso_pendiente') else 3)
        ),
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
    """Listado de obras del alcance con volumen + estado (por revisar)."""
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

    # Incluir obras con propuesta pendiente aunque el filtro de fechas no pille fichaje.
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
        if allowed is not None and prop.obra_id not in allowed:
            continue
        bucket = por_obra.setdefault(prop.obra_id, {
            'horas': Decimal('0.00'),
            'companies': set(),
        })
        bucket['companies'].add(prop.company_id)

    props_mes = CertificacionPropuesta.query.filter_by(anio=anio, mes=mes).all()
    for prop in props_mes:
        if allowed is not None and prop.obra_id not in allowed:
            continue
        bucket = por_obra.setdefault(prop.obra_id, {
            'horas': Decimal('0.00'),
            'companies': set(),
        })
        bucket['companies'].add(prop.company_id)

    from app.services.certificacion_avisos_service import pares_pendientes_mes
    pares_aviso = pares_pendientes_mes(anio=anio, mes=mes, user=user)
    for cid, oid in pares_aviso:
        if allowed is not None and oid not in allowed:
            continue
        bucket = por_obra.setdefault(oid, {
            'horas': Decimal('0.00'),
            'companies': set(),
        })
        bucket['companies'].add(cid)

    if not por_obra:
        return []

    obras = {o.id: o for o in Obra.query.filter(Obra.id.in_(list(por_obra))).all()}
    props_por_obra: dict[int, list] = defaultdict(list)
    for prop in props_mes:
        if prop.obra_id in por_obra:
            props_por_obra[prop.obra_id].append(prop)

    out = []
    for oid, data in por_obra.items():
        obra = obras.get(oid)
        if not obra:
            continue
        by_company: dict[int, list] = defaultdict(list)
        for p in props_por_obra.get(oid, []):
            by_company[p.company_id].append(p)
        for cid in data['companies']:
            by_company.setdefault(cid, [])

        cont = {
            'aceptada': 0, 'recibida': 0, 'enviada': 0, 'rechazada': 0,
            'borrador': 0, 'sin_movimiento': 0,
        }
        for rows in by_company.values():
            est = _estado_desde_par(rows, vista_subcontrata=False)
            cont[est] = cont.get(est, 0) + 1
        estado = 'sin_movimiento'
        for key in ('recibida', 'rechazada', 'enviada', 'borrador', 'aceptada'):
            if cont.get(key, 0):
                estado = key
                break
        avisos_emp = [
            pares_aviso[(cid, oid)]
            for cid in by_company
            if (cid, oid) in pares_aviso
        ]
        motivo_aviso = None
        if 'recibida' in avisos_emp:
            motivo_aviso = 'recibida'
        elif 'requerida' in avisos_emp:
            motivo_aviso = 'requerida'
        horas = cuantizar(data['horas']) or Decimal('0.00')
        out.append({
            'obra': obra,
            'horas': horas,
            'n_empresas': len(by_company) or len(data['companies']),
            'importe': None,  # se calcula en detalle (precios por empresa)
            'estado': estado,
            'requiere_accion': (
                cont.get('recibida', 0) > 0
                or cont.get('rechazada', 0) > 0
                or bool(avisos_emp)
            ),
            'aviso_pendiente': bool(avisos_emp),
            'motivo_aviso': motivo_aviso,
            'n_aviso': len(avisos_emp),
            'n_recibida': cont.get('recibida', 0),
            'n_rechazada': cont.get('rechazada', 0),
            'n_enviada': cont.get('enviada', 0),
            'n_borrador': cont.get('borrador', 0),
            'n_aceptada': cont.get('aceptada', 0),
            'n_sin_movimiento': cont.get('sin_movimiento', 0),
            'tiene_recibida': cont.get('recibida', 0) > 0,
            'tiene_rechazada': cont.get('rechazada', 0) > 0,
            'tiene_requerida': 'requerida' in avisos_emp,
        })
    out.sort(key=lambda row: (
        0 if row['estado'] == 'recibida' else (1 if row['estado'] == 'rechazada' else (2 if row.get('aviso_pendiente') else 3)),
        -(row.get('n_aviso') or 0),
        -(row['horas'] or 0),
        (row['obra'].nombre or '').lower(),
    ))
    return out


def _precio_hub_local(
    company: Company | None,
    obra: Obra | None,
    *,
    precio_linea_company: dict[int, Decimal] | None = None,
) -> Decimal:
    """€/h del hub sin tocar Odoo: override obra > override empresa > línea ya guardada > 0."""
    propio = precio_obra(obra)
    if propio is not None:
        return propio
    if company is not None and company.precio_hora is not None:
        return cuantizar(company.precio_hora) or Decimal('0.00')
    if company is not None and precio_linea_company:
        got = precio_linea_company.get(company.id)
        if got is not None:
            return got
    return Decimal('0.00')


def detalle_certificacion_obra(
    user,
    obra_id: int,
    *,
    anio: int,
    mes: int,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict | None:
    """Detalle obra: fichajes + propuestas locales. Cero sync / cero Odoo.

    La tarifa de contrato y la sync viven en «Gestionar» (empresa+obra).
    """
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
    props_por_company: dict[int, list] = defaultdict(list)
    for p in props_obra:
        props_por_company[p.company_id].append(p)
    estados_por_company = {
        cid: _estado_desde_par(rows, vista_subcontrata=False)
        for cid, rows in props_por_company.items()
    }

    # Precio ya persistido en líneas (una query), sin contrato Odoo.
    prop_ids = [p.id for p in props_obra]
    precio_linea_company: dict[int, Decimal] = {}
    if prop_ids:
        for company_id, precio in (
            db.session.query(CertificacionPropuesta.company_id, CertificacionLinea.precio_hora)
            .join(CertificacionLinea, CertificacionLinea.propuesta_id == CertificacionPropuesta.id)
            .filter(
                CertificacionPropuesta.id.in_(prop_ids),
                CertificacionLinea.precio_hora.isnot(None),
            )
            .all()
        ):
            if company_id not in precio_linea_company and precio is not None:
                got = cuantizar(precio)
                if got is not None:
                    precio_linea_company[company_id] = got

    from app.services.certificacion_avisos_service import pares_pendientes_mes
    pares_aviso = pares_pendientes_mes(
        anio=anio, mes=mes, obra_id=obra_id, user=user,
    )

    company_ids = {f['company_id'] for f in filas} | set(props_por_company)
    company_ids |= {cid for (cid, oid) in pares_aviso if oid == obra_id}
    user_ids = {f['user_id'] for f in filas}
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    companies = {
        c.id: c for c in Company.query.filter(Company.id.in_(list(company_ids))).all()
    } if company_ids else {}

    precios_company = {
        cid: _precio_hub_local(companies.get(cid), obra, precio_linea_company=precio_linea_company)
        for cid in company_ids
    }

    dias: dict[date, dict] = {}
    por_empresa: dict[int, dict] = {}
    total_horas = Decimal('0.00')
    total_importe = Decimal('0.00')
    for f in filas:
        company = companies.get(f['company_id'])
        persona = users.get(f['user_id'])
        if not company or not persona:
            continue
        precio = precios_company.get(company.id) or Decimal('0.00')
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
            'personas': {},
            'contrato': None,
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
        pers = emp['personas'].setdefault(persona.id, {
            'user': persona,
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
            'fechas': {},
        })
        pers['horas'] += f['horas']
        pers['importe'] += importe
        pf = pers['fechas'].setdefault(f['fecha'], {
            'fecha': f['fecha'],
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
            'precio': precio,
        })
        pf['horas'] += f['horas']
        pf['importe'] += importe

    for cid in company_ids:
        company = companies.get(cid)
        if not company or cid in por_empresa:
            continue
        por_empresa[cid] = {
            'company': company,
            'horas': Decimal('0.00'),
            'importe': Decimal('0.00'),
            'precio': precios_company.get(cid) or Decimal('0.00'),
            'fechas': {},
            'personas': {},
            'contrato': None,
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
            emp['estado'] = estados_por_company.get(emp['company'].id, 'sin_movimiento')
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
        emp['estado'] = estados_por_company.get(cid, 'sin_movimiento')
        motivo_aviso = pares_aviso.get((cid, obra_id))
        emp['requiere_accion'] = (
            emp['estado'] in ('recibida', 'rechazada')
            or motivo_aviso in ('recibida', 'requerida')
        )
        emp['aviso_pendiente'] = bool(motivo_aviso)
        emp['motivo_aviso'] = motivo_aviso
        emp['contrato'] = None
        fechas_emp = []
        for fecha in sorted(emp['fechas'].keys(), reverse=True):
            fb = emp['fechas'][fecha]
            fb['horas'] = cuantizar(fb['horas']) or Decimal('0.00')
            fb['importe'] = cuantizar(fb['importe']) or Decimal('0.00')
            fb['personas'].sort(key=lambda p: (-(p['horas'] or 0), (p['user'].name or '').lower()))
            fechas_emp.append(fb)
        emp['fechas'] = fechas_emp
        personas_emp = []
        for pers in (emp.get('personas') or {}).values():
            pers['horas'] = cuantizar(pers['horas']) or Decimal('0.00')
            pers['importe'] = cuantizar(pers['importe']) or Decimal('0.00')
            fechas_p = []
            for fecha in sorted(pers['fechas'].keys(), reverse=True):
                pf = pers['fechas'][fecha]
                pf['horas'] = cuantizar(pf['horas']) or Decimal('0.00')
                pf['importe'] = cuantizar(pf['importe']) or Decimal('0.00')
                fechas_p.append(pf)
            pers['fechas'] = fechas_p
            personas_emp.append(pers)
        personas_emp.sort(key=lambda p: (
            -(p['horas'] or 0),
            (p['user'].name or '').lower() if p.get('user') else '',
        ))
        emp['personas'] = personas_emp
        empresas_out.append(emp)
    empresas_out.sort(key=lambda e: (
        0 if e['estado'] == 'recibida' else (1 if e['estado'] == 'rechazada' else (2 if e.get('aviso_pendiente') else 3)),
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


def precio_mostrado_obra(obra: Obra, *, company: Company | None = None) -> Decimal:
    """Valor a mostrar en el hub de obra (override o contrato base)."""
    propio = precio_obra(obra)
    if propio is not None:
        return propio
    if company is not None:
        return precio_para(company, obra)
    return Decimal('0.00')


def reaplicar_precios_empresa_borrador(company: Company, anio: int, mes: int) -> int:
    """Tras quitar override de empresa, reaplica contrato (u override de obra) a borradores."""
    props = CertificacionPropuesta.query.filter_by(
        company_id=company.id, anio=anio, mes=mes, estado='borrador',
    ).all()
    obras = {
        o.id: o for o in Obra.query.filter(
            Obra.id.in_({p.obra_id for p in props if p.obra_id} or {-1}),
        ).all()
    }
    user_ids = {ln.user_id for p in props for ln in p.lineas}
    users = {
        u.id: u for u in User.query.filter(User.id.in_(user_ids or {-1})).all()
    }
    cache: dict = {}
    n = 0
    for prop in props:
        obra = obras.get(prop.obra_id)
        for ln in prop.lineas:
            ln.precio_hora = precio_para(
                company, obra,
                user=users.get(ln.user_id),
                fecha=ln.fecha,
                cache=cache,
            )
            n += 1
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
        # Cabecera con ?page=; no hace falta esperar 300 ms (ralentizaba cada descarga).
        opts['javascript-delay'] = '80'
    return opts


def _cert_pdf_cache_dir(schema_name: str | None) -> str:
    import os
    from flask import current_app

    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in (schema_name or 'default'))
    base = os.path.abspath(os.path.join(
        current_app.root_path, '..', 'uploads', 'certificacion_pdf', safe,
    ))
    os.makedirs(base, exist_ok=True)
    return base


def _cert_pdf_fingerprint(prop: CertificacionPropuesta) -> str:
    """Identidad del contenido para invalidar la caché al cambiar estado/líneas."""
    lineas = list(prop.lineas or [])
    horas = sum(float(ln.horas or 0) for ln in lineas)
    aceptar = prop.aceptada_at.isoformat() if prop.aceptada_at else ''
    quien = prop.respondida_por_id or ''
    return f'{prop.estado}_{aceptar}_{quien}_{len(lineas)}_{horas:.2f}'


def _cert_pdf_cache_path(prop: CertificacionPropuesta, schema_name: str | None) -> str | None:
    """Caché en disco solo para propuestas cerradas (contenido estable)."""
    import os

    if (prop.estado or '') not in ('aceptada', 'cerrada'):
        return None
    return os.path.join(
        _cert_pdf_cache_dir(schema_name),
        f'prop_{prop.id}_{_cert_pdf_fingerprint(prop)}.pdf',
    )


def cargar_propuesta_para_pdf(propuesta_id: int) -> CertificacionPropuesta | None:
    """Carga con joins para no disparar N+1 al armar el PDF."""
    from sqlalchemy.orm import joinedload

    return (
        CertificacionPropuesta.query
        .options(
            joinedload(CertificacionPropuesta.company),
            joinedload(CertificacionPropuesta.obra),
            joinedload(CertificacionPropuesta.lineas).joinedload(CertificacionLinea.user),
            joinedload(CertificacionPropuesta.lineas).joinedload(CertificacionLinea.obra),
        )
        .filter_by(id=propuesta_id)
        .first()
    )


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
    grupos: list[dict] | None = None,
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
    if grupos is None:
        grupos = agrupar(prop)
    tot = totales_grupos(grupos)
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

    _, _, sub_n, ofi_n = _nombres_certificacion(company, vista_subcontrata=False)
    rondas = _rondas_periodo(prop.company_id, prop.obra_id, prop.anio, prop.mes)
    etiquetas = etiquetas_rondas(rondas)
    ronda_pdf = next(
        (r for r in rondas if r.resultado == 'aceptada'),
        None,
    )
    if ronda_pdf is None:
        candidatas = [
            r for r in rondas
            if r.propuesta_id == prop.id or r.direccion == prop.direccion
        ]
        ronda_pdf = candidatas[-1] if candidatas else None
    propuesta_num = etiqueta_ronda(ronda_pdf, etiquetas) if ronda_pdf else ''

    aceptada_por = ''
    aceptada_el = ''
    aceptada_lado = ''
    if (prop.estado or '') in ('aceptada', 'cerrada'):
        actor_id = prop.respondida_por_id
        cuando = prop.aceptada_at
        if ronda_pdf and ronda_pdf.resultado == 'aceptada':
            actor_id = ronda_pdf.respondida_por_id or actor_id
            cuando = ronda_pdf.respondida_at or cuando
        if not cuando and prop.estado == 'cerrada':
            hermana = CertificacionPropuesta.query.filter_by(
                company_id=prop.company_id,
                obra_id=prop.obra_id,
                anio=prop.anio,
                mes=prop.mes,
                direccion=_otra(prop.direccion),
                estado='aceptada',
            ).first()
            if hermana:
                cuando = hermana.aceptada_at
                actor_id = actor_id or hermana.respondida_por_id
        aceptada_por = _nombre_actor(actor_id)
        if cuando:
            aceptada_el = cuando.strftime('%d/%m/%Y %H:%M')
        # Quien acepta es la parte contraria a la propuesta aceptada.
        dir_aceptada = (
            ronda_pdf.direccion if ronda_pdf and ronda_pdf.resultado == 'aceptada'
            else prop.direccion
        )
        aceptada_lado = _nombre_por_direccion(_otra(dir_aceptada), sub_n, ofi_n)

    return {
        'doc_title': f'{translate("Certificación")} · {empresa} · {mes_txt}',
        'empresa': empresa,
        'mes_txt': mes_txt,
        'sentido': sentido,
        'estado_txt': (prop.estado or '').capitalize(),
        'propuesta_num': propuesta_num,
        'aceptada_por': aceptada_por,
        'aceptada_el': aceptada_el,
        'aceptada_lado': aceptada_lado,
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
    grupos = agrupar(prop)
    if overlay_page_count is None:
        # +1 de margen: mejor una marca de agua de más que quedarse corto.
        overlay_page_count = _estimate_cert_pages(grupos) + 1
    ctx = _build_cert_pdf_context(
        prop,
        schema_name=schema_name,
        overlay_page_count=overlay_page_count,
        include_inline_banner=include_inline_banner,
        grupos=grupos,
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
    """Genera el PDF (un solo pase wkhtmltopdf). Aceptadas/cerradas se cachean en disco."""
    import os
    import tempfile

    header_path = None
    try:
        import pdfkit
        from flask import current_app, g

        if schema_name is None:
            tenant = getattr(g, 'current_tenant', None)
            schema_name = getattr(tenant, 'schema_name', None) if tenant else None

        cache_path = _cert_pdf_cache_path(prop, schema_name)
        if cache_path and os.path.isfile(cache_path):
            try:
                with open(cache_path, 'rb') as fh:
                    cached = fh.read()
                if cached.startswith(b'%PDF'):
                    return cached
            except OSError:
                pass

        config = None
        wkhtml = current_app.config.get('WKHTMLTOPDF_CMD') or current_app.config.get('PDFKIT_WKHTMLTOPDF')
        if wkhtml:
            config = pdfkit.configuration(wkhtmltopdf=wkhtml)

        header_html = _render_cert_header_html(prop, schema_name=schema_name)
        fd, header_path = tempfile.mkstemp(suffix='.html', prefix='cert_hdr_')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(header_html)

        opts = _pdfkit_options_cert(header_html_path=header_path)

        # Un solo pase: estimar páginas (marca de agua) evita regenerar el PDF entero.
        final_html = html_propuesta(
            prop,
            schema_name=schema_name,
            overlay_page_count=None,
            include_inline_banner=False,
        )
        pdf_bytes = pdfkit.from_string(
            final_html, False, options=opts, configuration=config,
        )
        if not pdf_bytes or not pdf_bytes.startswith(b'%PDF'):
            return None

        if cache_path:
            try:
                tmp = cache_path + '.tmp'
                with open(tmp, 'wb') as fh:
                    fh.write(pdf_bytes)
                os.replace(tmp, cache_path)
                # Limpia versiones antiguas de la misma propuesta.
                prefix = f'prop_{prop.id}_'
                cache_dir = os.path.dirname(cache_path)
                for name in os.listdir(cache_dir):
                    if name.startswith(prefix) and name != os.path.basename(cache_path):
                        try:
                            os.unlink(os.path.join(cache_dir, name))
                        except OSError:
                            pass
            except OSError:
                pass

        return pdf_bytes
    except Exception:
        try:
            from flask import current_app
            current_app.logger.exception(
                'cert PDF: fallo generando propuesta_id=%s',
                getattr(prop, 'id', None),
            )
        except Exception:
            pass
        return None
    finally:
        if header_path:
            try:
                os.unlink(header_path)
            except OSError:
                pass


_warmup_pdf_inflight: set[tuple] = set()
_warmup_pdf_lock = threading.Lock()


def _warmup_pdf_worker(app, schema_name: str, prop_ids: list[int]) -> None:
    """Hilo: genera y cachea PDFs de propuestas ya aceptadas/cerradas."""
    from sqlalchemy import text
    from app import db, is_safe_schema_name
    from flask import g

    key = (schema_name, tuple(sorted(prop_ids)))
    try:
        with app.app_context():
            if not is_safe_schema_name(schema_name):
                return
            try:
                db.session.execute(text('SET search_path TO public'))
                from app.models import Tenant
                tenant = Tenant.query.filter_by(schema_name=schema_name, is_active=True).first()
                if tenant:
                    g.current_tenant = tenant
                db.session.execute(text(f'SET search_path TO {schema_name}, public'))
                for pid in prop_ids:
                    prop = cargar_propuesta_para_pdf(pid)
                    if not prop or (prop.estado or '') not in ('aceptada', 'cerrada'):
                        continue
                    pdf_propuesta(prop, schema_name=schema_name)
                    app.logger.info(
                        'cert PDF: warmup listo prop_id=%s estado=%s schema=%s',
                        pid, prop.estado, schema_name,
                    )
            except Exception:
                app.logger.exception(
                    'cert PDF: warmup falló schema=%s ids=%s', schema_name, prop_ids,
                )
            finally:
                try:
                    db.session.remove()
                except Exception:
                    pass
    finally:
        with _warmup_pdf_lock:
            _warmup_pdf_inflight.discard(key)


def programar_warmup_pdf_certificacion(
    *prop_ids,
    schema_name: str | None = None,
) -> None:
    """Tras aceptar: precarga el PDF en disco en segundo plano (no bloquea la UI)."""
    from flask import current_app, g, has_app_context

    ids = []
    for raw in prop_ids:
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            continue
        if pid and pid not in ids:
            ids.append(pid)
    if not ids or not has_app_context():
        return
    if schema_name is None:
        tenant = getattr(g, 'current_tenant', None)
        schema_name = getattr(tenant, 'schema_name', None) if tenant else None
    if not schema_name:
        return
    key = (schema_name, tuple(sorted(ids)))
    with _warmup_pdf_lock:
        if key in _warmup_pdf_inflight:
            return
        _warmup_pdf_inflight.add(key)
    app = current_app._get_current_object()
    threading.Thread(
        target=_warmup_pdf_worker,
        args=(app, schema_name, ids),
        daemon=True,
        name=f'cert-pdf-warmup-{ids[0]}',
    ).start()


def ids_propuestas_pdf_cerradas(
    prop: CertificacionPropuesta | None,
) -> list[int]:
    """Id de la aceptada + hermana cerrada (si existe) para warmup."""
    if not prop or not prop.id:
        return []
    ids = [int(prop.id)]
    otra = CertificacionPropuesta.query.filter_by(
        company_id=prop.company_id,
        obra_id=prop.obra_id,
        anio=prop.anio,
        mes=prop.mes,
        direccion=_otra(prop.direccion),
    ).first()
    if otra and otra.id and (otra.estado or '') in ('aceptada', 'cerrada'):
        ids.append(int(otra.id))
    return ids


def aplicar_ronda_a_borrador(
    prop: CertificacionPropuesta,
    ronda: CertificacionRonda,
    *,
    user_id: int | None = None,
) -> int:
    """Copia horas/tramos del snapshot a la propuesta viva (opcionalmente un trabajador).

    Si el snapshot trae días añadidos a mano que el borrador no tiene, los crea.
    """
    if prop.estado != 'borrador':
        raise ValueError('Solo se puede copiar sobre un borrador.')
    if periodo_bloqueado(prop.company_id, prop.anio, prop.mes, prop.obra_id):
        raise ValueError('Esta obra ya está aceptada en el mes.')
    if not ronda or not ronda.lineas_json:
        return 0
    mapa = mapa_lineas_ronda(ronda)
    n = 0

    def _aplicar_a_linea(ln: CertificacionLinea, row: dict) -> None:
        hi = parse_hora(row.get('hora_inicio'))
        hf = parse_hora(row.get('hora_fin'))
        horas = row.get('horas')
        precio = (
            row.get('precio_hora')
            if row.get('precio_hora') not in (None, '')
            else ln.precio_hora
        )
        # Subcontrata: solo totales. No heredar inicio/fin del fichaje de la oficina.
        if prop.direccion == DIR_SUB:
            _escribir_campos_linea(
                ln, hora_inicio=None, hora_fin=None, horas=horas, precio=precio,
            )
            if row.get('origen_horas') == 'manual_anadido':
                ln.origen_horas = 'manual_anadido'
            return
        if hi and hf:
            _escribir_campos_linea(ln, hora_inicio=hi, hora_fin=hf, horas=None, precio=precio)
        else:
            _escribir_campos_linea(ln, hora_inicio=None, hora_fin=None, horas=horas, precio=precio)
        if row.get('origen_horas') == 'manual_anadido':
            ln.origen_horas = 'manual_anadido'

    # Query explícita: la collection lazy puede estar stale tras borrar/recrear filas.
    lineas_vivas = (
        CertificacionLinea.query.filter_by(propuesta_id=prop.id).all()
        if prop.id else list(prop.lineas or [])
    )
    for ln in lineas_vivas:
        if user_id is not None and ln.user_id != int(user_id):
            continue
        row = mapa.get((ln.user_id, ln.obra_id, ln.fecha))
        if not row:
            continue
        _aplicar_a_linea(ln, row)
        n += 1

    existentes = {
        (ln.user_id, ln.obra_id, ln.fecha) for ln in lineas_vivas
    }
    nuevas: list[tuple[CertificacionLinea, dict]] = []
    for key, row in mapa.items():
        uid, oid, fecha_d = key
        if user_id is not None and uid != int(user_id):
            continue
        if key in existentes:
            continue
        if oid != prop.obra_id:
            continue
        precio = row.get('precio_hora')
        ln = CertificacionLinea(
            propuesta_id=prop.id,
            user_id=uid,
            obra_id=oid,
            fecha=fecha_d,
            precio_hora=cuantizar(precio) if precio not in (None, '') else Decimal('0.00'),
            origen_horas='manual_anadido',
            estado_fichaje=None,
            solape=False,
        )
        db.session.add(ln)
        prop.lineas.append(ln)
        nuevas.append((ln, row))
        n += 1
    if nuevas:
        db.session.flush()
        for ln, row in nuevas:
            _aplicar_a_linea(ln, row)
            if row.get('origen_horas') == 'manual_anadido':
                ln.origen_horas = 'manual_anadido'
    return n


def ultima_ronda_propia(prop: CertificacionPropuesta) -> CertificacionRonda | None:
    rondas = [
        r for r in _rondas_periodo(prop.company_id, prop.obra_id, prop.anio, prop.mes)
        if r.resultado != 'retirada' and r.direccion == prop.direccion
    ]
    return rondas[-1] if rondas else None


def restablecer_persona_base(
    prop: CertificacionPropuesta,
    user_id: int,
    *,
    vista_subcontrata: bool,
) -> int:
    """Plataforma: fichaje. Subcontrata: último envío propio."""
    if prop.estado != 'borrador':
        raise ValueError('Solo se puede restablecer un borrador.')
    uid = int(user_id)
    if vista_subcontrata:
        ronda = ultima_ronda_propia(prop)
        if not ronda:
            raise ValueError('No hay un envío tuyo anterior para restablecer.')
        return aplicar_ronda_a_borrador(prop, ronda, user_id=uid)
    if periodo_bloqueado(prop.company_id, prop.anio, prop.mes, prop.obra_id):
        raise ValueError('Esta obra ya está aceptada en el mes.')
    mapa = _esqueleto_mapa(prop.company_id, prop.anio, prop.mes, obra_id=prop.obra_id)
    n = 0
    for ln in prop.lineas:
        if ln.user_id != uid:
            continue
        _aplicar_fichaje_a_linea(ln, mapa.get((ln.user_id, ln.obra_id, ln.fecha)))
        n += 1
    if not n:
        raise ValueError('No hay filas de ese trabajador.')
    return n


def contexto_mesa(
    company: Company,
    obra: Obra,
    anio: int,
    mes: int,
    *,
    propia: CertificacionPropuesta | None,
    ajena: CertificacionPropuesta | None,
    vista_subcontrata: bool,
    ronda_id: int | None = None,
    modo_vista: str = 'persona',
    corr: bool = False,
) -> dict:
    """Datos para la UI de mesa única + baraja de rondas.

    Cuando te toca responder hay dos vistas:
    - recibida: carta ajena en mesa (solo lectura + Aceptar/Rechazar)
    - responder (corr): borrador editable para enviar corrección
    """
    asegurar_rondas_periodo(company.id, obra.id, anio, mes)
    _purgar_retiradas_y_renumerar(company.id, obra.id, anio, mes)
    rondas = list(_rondas_periodo(company.id, obra.id, anio, mes))
    mesa = ronda_en_mesa(company.id, obra.id, anio, mes)
    bloqueado = periodo_bloqueado(company.id, anio, mes, obra.id)
    propia_dir = DIR_SUB if vista_subcontrata else DIR_EMP
    mesa_ajena = mesa if (mesa and mesa.direccion != propia_dir) else None

    _, _, sub_n, ofi_n = _nombres_certificacion(company, vista_subcontrata=vista_subcontrata)

    def _lado(direccion: str) -> str:
        return sub_n if direccion == DIR_SUB else ofi_n

    # Modo preliminar para marcar «misma que actual» en la baraja.
    if bloqueado or (propia and propia.estado == 'aceptada') or (ajena and ajena.estado == 'aceptada'):
        modo_prev = 'cerrada'
    elif propia and propia.estado == 'enviada':
        modo_prev = 'esperando'
    elif mesa_ajena is not None:
        modo_prev = 'responder'
    else:
        modo_prev = 'preparar'

    etiquetas = etiquetas_rondas(rondas)

    def _carta(r: CertificacionRonda) -> dict:
        es_propia = r.direccion == propia_dir
        en_mesa = r.resultado == 'en_mesa'
        # Enviada propia en mesa = misma vista que «Propuesta actual».
        misma = bool(en_mesa and es_propia and modo_prev == 'esperando')
        et = etiquetas.get(int(r.id), str(r.secuencia or ''))
        major = str(et).split('.', 1)[0] if et else str(r.secuencia or '')
        return {
            'id': r.id,
            'secuencia': r.secuencia,
            'etiqueta': et,
            'major': major,
            'direccion': r.direccion,
            'lado': _lado(r.direccion),
            'es_propia': es_propia,
            'resultado': r.resultado,
            'enviada_at': r.enviada_at,
            'horas': r.horas_total,
            'importe': r.importe_total,
            'comentario': (r.comentario_rechazo or '').strip(),
            'en_mesa': en_mesa,
            'misma_que_actual': misma,
            'ronda': r,
        }

    baraja = [_carta(r) for r in rondas]
    mesa_carta_seq = next((c['etiqueta'] for c in baraja if c['en_mesa']), None)

    # Historial agrupado por nº mayor (1 / 1.2 → Ronda 1; 2 / 2.2 → Ronda 2).
    _por_major: dict[str, list[dict]] = {}
    _orden_major: list[str] = []
    for c in baraja:
        mkey = str(c.get('major') or '?')
        if mkey not in _por_major:
            _por_major[mkey] = []
            _orden_major.append(mkey)
        _por_major[mkey].append(c)

    def _estado_grupo(cartas: list[dict]) -> str:
        if any(x.get('resultado') == 'en_mesa' for x in cartas):
            return 'en_curso'
        if any(x.get('resultado') == 'aceptada' for x in cartas):
            return 'aceptada'
        if any(x.get('resultado') == 'rechazada' for x in cartas):
            return 'rechazada'
        return 'anterior'

    # Ronda alta arriba. Dentro: base (#3) abajo, correcciones (#3.1…) hacia arriba.
    baraja_grupos = []
    for mkey in reversed(_orden_major):
        cartas = _por_major[mkey]
        baraja_grupos.append({
            'major': mkey,
            'estado': _estado_grupo(cartas),
            'cartas': list(reversed(cartas)),
        })

    corr_activa = bool(corr) and modo_prev == 'responder'
    ronda_sel = None
    viendo_recibida = False

    if ronda_id:
        ronda_sel = next((r for r in rondas if r.id == ronda_id), None)
        if ronda_sel and ronda_sel.resultado == 'en_mesa':
            if mesa_ajena and ronda_sel.id == mesa_ajena.id and not corr_activa:
                viendo_recibida = True
            else:
                # Carta propia en mesa (o corr forzada): vista interactiva actual.
                ronda_sel = None
    elif modo_prev == 'responder' and mesa_ajena and not corr_activa:
        # Por defecto al abrir: ver lo que mandaron (aceptar sin editar).
        ronda_sel = mesa_ajena
        viendo_recibida = True

    viendo_historial = bool(ronda_sel)

    if viendo_recibida:
        modo_mesa = 'recibida'
    elif viendo_historial:
        modo_mesa = 'historial'
    else:
        modo_mesa = modo_prev

    # Limpia restos en propuestas vivas: el motivo vive en la ronda rechazada.
    if mesa is None:
        for p in (propia, ajena):
            if p and p.estado == 'borrador' and (p.comentario_rechazo or '').strip():
                p.comentario_rechazo = None

    comparar = None
    comparar_cadena: list[dict] = []
    etiqueta_borrador = ''
    # Cabeceras #1 / #1.2 / App / € en TODOS los modos (no solo al responder).
    vivos = [r for r in rondas if r and (r.resultado or '') != 'retirada' and r.id]

    def _ancla_cadena():
        if ronda_sel is not None:
            return ronda_sel
        if mesa_ajena is not None:
            return mesa_ajena
        if mesa is not None:
            return mesa
        return vivos[-1] if vivos else None

    ancla = _ancla_cadena()
    if ancla is not None:
        comparar = ancla
        comparar_cadena = cadena_rondas_negociacion(rondas, ancla, etiquetas)

    # Columna del borrador editable (#1, #1.3…). También tras rechazo mirando historial
    # (mesa vacía + borrador) para etiquetar «Nueva #2» en la baraja.
    if (
        propia
        and (propia.estado or '') == 'borrador'
        and not bloqueado
        and (
            (modo_mesa in ('preparar', 'responder') and ronda_sel is None)
            or (mesa is None and modo_prev == 'preparar')
        )
    ):
        # Si miras una carta del historial, la etiqueta del próximo envío se calcula
        # desde la última ronda viva (no desde la carta que estás leyendo).
        ancla_borrador = ancla if ronda_sel is None else (vivos[-1] if vivos else None)
        cadena_borrador = (
            comparar_cadena
            if ronda_sel is None
            else (
                cadena_rondas_negociacion(rondas, ancla_borrador, etiquetas)
                if ancla_borrador is not None else []
            )
        )
        ultima_et = (
            cadena_borrador[-1]['etiqueta']
            if cadena_borrador
            else (etiqueta_ronda(ancla_borrador, etiquetas) if ancla_borrador else '')
        )
        if ancla_borrador is not None and (ancla_borrador.resultado or '') == 'rechazada':
            # Tras rechazo empieza negociación nueva: 1 → 2, 3.2 → 4…
            try:
                etiqueta_borrador = str(int(str(ultima_et).split('.', 1)[0]) + 1)
            except (TypeError, ValueError):
                etiqueta_borrador = siguiente_etiqueta_propuesta(ultima_et)
        elif ultima_et:
            etiqueta_borrador = siguiente_etiqueta_propuesta(ultima_et)
        else:
            etiqueta_borrador = '1'

    if modo_prev == 'esperando':
        turno = 'esperando'
    elif modo_prev == 'responder':
        turno = 'te_toca'
    elif modo_prev == 'preparar':
        # Tras un rechazo (mesa vacía) sigue pudiendo enviar aunque mire historial.
        turno = 'puedes_enviar'
    elif modo_mesa == 'cerrada':
        turno = 'cerrada'
    else:
        turno = 'historial'

    chat_msgs = listar_chat(company.id, obra.id, anio, mes)
    chat_ui = []
    _re_hash = re.compile(r'#([\d.]+)')
    for m in chat_msgs:
        if m.direccion == 'sistema':
            lado = ''
            es_mio = False
        elif m.direccion == propia_dir:
            lado = _lado(propia_dir)
            es_mio = True
        else:
            lado = _lado(m.direccion)
            es_mio = False
        autor_nombre = ''
        if m.autor:
            autor_nombre = f'{(m.autor.name or "").strip()} {(m.autor.lastname or "").strip()}'.strip()
        tipo_m = (m.tipo or '').strip() or 'nota'
        texto_ui = _texto_chat_ui(m.texto or '', autor=autor_nombre, tipo=tipo_m)
        es_evento = tipo_m in ('envio', 'aceptacion', 'desenvio')
        es_rechazo = tipo_m == 'rechazo'
        es_nota = tipo_m == 'nota'
        # Línea corta para divisores de sistema (sin caja).
        linea = ''
        if es_evento:
            quien = autor_nombre or lado or ''
            hora = m.created_at.strftime('%H:%M') if m.created_at else ''
            m_hash = _re_hash.search(m.texto or '') or _re_hash.search(texto_ui or '')
            etiq = m_hash.group(1) if m_hash else ''
            if tipo_m == 'envio':
                accion = f'envió #{etiq}' if etiq else 'envió la propuesta'
            elif tipo_m == 'aceptacion':
                accion = f'aceptó #{etiq}' if etiq else 'aceptó la propuesta'
            else:
                accion = 'retiró la propuesta'
            partes = [p for p in (quien, accion) if p]
            nucleo = ' '.join(partes) if partes else accion
            linea = f'{nucleo} ({hora})' if hora else nucleo
        elif es_rechazo:
            # Cuerpo = solo el motivo (quita el prefijo «Ha rechazado…»).
            motivo = texto_ui or ''
            for pref in (
                'Ha rechazado la propuesta:',
                'ha rechazado la propuesta:',
                'Rechazó la propuesta:',
            ):
                if motivo.lower().startswith(pref.lower()):
                    motivo = motivo[len(pref):].strip()
                    break
            texto_ui = motivo or texto_ui
        chat_ui.append({
            'id': m.id,
            'tipo': tipo_m,
            'texto': texto_ui,
            'cuando': m.created_at,
            'lado': lado,
            'autor': autor_nombre,
            'es_mio': es_mio,
            'es_sistema': not es_nota,
            'es_evento': es_evento,
            'es_rechazo': es_rechazo,
            'es_nota': es_nota,
            'linea': linea,
        })

    # Solo oficina (SaaS): reabrir mes cerrado (aceptada), o restaurar una carta
    # rechazada a la mesa. Tras un rechazo normal ambos ya tienen borrador nuevo:
    # no hace falta reabrir para «abrir propuesta nueva».
    puede_reabrir = False
    if not vista_subcontrata and mesa is None:
        if bloqueado:
            puede_reabrir = True
        elif any((r.resultado or '') == 'aceptada' for r in rondas):
            puede_reabrir = True
        elif (
            any((r.resultado or '') == 'rechazada' for r in rondas)
            and not (
                propia
                and (propia.estado or '') == 'borrador'
                and (not ajena or (ajena.estado or '') in ('borrador', 'cerrada'))
            )
        ):
            # Rechazo «atascado» (alguien no quedó en borrador): sí permite restaurar.
            puede_reabrir = True

    # Propuesta de la subcontrata (la que debe enviar normalmente).
    prop_sub = propia if vista_subcontrata else ajena
    cert_requerida = bool(
        prop_sub
        and getattr(prop_sub, 'requerida_at', None)
        and (prop_sub.estado or '') == 'borrador'
    )
    puede_requerir = (
        not vista_subcontrata
        and not bloqueado
        and modo_mesa == 'preparar'
        and prop_sub is not None
        and (prop_sub.estado or '') == 'borrador'
    )

    return {
        'rondas': rondas,
        'baraja': baraja,
        'baraja_grupos': baraja_grupos,
        'mesa': mesa,
        'mesa_carta': _carta(mesa) if mesa else None,
        'mesa_carta_seq': mesa_carta_seq,
        'mesa_ajena_id': mesa_ajena.id if mesa_ajena else None,
        'ronda_sel': ronda_sel,
        'ronda_sel_etiqueta': (
            etiquetas.get(int(ronda_sel.id), str(ronda_sel.secuencia or ''))
            if ronda_sel and ronda_sel.id else None
        ),
        'viendo_historial': viendo_historial,
        'viendo_recibida': viendo_recibida,
        'corr_activa': corr_activa,
        'modo_mesa': modo_mesa,
        'turno': turno,
        'puede_reabrir': puede_reabrir,
        'puede_requerir': puede_requerir,
        'cert_requerida': cert_requerida,
        'cert_requerida_at': getattr(prop_sub, 'requerida_at', None) if prop_sub else None,
        'comparar_ronda': comparar,
        'comparar_cadena': comparar_cadena,
        'etiqueta_borrador': etiqueta_borrador,
        'mapa_comparar': mapa_lineas_ronda(comparar),
        'totales_comparar': totales_comparar_ronda(comparar),
        'lado_propio': _lado(propia_dir),
        'lado_ajeno': _lado(_otra(propia_dir)),
        'chat_mensajes': chat_ui,
        # Oficina (DIR_EMP) sí muestra inicio/fin del envío; subcontrata solo totales.
        'hist_muestra_tramo': bool(
            ronda_sel and (ronda_sel.direccion or '') == DIR_EMP
        ),
        'grupos_hist': agrupar_snapshot(
            ronda_sel.lineas_json if ronda_sel else None,
            modo='fecha' if modo_vista == 'fecha' else 'persona',
            obra_id=obra.id if obra else None,
        ),
    }
