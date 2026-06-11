"""Detalle de entidades locales sin vínculo Odoo."""
from flask import url_for

from app.models import Obra, User, Company


def _user_linkage_hint(user):
    if user.role in ('admin', 'rrhh', 'jefe_obra'):
        return f'Usuario interno ({user.role}) — no se importa desde Odoo'
    if not user.active:
        return 'Usuario inactivo o pendiente de alta'
    if user.company_rel and user.company_rel.is_internal:
        return 'Operario de empresa interna — puede no tener registro en Odoo HR'
    return 'Sin odoo_id — creado manualmente o pendiente de sincronizar'


def _company_linkage_hint(company):
    if company.is_internal:
        return 'Empresa interna — no se importa como subcontrata Odoo'
    return 'Sin odoo_id — creada manualmente o pendiente de sincronizar'


def _obra_linkage_hint(obra):
    if obra.estado == 'Finalizada':
        return 'Obra finalizada sin vínculo Odoo'
    return 'Creada manualmente o importada sin odoo_id'


def get_entity_linkage_summary():
    obras_sin = (
        Obra.query.filter(Obra.is_deleted.is_(False), Obra.odoo_id.is_(None))
        .order_by(Obra.nombre)
        .all()
    )
    users_sin = (
        User.query.filter(User.is_deleted.is_(False), User.odoo_id.is_(None))
        .order_by(User.name, User.lastname)
        .all()
    )
    companies_sin = (
        Company.query.filter(Company.odoo_id.is_(None))
        .order_by(Company.nombre)
        .all()
    )

    return {
        'obras': {
            'vinculadas': Obra.query.filter(Obra.is_deleted.is_(False), Obra.odoo_id.isnot(None)).count(),
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
            'vinculados': User.query.filter(User.is_deleted.is_(False), User.odoo_id.isnot(None)).count(),
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
            'vinculadas': Company.query.filter(Company.odoo_id.isnot(None)).count(),
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
