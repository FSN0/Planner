"""Ausencias planificadas (vacaciones, bajas, permisos…) — genérico + sync ERP."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import text

from app import db
from app.models import (
    Asignacion,
    AusenciaConflicto,
    AusenciaPlanificada,
    CONFLICT_KEEP_ASSIGNMENT,
    CONFLICT_KEEP_LEAVE,
    CONFLICT_OVERLAY,
    CONFLICT_PENDING,
    LEAVE_SOURCE_MANUAL,
    LEAVE_SOURCE_ODOO,
    LEAVE_STATUS_APROBADA,
    LEAVE_STATUS_PENDIENTE,
    SyncLog,
    User,
)
from app.services.config_service import get_tenant_config
from app.sync.dispatcher import get_sync_adapter
from app.utils.timezone_utils import today_local, utc_now

logger = logging.getLogger(__name__)

# Colores overlay en calendarios / planificador
LEAVE_COLOR_APROBADA = '#7c3aed'
LEAVE_COLOR_PENDIENTE = '#a78bfa'


def _parse_date(value):
    if value is None:
        return None
    if hasattr(value, 'year'):
        return value
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def _find_user_id_by_odoo_external(external_id: str):
    """
    Resuelve users.id en el esquema actual (search_path del tenant).
    Evita objetos huérfanos / public schema.
    """
    if not external_id:
        return None
    return db.session.execute(
        text(
            """
            SELECT id FROM users
            WHERE COALESCE(is_deleted, false) = false
              AND external_ids->>'odoo' = :ext
            LIMIT 1
            """
        ),
        {'ext': str(external_id)},
    ).scalar()


def user_has_approved_leave(user_id: int, day) -> bool:
    """True si el empleado tiene una ausencia aprobada que cubre ese día."""
    return (
        AusenciaPlanificada.query.filter(
            AusenciaPlanificada.user_id == user_id,
            AusenciaPlanificada.estado == LEAVE_STATUS_APROBADA,
            AusenciaPlanificada.fecha_inicio <= day,
            AusenciaPlanificada.fecha_fin >= day,
        ).first()
        is not None
    )


def get_leaves_for_user(user_id: int, date_from=None, date_to=None, only_effective=False):
    q = AusenciaPlanificada.query.filter_by(user_id=user_id)
    if only_effective:
        q = q.filter_by(estado=LEAVE_STATUS_APROBADA)
    if date_from:
        q = q.filter(AusenciaPlanificada.fecha_fin >= date_from)
    if date_to:
        q = q.filter(AusenciaPlanificada.fecha_inicio <= date_to)
    return q.order_by(AusenciaPlanificada.fecha_inicio).all()


def build_leaves_by_user(user_ids, date_from, date_to, include_pending=False):
    """
    Índice user_id -> [AusenciaPlanificada] que solapan [date_from, date_to].
    Por defecto solo aprobadas (Odoo manda; pendientes no se usan en planificación).
    """
    ids = [int(u) for u in (user_ids or []) if u is not None]
    if not ids or not date_from or not date_to:
        return {}
    estados = [LEAVE_STATUS_APROBADA]
    if include_pending:
        estados.append(LEAVE_STATUS_PENDIENTE)
    rows = AusenciaPlanificada.query.filter(
        AusenciaPlanificada.user_id.in_(ids),
        AusenciaPlanificada.estado.in_(estados),
        AusenciaPlanificada.fecha_inicio <= date_to,
        AusenciaPlanificada.fecha_fin >= date_from,
    ).all()
    out = defaultdict(list)
    for leave in rows:
        out[leave.user_id].append(leave)
    return dict(out)


def leave_covering(leaves, day):
    """
    Mejor ausencia que cubre el día: prioriza aprobada sobre pendiente.
    leaves: iterable de AusenciaPlanificada.
    """
    if not leaves:
        return None
    pending = None
    for leave in leaves:
        if not leave.covers(day):
            continue
        if leave.estado == LEAVE_STATUS_APROBADA:
            return leave
        if leave.estado == LEAVE_STATUS_PENDIENTE and pending is None:
            pending = leave
    return pending


def leave_overlay_meta(leave):
    """Dict con color/label para pintar asignación en ausencia, o None."""
    if not leave:
        return None
    tipo = (leave.tipo or 'Ausencia').strip() or 'Ausencia'
    if leave.estado == LEAVE_STATUS_PENDIENTE:
        return {
            'color': LEAVE_COLOR_PENDIENTE,
            'tipo': tipo,
            'estado': leave.estado,
            'label_prefix': f'{tipo} (pendiente)',
            'aprobada': False,
        }
    return {
        'color': LEAVE_COLOR_APROBADA,
        'tipo': tipo,
        'estado': leave.estado,
        'label_prefix': tipo,
        'aprobada': True,
    }


def apply_leave_overlay_title(base_title, leave, name_first=False):
    """
    Título con overlay. name_first=True → 'Pepe · Vacaciones'; else 'Vacaciones · base'.
    Returns (title, color_or_None, is_overlay).
    """
    meta = leave_overlay_meta(leave)
    if not meta:
        return base_title, None, False
    if name_first:
        title = f"{base_title} · {meta['label_prefix']}"
    else:
        title = f"{meta['label_prefix']} · {base_title}"
    return title, meta['color'], True


def get_upcoming_leaves(actor_user, horizon_days=45, limit=25, only_future=False, only_active=False):
    """
    Ausencias en ventana [hoy, hoy+horizon].
    only_active: fecha_inicio <= hoy <= fecha_fin (en curso ahora).
    only_future: fecha_inicio > hoy (aún no han empezado).
    Admin: todas. Jefe: personal con asignación en sus obras en el periodo.
    """
    from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, Obra

    today = today_local()
    horizon = today + timedelta(days=horizon_days)
    q = AusenciaPlanificada.query.filter(
        AusenciaPlanificada.fecha_fin >= today,
        AusenciaPlanificada.fecha_inicio <= horizon,
        AusenciaPlanificada.estado == LEAVE_STATUS_APROBADA,
    )
    if only_active:
        q = q.filter(
            AusenciaPlanificada.fecha_inicio <= today,
            AusenciaPlanificada.fecha_fin >= today,
        )
    elif only_future:
        q = q.filter(AusenciaPlanificada.fecha_inicio > today)

    if actor_user.role == ROLE_JEFE:
        obra_ids = [
            o.id for o in Obra.query.filter_by(
                jefe_obra_id=actor_user.id, is_deleted=False
            ).all()
        ]
        if not obra_ids:
            return []
        user_ids = {
            row[0]
            for row in db.session.query(Asignacion.user_id).filter(
                Asignacion.obra_id.in_(obra_ids),
                Asignacion.fecha >= today,
                Asignacion.fecha <= horizon,
            ).distinct().all()
        }
        if not user_ids:
            return []
        q = q.filter(AusenciaPlanificada.user_id.in_(user_ids))
    elif actor_user.role not in (ROLE_ADMIN, ROLE_LABORAL):
        return []

    return (
        q.order_by(AusenciaPlanificada.fecha_inicio.asc(), AusenciaPlanificada.id.asc())
        .limit(limit)
        .all()
    )


def get_leaves_scoped(actor_user, estado=None, limit=200):
    """Listado histórico / filtro, acotado al ámbito del rol. Default: solo aprobadas."""
    from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, Obra

    today = today_local()
    q = AusenciaPlanificada.query
    if estado:
        q = q.filter_by(estado=estado)
    else:
        q = q.filter_by(estado=LEAVE_STATUS_APROBADA)

    if actor_user.role == ROLE_JEFE:
        obra_ids = [
            o.id for o in Obra.query.filter_by(
                jefe_obra_id=actor_user.id, is_deleted=False
            ).all()
        ]
        if not obra_ids:
            return []
        # Personal de sus obras en ventana amplia (pasado reciente + futuro)
        user_ids = {
            row[0]
            for row in db.session.query(Asignacion.user_id).filter(
                Asignacion.obra_id.in_(obra_ids),
                Asignacion.fecha >= today - timedelta(days=120),
                Asignacion.fecha <= today + timedelta(days=180),
            ).distinct().all()
        }
        if not user_ids:
            return []
        q = q.filter(AusenciaPlanificada.user_id.in_(user_ids))
    elif actor_user.role not in (ROLE_ADMIN, ROLE_LABORAL):
        return []

    return q.order_by(AusenciaPlanificada.fecha_inicio.desc()).limit(limit).all()


def obras_for_leave(leave, max_obras=3):
    """Obras en las que el empleado estaba/está asignado durante la ausencia."""
    from app.models import Obra

    rows = (
        db.session.query(Obra)
        .join(Asignacion, Asignacion.obra_id == Obra.id)
        .filter(
            Asignacion.user_id == leave.user_id,
            Asignacion.fecha >= leave.fecha_inicio,
            Asignacion.fecha <= leave.fecha_fin,
            Obra.is_deleted.is_(False),
        )
        .distinct()
        .limit(max_obras)
        .all()
    )
    return rows


def get_pending_conflicts(obra_ids=None):
    q = AusenciaConflicto.query.filter_by(estado=CONFLICT_PENDING)
    if obra_ids is not None:
        q = q.filter(AusenciaConflicto.obra_id.in_(list(obra_ids)))
    return q.order_by(AusenciaConflicto.fecha.desc()).all()


def jefe_puede_resolver_ausencias() -> bool:
    return get_tenant_config('ausencias_jefe_puede_resolver', default='False') == 'True'


def auto_resolucion_ausencias() -> str:
    """overlay (default) | none | prefer_leave | prefer_assignment"""
    raw = get_tenant_config('ausencias_auto_resolucion', default='overlay') or 'overlay'
    # Legacy: prefer_leave desasignaba; ahora equivale a overlay (mantener asignación)
    if raw == 'prefer_leave':
        return 'overlay'
    return raw


def sync_leaves_from_erp(date_from=None, date_to=None, origen=LEAVE_SOURCE_ODOO):
    """
    Importa ausencias del adaptador ERP activo del tenant.
    Crea/actualiza por (origen, external_id). No borra altas manuales.
    Omite leaves cuyo empleado Odoo no esté vinculado en SignaPlan.
    """
    from flask import g

    tenant = getattr(g, 'current_tenant', None)
    if not tenant:
        raise RuntimeError('Sin tenant en contexto para sync de ausencias')

    adapter = get_sync_adapter()
    raw = adapter.get_leaves(date_from=date_from, date_to=date_to) or []

    stats = {'nuevos': 0, 'actualizados': 0, 'omitidos': 0, 'errores': 0}
    range_from = _parse_date(date_from) if date_from else today_local() - timedelta(days=7)
    range_to = _parse_date(date_to) if date_to else today_local() + timedelta(days=400)

    for item in raw:
        nested = db.session.begin_nested()
        try:
            with db.session.no_autoflush:
                ext_id = str(item.get('external_id') or '')
                if not ext_id:
                    stats['omitidos'] += 1
                    nested.commit()
                    continue

                user_id = _find_user_id_by_odoo_external(item.get('empleado_external_id'))
                if not user_id:
                    stats['omitidos'] += 1
                    nested.commit()
                    continue

                fecha_inicio = _parse_date(item.get('fecha_inicio'))
                fecha_fin = _parse_date(item.get('fecha_fin'))
                if not fecha_inicio or not fecha_fin:
                    stats['omitidos'] += 1
                    nested.commit()
                    continue
                if fecha_fin < fecha_inicio:
                    fecha_inicio, fecha_fin = fecha_fin, fecha_inicio

                row = (
                    AusenciaPlanificada.query
                    .filter_by(origen=origen, external_id=ext_id)
                    .first()
                )
                payload = dict(
                    user_id=user_id,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    dias=item.get('dias'),
                    tipo=(item.get('tipo') or 'Ausencia')[:120],
                    tipo_external_id=item.get('tipo_external_id'),
                    estado=item.get('estado') or LEAVE_STATUS_APROBADA,
                    descripcion=item.get('descripcion'),
                    updated_at=utc_now(),
                )
                # De Odoo solo importamos aprobadas
                if origen == LEAVE_SOURCE_ODOO and payload['estado'] != LEAVE_STATUS_APROBADA:
                    stats['omitidos'] += 1
                    nested.commit()
                    continue
                is_update = row is not None
                if row:
                    for k, v in payload.items():
                        setattr(row, k, v)
                else:
                    db.session.add(AusenciaPlanificada(
                        origen=origen,
                        external_id=ext_id,
                        **payload,
                    ))
            nested.commit()
            if is_update:
                stats['actualizados'] += 1
            else:
                stats['nuevos'] += 1
        except Exception as exc:
            nested.rollback()
            logger.exception('Error syncing leave %s: %s', item, exc)
            stats['errores'] += 1

    try:
        detect_and_upsert_conflicts(date_from=range_from, date_to=range_to)
        db.session.add(SyncLog(
            tipo='Ausencias',
            modo='Manual',
            nuevos=stats['nuevos'],
            actualizados=stats['actualizados'],
            finalizados=0,
            errores=stats['omitidos'] + stats['errores'],
            detalles=(
                f"omitidos_sin_usuario={stats['omitidos']}; "
                f"errores={stats['errores']}"
            ),
            estado='ok' if stats['errores'] == 0 else 'parcial',
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return stats


def detect_and_upsert_conflicts(date_from=None, date_to=None):
    """
    Registra solapes asignación + ausencia aprobada.
    Modo overlay (default): mantiene la asignación y marca el solape como overlay
    (sin pendientes manuales ni desasignación).
    """
    if not date_from:
        date_from = today_local() - timedelta(days=7)
    if not date_to:
        date_to = today_local() + timedelta(days=120)

    leaves = AusenciaPlanificada.query.filter(
        AusenciaPlanificada.estado == LEAVE_STATUS_APROBADA,
        AusenciaPlanificada.fecha_inicio <= date_to,
        AusenciaPlanificada.fecha_fin >= date_from,
    ).all()

    created = 0
    auto = auto_resolucion_ausencias()

    for leave in leaves:
        day = max(leave.fecha_inicio, date_from)
        end = min(leave.fecha_fin, date_to)
        while day <= end:
            asignaciones = Asignacion.query.filter_by(
                user_id=leave.user_id, fecha=day
            ).all()
            for asig in asignaciones:
                existing = AusenciaConflicto.query.filter_by(
                    user_id=leave.user_id,
                    fecha=day,
                    obra_id=asig.obra_id,
                    ausencia_id=leave.id,
                ).first()
                if existing:
                    if existing.estado == CONFLICT_PENDING:
                        existing.asignacion_id = asig.id
                        if auto == 'overlay':
                            existing.estado = CONFLICT_OVERLAY
                            existing.resolved_at = utc_now()
                        elif auto == 'prefer_assignment':
                            resolve_conflict(
                                existing.id, CONFLICT_KEEP_ASSIGNMENT, resolved_by_id=None
                            )
                    continue

                conflict = AusenciaConflicto(
                    user_id=leave.user_id,
                    fecha=day,
                    obra_id=asig.obra_id,
                    ausencia_id=leave.id,
                    asignacion_id=asig.id,
                    estado=CONFLICT_PENDING,
                )
                db.session.add(conflict)
                db.session.flush()
                created += 1

                if auto == 'overlay':
                    conflict.estado = CONFLICT_OVERLAY
                    conflict.resolved_at = utc_now()
                elif auto == 'prefer_assignment':
                    resolve_conflict(conflict.id, CONFLICT_KEEP_ASSIGNMENT, resolved_by_id=None)

            day = day + timedelta(days=1)

    return created


def resolve_conflict(conflict_id: int, decision: str, resolved_by_id=None):
    """
    decision:
      - overlay → mantener asignación (Odoo manda)
      - mantener_ausencia → desasignar ese día (manual / excepcional)
      - mantener_asignacion → marcar resuelto ignorando ausencia ese día
    """
    from app.services.core_assignment_service import CoreAssignmentService

    conflict = AusenciaConflicto.query.get(conflict_id)
    if not conflict or conflict.estado != CONFLICT_PENDING:
        return False

    if decision == CONFLICT_OVERLAY:
        conflict.estado = CONFLICT_OVERLAY
    elif decision == CONFLICT_KEEP_LEAVE:
        CoreAssignmentService.desasignar(
            conflict.user_id, conflict.obra_id, conflict.fecha, None,
            'Desasignado por conflicto con ausencia planificada',
        )
        conflict.estado = CONFLICT_KEEP_LEAVE
    elif decision == CONFLICT_KEEP_ASSIGNMENT:
        conflict.estado = CONFLICT_KEEP_ASSIGNMENT
    else:
        raise ValueError(f'Decisión de conflicto no válida: {decision}')

    conflict.resolved_by_id = resolved_by_id
    conflict.resolved_at = utc_now()
    return True


def create_manual_leave(
    user_id,
    fecha_inicio,
    fecha_fin,
    tipo='Vacaciones',
    estado=LEAVE_STATUS_APROBADA,
    descripcion=None,
    created_by_id=None,
):
    user_id = int(user_id)
    exists = db.session.execute(
        text('SELECT 1 FROM users WHERE id = :id AND COALESCE(is_deleted, false) = false'),
        {'id': user_id},
    ).scalar()
    if not exists:
        raise ValueError('Empleado no encontrado.')

    fecha_inicio = _parse_date(fecha_inicio)
    fecha_fin = _parse_date(fecha_fin)
    if fecha_fin < fecha_inicio:
        fecha_inicio, fecha_fin = fecha_fin, fecha_inicio
    leave = AusenciaPlanificada(
        user_id=user_id,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        dias=(fecha_fin - fecha_inicio).days + 1,
        tipo=tipo[:120],
        estado=estado,
        origen=LEAVE_SOURCE_MANUAL,
        descripcion=descripcion,
        created_by_id=created_by_id,
    )
    db.session.add(leave)
    db.session.flush()
    detect_and_upsert_conflicts(date_from=fecha_inicio, date_to=fecha_fin)
    db.session.commit()
    return leave
