"""Detalle de entidades locales sin vínculo Odoo."""
from flask import url_for
from sqlalchemy import or_

from app.models import Obra, User, Company


def _has_odoo_link(column):
    return column.has_key('odoo') & column['odoo'].astext.isnot(None)


def _sin_odoo_link(column):
    return or_(~column.has_key('odoo'), column['odoo'].astext.is_(None), column['odoo'].astext == '')


def _user_linkage_hint(user):
    if user.role in ('admin', 'rrhh', 'jefe_obra'):
        return f'Usuario interno ({user.role}) — no se importa desde Odoo'
    if not user.active:
        return 'Usuario inactivo o pendiente de alta'
    if user.company_rel and user.company_rel.is_internal:
        return 'Operario de empresa interna — puede no tener registro en Odoo HR'
    return 'Sin vínculo Odoo — creado manualmente o pendiente de sincronizar'


def _company_linkage_hint(company):
    if company.is_internal:
        return 'Empresa interna — no se importa como subcontrata Odoo'
    return 'Sin vínculo Odoo — creada manualmente o pendiente de sincronizar'


def _obra_linkage_hint(obra):
    if obra.estado == 'Finalizada':
        return 'Obra finalizada sin vínculo Odoo'
    return 'Creada manualmente o importada sin vínculo Odoo'


def get_entity_linkage_summary():
    obras_sin = (
        Obra.query.filter(Obra.is_deleted.is_(False), _sin_odoo_link(Obra.external_ids))
        .order_by(Obra.nombre)
        .all()
    )
    users_sin = (
        User.query.filter(User.is_deleted.is_(False), _sin_odoo_link(User.external_ids))
        .order_by(User.name, User.lastname)
        .all()
    )
    companies_sin = (
        Company.query.filter(_sin_odoo_link(Company.external_ids))
        .order_by(Company.nombre)
        .all()
    )

    return {
        'obras': {
            'vinculadas': Obra.query.filter(Obra.is_deleted.is_(False), _has_odoo_link(Obra.external_ids)).count(),
            'total': Obra.query.filter(Obra.is_deleted.is_(False)).count(),
            'sin_vincular': [
                {
                    'id': o.id,
                    'label': o.nombre,
                    'codigo': o.codigo or '—',
                    'estado': o.estado,
                    'hint': _obra_linkage_hint(o),
                    'url': url_for('admin.obra_panel', obra_id=o.id),
                }
                for o in obras_sin
            ],
        },
        'empleados': {
            'vinculados': User.query.filter(User.is_deleted.is_(False), _has_odoo_link(User.external_ids)).count(),
            'total': User.query.filter(User.is_deleted.is_(False)).count(),
            'sin_vincular': [
                {
                    'id': u.id,
                    'label': f'{u.name} {u.lastname}'.strip(),
                    'role': u.role,
                    'email': u.email or '—',
                    'hint': _user_linkage_hint(u),
                    'url': url_for('admin.worker_panel', user_id=u.id),
                }
                for u in users_sin
            ],
        },
        'empresas': {
            'vinculadas': Company.query.filter(_has_odoo_link(Company.external_ids)).count(),
            'total': Company.query.count(),
            'sin_vincular': [
                {
                    'id': c.id,
                    'label': c.nombre,
                    'codigo': c.code,
                    'tipo': 'Interna' if c.is_internal else 'Externa',
                    'hint': _company_linkage_hint(c),
                    'url': url_for('admin.company_panel', company_id=c.id),
                }
                for c in companies_sin
            ],
        },
    }
