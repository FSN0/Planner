# app/api/vehiculos.py
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from app import db
from app.models import Vehiculo, Festivo, ROLE_ADMIN, ROLE_JEFE
from app.decorators import roles_required
from app.services.permission_service import is_laboral
from app.services.vehicle_assignment_service import process_vehicle_assignment_action
from app.utils.timezone_utils import today_local

vehiculos_api = Blueprint('vehiculos_api', __name__)


@vehiculos_api.route('/v6/vehicles', methods=['GET'])
@login_required
def api_list_vehicles():
    """Listado select2: {id, text: 'matricula — nombre'}."""
    q = (request.args.get('q') or '').strip().lower()
    query = Vehiculo.query.filter_by(active=True)
    vehicles = query.order_by(Vehiculo.matricula.asc().nullslast(), Vehiculo.nombre.asc()).all()

    results = []
    for v in vehicles:
        text = v.label()
        if q and q not in text.lower() and q not in (v.marca or '').lower() and q not in (v.modelo or '').lower():
            continue
        results.append({'id': v.id, 'text': text})

    return jsonify({'results': results})


@vehiculos_api.route('/v6/planificador/vehicle-action', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def api_planificador_vehicle_action():
    if is_laboral(current_user):
        return jsonify({'success': False, 'error': 'Perfil laboral sin permisos de edición.'}), 403
    data = request.get_json() or {}
    worker_id = data.get('worker_id')
    vehicle_id = data.get('vehicle_id')
    start_date_str = data.get('start') or data.get('start_date')
    end_date_str = data.get('end') or data.get('end_date')
    include_weekends = data.get('include_weekends', False)
    overwrite_mode = data.get('overwrite_mode', 'check')
    notas = (data.get('notas') or '').strip() or None
    accion = (data.get('accion') or 'ASIGNAR').upper()

    if not worker_id or not vehicle_id:
        return jsonify({'success': False, 'error': 'Faltan worker_id o vehicle_id'}), 400
    if not start_date_str or not end_date_str:
        return jsonify({'success': False, 'error': 'Faltan fechas start/end'}), 400

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'error': 'Formato de fecha inválido'}), 400

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
        return jsonify({'success': False, 'error': 'El rango no contiene días laborables válidos.'}), 400

    try:
        result = process_vehicle_assignment_action(
            actor_user=current_user,
            worker_id=int(worker_id),
            vehicle_id=int(vehicle_id),
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
