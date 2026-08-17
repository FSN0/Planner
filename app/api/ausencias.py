# app/api/ausencias.py
#
# Alta rápida de ausencias (calendario de persona / UI).

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from app import db
from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH
from app.decorators import roles_required
from app.services.permission_service import user_can, is_laboral
from app.services.leave_service import create_manual_leave, estado_alta_por_rol
from app.services.i18n_service import translate

ausencias_api = Blueprint('ausencias_api', __name__)


@ausencias_api.route('/v6/ausencias', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH)
def api_crear_ausencia():
    """
    Alta rápida de ausencia (p. ej. desde el calendario de la persona).
    Jefe → pendiente; admin/laboral/rrhh → aprobada por defecto.
    """
    if is_laboral(current_user) and not user_can(current_user, 'ausencias', 'w'):
        return jsonify({'success': False, 'error': translate('Sin permiso.')}), 403

    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id') or data.get('worker_id')
    fecha_inicio = data.get('fecha_inicio') or data.get('start')
    fecha_fin = data.get('fecha_fin') or data.get('end')
    tipo = (data.get('tipo') or 'Vacaciones').strip() or 'Vacaciones'
    estado = estado_alta_por_rol(current_user, data.get('estado'))

    if not user_id or not fecha_inicio or not fecha_fin:
        return jsonify({'success': False, 'error': translate('Faltan empleado o fechas.')}), 400

    try:
        leave = create_manual_leave(
            user_id=int(user_id),
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            tipo=tipo,
            estado=estado,
            descripcion=data.get('descripcion'),
            created_by_id=current_user.id,
        )
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 400

    if leave is None:
        db.session.rollback()
        return jsonify({'success': False, 'error': translate('No se pudo guardar la ausencia.')}), 500

    leave_id = leave.id
    leave_estado = leave.estado
    return jsonify({
        'success': True,
        'leave_id': leave_id,
        'estado': leave_estado,
        'message': (
            translate('Solicitud de ausencia enviada (pendiente de validación).')
            if leave_estado == 'pendiente'
            else translate('Ausencia registrada.')
        ),
    })
