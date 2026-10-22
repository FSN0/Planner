# app/api/vehiculos.py
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from app import db
from app.models import AsignacionVehiculo, Vehiculo, Festivo
from app.services.i18n_service import translate
from app.services.leave_service import user_has_approved_leave
from app.services.permission_service import can_write_vehicles, can_plan_fleet, user_can
from app.services.vehicle_assignment_service import (
    last_vehicle_assignment_end,
    process_vehicle_assignment_action,
)
from app.utils.timezone_utils import today_local

vehiculos_api = Blueprint('vehiculos_api', __name__)


@vehiculos_api.route('/v6/planificador/vehicle-assignment-span', methods=['GET'])
@login_required
def api_vehicle_assignment_span():
    """Fin del tramo planificado usuario+vehículo desde una fecha (para el modal de baja)."""
    if not can_plan_fleet(current_user):
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403

    try:
        worker_id = int(request.args.get('worker_id'))
        vehicle_id = int(request.args.get('vehicle_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': translate('Parámetros inválidos')}), 400

    from_str = (request.args.get('from') or request.args.get('start') or '').strip()
    if not from_str:
        return jsonify({'success': False, 'error': translate('Falta la fecha de inicio')}), 400
    try:
        from_date = datetime.strptime(from_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'error': translate('Formato de fecha inválido')}), 400

    end = last_vehicle_assignment_end(vehicle_id, worker_id, from_date)
    return jsonify({
        'success': True,
        'start': from_date.isoformat(),
        'end': end.isoformat() if end else from_date.isoformat(),
    })


@vehiculos_api.route('/v6/vehicles', methods=['GET'])
@login_required
def api_list_vehicles():
    """Listado select2: {id, text: 'matricula — nombre'}."""
    if not user_can(current_user, 'vehiculos', 'r') and not can_plan_fleet(current_user):
        return jsonify({'results': []}), 403
    q = (request.args.get('q') or '').strip().lower()
    start_str = (request.args.get('start') or '').strip()
    end_str = (request.args.get('end') or '').strip()
    worker_id_raw = request.args.get('worker_id')
    query = Vehiculo.query.filter_by(active=True)
    vehicles = query.order_by(Vehiculo.matricula.asc().nullslast(), Vehiculo.nombre.asc()).all()

    worker_id = None
    try:
        if worker_id_raw not in (None, '', 'null'):
            worker_id = int(worker_id_raw)
    except (TypeError, ValueError):
        worker_id = None

    fechas = []
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
            if end_date < start_date:
                start_date, end_date = end_date, start_date
            curr = start_date
            while curr <= end_date:
                fechas.append(curr)
                curr += timedelta(days=1)
        except ValueError:
            fechas = []

    results = []
    # Opción genérica: el jefe pide «cualquier coche»; flota elige al resolver.
    if not q or 'cualquier' in q or 'cualquiera' in q or 'generico' in q or 'genérico' in q:
        results.append({
            'id': 'CUALQUIERA',
            'text': '🚗 CUALQUIERA (solicitud genérica)',
        })

    for v in vehicles:
        text = v.label()
        if q and q not in text.lower() and q not in (v.marca or '').lower() and q not in (v.modelo or '').lower():
            continue
        if fechas:
            bloqueado = False
            for fecha in fechas:
                av = AsignacionVehiculo.query.filter_by(
                    vehiculo_id=v.id, fecha=fecha, estado='efectiva',
                ).first()
                if not av:
                    continue
                if worker_id is not None and av.user_id == worker_id:
                    continue
                if user_has_approved_leave(av.user_id, av.fecha):
                    continue
                bloqueado = True
                break
            if bloqueado:
                continue
        results.append({'id': v.id, 'text': text})

    return jsonify({'results': results})


@vehiculos_api.route('/v6/planificador/vehicle-action', methods=['POST'])
@login_required
def api_planificador_vehicle_action():
    if not can_plan_fleet(current_user):
        return jsonify({
            'success': False,
            'error': translate('No tienes permisos para asignar vehículos.'),
            'permission_denied': True,
        }), 403
    data = request.get_json() or {}
    worker_id = data.get('worker_id')
    vehicle_id = data.get('vehicle_id')
    start_date_str = data.get('start') or data.get('start_date')
    end_date_str = data.get('end') or data.get('end_date')
    include_weekends = data.get('include_weekends', False)
    overwrite_mode = data.get('overwrite_mode', 'check')
    notas = (data.get('notas') or '').strip() or None
    accion = (data.get('accion') or 'ASIGNAR').upper()

    from app.services.vehicle_assignment_service import _is_vehiculo_cualquiera
    if not worker_id or vehicle_id in (None, ''):
        return jsonify({'success': False, 'error': translate('Faltan worker_id o vehicle_id')}), 400
    if not start_date_str or not end_date_str:
        return jsonify({'success': False, 'error': translate('Faltan fechas start/end')}), 400

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'error': translate('Formato de fecha inválido')}), 400

    hoy = today_local()
    festivos_bd = Festivo.query.filter(
        Festivo.fecha >= start_date, Festivo.fecha <= end_date
    ).all()
    fechas_festivas = {f.fecha for f in festivos_bd}

    fechas = []
    curr = start_date
    while curr <= end_date:
        if curr >= hoy and (curr.weekday() < 5 or include_weekends) and curr not in fechas_festivas:
            fechas.append(curr)
        curr += timedelta(days=1)

    if not fechas:
        return jsonify({'success': False, 'error': translate('El rango no contiene días laborables válidos.')}), 400

    try:
        vid_arg = None if _is_vehiculo_cualquiera(vehicle_id) else int(vehicle_id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': translate('vehicle_id inválido')}), 400

    try:
        result = process_vehicle_assignment_action(
            actor_user=current_user,
            worker_id=int(worker_id),
            vehicle_id=vid_arg if vid_arg is not None else 'CUALQUIERA',
            date_list=fechas,
            notas=notas,
            overwrite_mode=overwrite_mode,
            accion=accion,
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

    status = 200 if result.get('success') or result.get('conflict') else 400
    return jsonify(result), status
