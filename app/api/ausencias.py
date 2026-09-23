# app/api/ausencias.py
#
# Alta rápida de ausencias (calendario de persona / UI).

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from app import db
from app.services.permission_service import user_can
from app.services.leave_service import (
    actor_puede_crear_ausencia,
    create_manual_leave,
    estado_alta_por_permiso,
)
from app.services.i18n_service import translate

ausencias_api = Blueprint('ausencias_api', __name__)


@ausencias_api.route('/v6/ausencias', methods=['POST'])
@login_required
def api_crear_ausencia():
    """
    Alta rápida de ausencia (p. ej. desde el calendario de la persona).
    Oficina → aprobada por defecto; custodia/portal → pendiente.
    """
    if not actor_puede_crear_ausencia(current_user):
        return jsonify({'success': False, 'error': translate('Sin permiso.')}), 403

    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id') or data.get('worker_id')
    fecha_inicio = data.get('fecha_inicio') or data.get('start')
    fecha_fin = data.get('fecha_fin') or data.get('end')
    tipo = (data.get('tipo') or 'Vacaciones').strip() or 'Vacaciones'
    estado = estado_alta_por_permiso(current_user, data.get('estado'))

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

    db.session.commit()
    return jsonify({
        'success': True,
        'id': leave.id,
        'estado': leave.estado,
        'puede_gestionar': user_can(current_user, 'ausencias', 'w'),
    })
