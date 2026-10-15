"""Designar / quitar admin de subcontrata desde Planner (write-back a Odoo).

Contrato acordado:
- Persona ya de esa empresa (company no interna).
- Empresa y persona con vínculo Odoo (partner).
- Si falla el write a Odoo, no se cambia el rol local.
- Varios admins por empresa permitidos.
"""
from __future__ import annotations

import logging

from flask import g

from app import db
from app.models import (
    ROLE_ADMIN_SUBCONTRATA,
    ROLE_OPERARIO,
    Company,
    User,
)
from app.services.odoo_employee_metadata import is_odoo_partner_link

logger = logging.getLogger(__name__)


def _tenant_has_odoo() -> bool:
    tenant = getattr(g, 'current_tenant', None)
    mods = (getattr(tenant, 'modulos_activos', None) or {}) if tenant else {}
    return bool(mods.get('odoo'))


def _partner_odoo_id(user: User) -> int | None:
    ext = user.external_ids or {}
    raw = str(ext.get('odoo') or '').strip()
    if not raw.isdigit():
        return None
    return int(raw)


def _company_odoo_id(company: Company | None) -> int | None:
    if not company:
        return None
    ext = company.external_ids or {}
    raw = str(ext.get('odoo') or '').strip()
    if not raw.isdigit():
        return None
    return int(raw)


def puede_gestionar_admin_subcontrata(user: User | None) -> bool:
    """True si la ficha es candidata a promover/degradar (UI)."""
    if not user or user.is_deleted or user.hiring_state:
        return False
    if user.role not in (ROLE_OPERARIO, ROLE_ADMIN_SUBCONTRATA):
        return False
    company = user.company_rel
    if not company or company.is_internal or not company.active:
        return False
    if not _tenant_has_odoo():
        return False
    if not is_odoo_partner_link(user):
        return False
    if _partner_odoo_id(user) is None:
        return False
    if _company_odoo_id(company) is None:
        return False
    return True


def set_admin_subcontrata(
    user: User,
    *,
    make_admin: bool,
    actor: User | None = None,
) -> User:
    """Promueve o degrada admin_subcontrata escribiendo antes la etiqueta en Odoo.

    Raises:
        ValueError: validación o fallo Odoo (el rol local no cambia si Odoo falla).
    """
    if not user or user.is_deleted:
        raise ValueError('Usuario no encontrado.')
    if user.hiring_state:
        raise ValueError('Finaliza la contratación antes de designar administrador.')
    if user.role not in (ROLE_OPERARIO, ROLE_ADMIN_SUBCONTRATA):
        raise ValueError('Solo se puede cambiar el rol entre operario y admin de subcontrata.')

    target_role = ROLE_ADMIN_SUBCONTRATA if make_admin else ROLE_OPERARIO
    if user.role == target_role:
        return user

    company = user.company_rel
    if not company or company.is_internal:
        raise ValueError('La persona debe pertenecer a una subcontrata (empresa externa).')
    if not company.active:
        raise ValueError('La empresa de la subcontrata no está activa.')
    if not _company_odoo_id(company):
        raise ValueError(
            'La empresa no está vinculada a Odoo. Sincroniza la subcontrata antes de designar admin.'
        )
    if not _tenant_has_odoo():
        raise ValueError('Este inquilino no tiene integración Odoo activa.')
    if not is_odoo_partner_link(user):
        raise ValueError(
            'Esta ficha no está vinculada como contacto Odoo (res.partner). '
            'Sincroniza o concilia el contacto antes.'
        )
    partner_id = _partner_odoo_id(user)
    if not partner_id:
        raise ValueError(
            'Falta el ID Odoo del contacto. Vincula a la persona con Odoo antes de designar admin.'
        )

    from app.sync.dispatcher import get_sync_adapter

    try:
        adapter = get_sync_adapter()
    except Exception as exc:
        raise ValueError(f'No se pudo conectar con Odoo: {exc}') from exc

    setter = getattr(adapter, 'set_admin_subcontrata_category', None)
    if not callable(setter):
        raise ValueError('El motor de sincronización no puede escribir etiquetas en Odoo.')

    try:
        setter(partner_id, enabled=make_admin)
    except NotImplementedError as exc:
        raise ValueError(str(exc)) from exc
    except ValueError:
        raise
    except Exception as exc:
        logger.exception(
            'set_admin_subcontrata Odoo falló user=%s partner=%s make_admin=%s',
            user.id, partner_id, make_admin,
        )
        raise ValueError(f'No se pudo actualizar la etiqueta en Odoo: {exc}') from exc

    # Solo tras éxito en Odoo.
    user.role = target_role
    db.session.add(user)
    actor_id = getattr(actor, 'id', None)
    logger.info(
        'Admin subcontrata %s user=%s company=%s actor=%s',
        'ON' if make_admin else 'OFF',
        user.id,
        company.id,
        actor_id,
    )
    return user
