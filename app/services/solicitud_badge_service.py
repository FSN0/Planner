# app/services/solicitud_badge_service.py
"""Contadores de solicitudes abiertas para badges de navegación."""
from __future__ import annotations

from sqlalchemy import or_

from app.models import Solicitud, SolicitudVehiculo, Obra
from app.services.panel_scope_service import (
    PANEL_SOLICITUDES,
    user_custody_jefe_ids,
    user_panel_mode,
)
from app.services.permission_service import user_can
from app.services.assign_mode_service import (
    user_assigns_via_solicitud,
    user_assigns_vehicles_via_solicitud,
)

_OPEN = ('PENDIENTE', 'EN_PROCESO')


def count_open_solicitud_badges(user) -> dict:
    """
    Misma lógica de alcance que el listado de solicitudes.
    Devuelve {personal, vehiculos, total}.
    """
    personal = 0
    vehiculos = 0
    if not user or not getattr(user, 'is_authenticated', False):
        return {'personal': 0, 'vehiculos': 0, 'total': 0}

    can_pers_w = user_can(user, 'solicitudes', 'w')
    can_veh_w = user_can(user, 'solicitudes_vehiculos', 'w')
    if not can_pers_w and not can_veh_w:
        return {'personal': 0, 'vehiculos': 0, 'total': 0}

    mode = user_panel_mode(user, PANEL_SOLICITUDES)

    if mode == 'office':
        if can_pers_w:
            personal = Solicitud.query.filter(Solicitud.estado.in_(_OPEN)).count()
        if can_veh_w:
            vehiculos = SolicitudVehiculo.query.filter(
                SolicitudVehiculo.estado.in_(_OPEN)
            ).count()
    else:
        # Quien pide vía solicitud ve las suyas / de su custodia (como el listado).
        if can_pers_w and user_assigns_via_solicitud(user):
            q = Solicitud.query
            custody = user_custody_jefe_ids(user, PANEL_SOLICITUDES)
            if custody:
                q = q.outerjoin(Obra, Solicitud.obra_id == Obra.id).filter(
                    or_(
                        Solicitud.requested_by_id == user.id,
                        Obra.jefe_obra_id.in_(custody),
                    ),
                    Solicitud.estado.in_(_OPEN),
                )
            else:
                q = q.filter(
                    Solicitud.requested_by_id == user.id,
                    Solicitud.estado.in_(_OPEN),
                )
            personal = q.count()
        if can_veh_w and user_assigns_vehicles_via_solicitud(user):
            vehiculos = SolicitudVehiculo.query.filter(
                SolicitudVehiculo.requested_by_id == user.id,
                SolicitudVehiculo.estado.in_(_OPEN),
            ).count()

    return {
        'personal': int(personal or 0),
        'vehiculos': int(vehiculos or 0),
        'total': int((personal or 0) + (vehiculos or 0)),
    }
