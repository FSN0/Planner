"""Catálogo y asignación de etiquetas (empleado / subcontrata).

Odoo: la escritura hacia ERP queda aparcada en ``etiqueta_odoo_hooks``;
SignaPlan será la fuente de verdad cuando se active.
"""
from __future__ import annotations

import re

from sqlalchemy import func

from app import db
from app.models import Company, Etiqueta, Solicitud, User
from app.services.etiqueta_odoo_hooks import (
    notify_etiqueta_absorbed,
    notify_etiqueta_created,
    notify_etiqueta_deleted,
    notify_etiqueta_renamed,
)

_HEX_COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')


def normalize_color(raw) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in ('#ffffff', '#fff', 'white', 'none', 'null'):
        return None
    if not text.startswith('#'):
        text = f'#{text}'
    if not _HEX_COLOR.match(text):
        return None
    return text.lower()


def list_etiquetas(tipo: str, *, active_only: bool = True) -> list[Etiqueta]:
    q = Etiqueta.query.filter_by(tipo=tipo)
    if active_only:
        q = q.filter_by(active=True)
    return q.order_by(func.lower(Etiqueta.nombre)).all()


def get_etiqueta(etiqueta_id: int) -> Etiqueta | None:
    return Etiqueta.query.get(etiqueta_id)


def etiqueta_to_dict(e: Etiqueta) -> dict:
    return {
        'id': e.id,
        'nombre': e.nombre,
        'color': e.color,
        'tipo': e.tipo,
        'active': bool(e.active),
    }


def create_etiqueta(tipo: str, nombre: str, color=None) -> Etiqueta:
    tipo = (tipo or '').strip()
    if tipo not in Etiqueta.TIPOS:
        raise ValueError('Tipo de etiqueta inválido.')
    nombre = (nombre or '').strip()
    if not nombre:
        raise ValueError('El nombre es obligatorio.')
    if len(nombre) > 80:
        raise ValueError('Nombre demasiado largo (máx. 80).')
    clash = (
        Etiqueta.query
        .filter(
            Etiqueta.tipo == tipo,
            func.lower(Etiqueta.nombre) == nombre.lower(),
        )
        .first()
    )
    if clash:
        raise ValueError('Ya existe una etiqueta con ese nombre.')
    e = Etiqueta(tipo=tipo, nombre=nombre, color=normalize_color(color), active=True)
    db.session.add(e)
    db.session.flush()
    notify_etiqueta_created(e)
    return e


def rename_etiqueta(etiqueta_id: int, nuevo_nombre: str) -> Etiqueta:
    e = Etiqueta.query.get(etiqueta_id)
    if not e:
        raise ValueError('Etiqueta no encontrada.')
    nuevo = (nuevo_nombre or '').strip()
    if not nuevo:
        raise ValueError('El nombre es obligatorio.')
    clash = (
        Etiqueta.query
        .filter(
            Etiqueta.tipo == e.tipo,
            func.lower(Etiqueta.nombre) == nuevo.lower(),
            Etiqueta.id != e.id,
        )
        .first()
    )
    if clash:
        raise ValueError('Ya existe otra etiqueta con ese nombre.')
    old = e.nombre
    e.nombre = nuevo
    db.session.flush()
    notify_etiqueta_renamed(e, old_name=old)
    return e


def update_etiqueta_color(etiqueta_id: int, color) -> Etiqueta:
    e = Etiqueta.query.get(etiqueta_id)
    if not e:
        raise ValueError('Etiqueta no encontrada.')
    e.color = normalize_color(color)
    db.session.flush()
    return e


def absorb_etiqueta(source_id: int, target_id: int) -> Etiqueta:
    """Mueve todas las asignaciones de source → target y borra source."""
    if int(source_id) == int(target_id):
        raise ValueError('Origen y destino deben ser distintos.')
    source = Etiqueta.query.get(source_id)
    target = Etiqueta.query.get(target_id)
    if not source or not target:
        raise ValueError('Etiqueta no encontrada.')
    if source.tipo != target.tipo:
        raise ValueError('Solo se puede absorber entre etiquetas del mismo tipo.')

    for user in list(source.users):
        if target not in user.etiquetas:
            user.etiquetas.append(target)
        if source in user.etiquetas:
            user.etiquetas.remove(source)
    for company in list(source.companies):
        if target not in company.etiquetas:
            company.etiquetas.append(target)
        if source in company.etiquetas:
            company.etiquetas.remove(source)
    for sol in list(source.solicitudes):
        if target not in sol.etiquetas:
            sol.etiquetas.append(target)
        if source in sol.etiquetas:
            sol.etiquetas.remove(source)

    notify_etiqueta_absorbed(source, target)
    db.session.delete(source)
    db.session.flush()
    return target


def delete_etiqueta(etiqueta_id: int) -> None:
    e = Etiqueta.query.get(etiqueta_id)
    if not e:
        raise ValueError('Etiqueta no encontrada.')
    notify_etiqueta_deleted(e)
    db.session.delete(e)
    db.session.flush()


def _resolve_empleado_tags(ids) -> list[Etiqueta]:
    clean = []
    for raw in ids or []:
        try:
            clean.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not clean:
        return []
    rows = (
        Etiqueta.query
        .filter(
            Etiqueta.id.in_(clean),
            Etiqueta.tipo == Etiqueta.TIPO_EMPLEADO,
            Etiqueta.active.is_(True),
        )
        .all()
    )
    return rows


def _resolve_subcontrata_tags(ids) -> list[Etiqueta]:
    clean = []
    for raw in ids or []:
        try:
            clean.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not clean:
        return []
    return (
        Etiqueta.query
        .filter(
            Etiqueta.id.in_(clean),
            Etiqueta.tipo == Etiqueta.TIPO_SUBCONTRATA,
            Etiqueta.active.is_(True),
        )
        .all()
    )


def set_user_etiquetas(user: User, etiqueta_ids) -> None:
    user.etiquetas = _resolve_empleado_tags(etiqueta_ids)


def set_company_etiquetas(company: Company, etiqueta_ids) -> None:
    company.etiquetas = _resolve_subcontrata_tags(etiqueta_ids)


def set_solicitud_etiquetas(solicitud: Solicitud, etiqueta_ids) -> None:
    solicitud.etiquetas = _resolve_empleado_tags(etiqueta_ids)


def user_own_etiquetas(user: User) -> list[Etiqueta]:
    return sorted(list(user.etiquetas or []), key=lambda e: (e.nombre or '').lower())


def company_etiquetas(company: Company | None) -> list[Etiqueta]:
    if not company:
        return []
    return sorted(list(company.etiquetas or []), key=lambda e: (e.nombre or '').lower())


def user_search_tag_text(user: User) -> str:
    """Texto para filtro de listados: propias + de la empresa padre."""
    names = [e.nombre for e in user_own_etiquetas(user)]
    company = getattr(user, 'company_rel', None)
    if company:
        names.extend(e.nombre for e in company_etiquetas(company))
    # unique preserve order
    seen = set()
    out = []
    for n in names:
        key = (n or '').lower()
        if key and key not in seen:
            seen.add(key)
            out.append(n)
    return ' '.join(out)


def company_search_tag_text(company: Company) -> str:
    return ' '.join(e.nombre for e in company_etiquetas(company))
