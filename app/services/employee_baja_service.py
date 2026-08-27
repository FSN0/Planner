"""
Baja / reactivación de personas preservando historial.

Usado por:
- Editar persona (tick «Usuario activo»)
- Desactivar operario / batch
- Sincronización Odoo (empleados y externos)

No usa soft_delete: el DNI y las FKs históricas se mantienen.
Las asignaciones futuras se liberan y quedan registradas como
solicitudes DESASIGNAR ya cumplidas (sin email de «nueva solicitud»).
"""
from collections import defaultdict

from sqlalchemy import or_

from app import db
from app.models import (
    ROLE_ADMIN,
    Asignacion,
    Company,
    Obra,
    Solicitud,
    User,
)
from app.services.core_assignment_service import CoreAssignmentService
from app.services.solicitud_service import build_comentarios_config
from app.utils.timezone_utils import today_local, utc_now

MOTIVO_MANUAL = 'manual'
MOTIVO_ODOO = 'odoo'

NOTA_BAJA_MANUAL = 'Baja de empleado (desactivación manual)'
NOTA_BAJA_ODOO = 'Baja automática por sincronización Odoo'
NOTA_LOG_ASIGNACION = 'Baja de empleado'


def _resolve_actor_id(actor_id=None):
    if actor_id:
        return int(actor_id)
    admin = (
        User.query.filter_by(role=ROLE_ADMIN, active=True, is_deleted=False)
        .order_by(User.id.asc())
        .first()
    )
    if admin:
        return admin.id
    any_user = User.query.order_by(User.id.asc()).first()
    return any_user.id if any_user else 1


def _nota_para_motivo(motivo, notas=None):
    if notas and str(notas).strip():
        return str(notas).strip()
    if motivo == MOTIVO_ODOO:
        return NOTA_BAJA_ODOO
    return NOTA_BAJA_MANUAL


def _limpiar_jefaturas(user, today):
    """Quita jefe/encargado en obras aún abiertas."""
    obras_jefe = Obra.query.filter(
        Obra.jefe_obra_id == user.id,
        Obra.is_deleted.is_(False),
        or_(Obra.fecha_fin.is_(None), Obra.fecha_fin >= today),
    ).all()
    for obra in obras_jefe:
        obra.jefe_obra_id = None

    obras_enc = Obra.query.filter(
        Obra.encargado_id == user.id,
        Obra.is_deleted.is_(False),
        or_(Obra.fecha_fin.is_(None), Obra.fecha_fin >= today),
    ).all()
    for obra in obras_enc:
        obra.encargado_id = None


def _liberar_asignaciones_futuras(user, actor_id, notas):
    """Desasigna días futuros y deja solicitud CUMPLIDA por obra (auditoría)."""
    today = today_local()
    futuras = Asignacion.query.filter(
        Asignacion.user_id == user.id,
        Asignacion.fecha > today,
    ).all()
    if not futuras:
        return 0

    por_obra = defaultdict(list)
    for a in futuras:
        por_obra[a.obra_id].append(a)

    liberadas = 0
    ahora = utc_now()
    for obra_id, asigs in por_obra.items():
        fechas = sorted({a.fecha for a in asigs})
        for a in asigs:
            if CoreAssignmentService.desasignar(
                a.user_id,
                a.obra_id,
                a.fecha,
                actor_id,
                NOTA_LOG_ASIGNACION,
                detalle_extra=notas,
                registrar_log=False,
            ):
                liberadas += 1
        if fechas:
            CoreAssignmentService.registrar_log_rango(
                user.id,
                obra_id,
                fechas[0],
                fechas[-1],
                len(fechas),
                actor_id,
                NOTA_LOG_ASIGNACION,
                False,
                detalle_extra=notas,
                fechas=fechas,
            )
            sol = Solicitud(
                tipo='CONCRETA',
                accion='DESASIGNAR',
                obra_id=obra_id,
                requested_by_id=actor_id,
                empleado_id=user.id,
                fecha_inicio=fechas[0],
                fecha_fin=fechas[-1],
                cantidad_solicitada=1,
                cantidad_cubierta=1,
                estado='CUMPLIDA',
                comentarios=build_comentarios_config(fechas, mode='selected'),
                notas=notas,
                resolved_at=ahora,
                resolved_by_id=actor_id,
            )
            db.session.add(sol)
    return liberadas


def _maybe_inactivar_empresa(company):
    """Si es externa y no queda nadie activo, archiva la empresa."""
    if not company or company.is_internal or not company.active:
        return False
    queda = User.query.filter(
        User.company_id == company.id,
        User.active.is_(True),
        User.is_deleted.is_(False),
    ).count()
    if queda:
        return False
    company.active = False
    return True


def dar_de_baja(user, *, actor_id=None, motivo=MOTIVO_MANUAL, notas=None, commit=True):
    """
    Desactiva al usuario sin borrar historial.

    Si ya estaba inactivo pero el motivo era incorrecto/ausente (p.ej. backfill
    «pending»), actualiza el motivo sin rehacer toda la baja.

    Returns dict: {changed, liberadas, company_inactivada}
    """
    if not user or user.is_deleted:
        return {'changed': False, 'liberadas': 0, 'company_inactivada': False}

    motivo_norm = motivo if motivo in (MOTIVO_MANUAL, MOTIVO_ODOO) else MOTIVO_MANUAL
    actor = _resolve_actor_id(actor_id)
    nota = _nota_para_motivo(motivo_norm, notas)
    today = today_local()

    # Ya inactivo: corregir motivo si hace falta (p.ej. sync Odoo tras backfill «pending»).
    if not user.active:
        reason = (user.deactivation_reason or '').strip()
        if reason in ('', 'pending') and motivo_norm in (MOTIVO_MANUAL, MOTIVO_ODOO):
            user.deactivation_reason = motivo_norm
            if not user.deactivated_at:
                user.deactivated_at = utc_now()
            liberadas = _liberar_asignaciones_futuras(user, actor, nota)
            company_inactivada = False
            if user.company_id:
                company = Company.query.get(user.company_id)
                company_inactivada = _maybe_inactivar_empresa(company)
            if commit:
                db.session.commit()
            return {
                'changed': True,
                'liberadas': liberadas,
                'company_inactivada': company_inactivada,
            }
        return {'changed': False, 'liberadas': 0, 'company_inactivada': False}

    user.active = False
    user.deactivation_reason = motivo_norm
    user.deactivated_at = utc_now()
    user.scheduled_activation_date = None
    user.scheduled_deactivation_date = None

    _limpiar_jefaturas(user, today)
    liberadas = _liberar_asignaciones_futuras(user, actor, nota)

    company_inactivada = False
    if user.company_id:
        company = Company.query.get(user.company_id)
        company_inactivada = _maybe_inactivar_empresa(company)

    if commit:
        db.session.commit()

    return {
        'changed': True,
        'liberadas': liberadas,
        'company_inactivada': company_inactivada,
    }


def reactivar(user, *, actor_id=None, commit=True):
    """Reactiva usuario y, si aplica, su empresa externa archivada."""
    if not user or user.is_deleted:
        return {'changed': False, 'company_reactivada': False}
    if user.active:
        company_reactivada = False
        if user.company_id:
            company = Company.query.get(user.company_id)
            if company and not company.active:
                company.active = True
                company_reactivada = True
                if commit:
                    db.session.commit()
        return {'changed': False, 'company_reactivada': company_reactivada}

    user.active = True
    user.deactivation_reason = None
    user.deactivated_at = None
    user.scheduled_deactivation_date = None

    company_reactivada = False
    if user.company_id:
        company = Company.query.get(user.company_id)
        if company and not company.active:
            company.active = True
            company_reactivada = True

    if commit:
        db.session.commit()

    return {'changed': True, 'company_reactivada': company_reactivada}


def aplicar_baja_por_odoo(local_id, *, actor_id=None, commit=False):
    """Atajo para sync: desactiva por id local si sigue activo."""
    user = User.query.get(local_id)
    if not user:
        return {'changed': False, 'liberadas': 0, 'company_inactivada': False}
    return dar_de_baja(
        user,
        actor_id=actor_id,
        motivo=MOTIVO_ODOO,
        commit=commit,
    )
