# app/api/asignaciones.py
from flask import Blueprint, request, jsonify, flash
from flask_login import login_required, current_user
from datetime import datetime, timedelta, date
import json

from app import db
from app.models import User, Obra, Asignacion, Solicitud, Festivo, ROLE_ADMIN, ROLE_JEFE
from app.decorators import roles_required

# --- Importamos los Servicios Limpios ---
from app.services.assignment_service import process_assignment_action, process_unassign_action
from app.services.solicitud_service import update_solicitudes_for_assignment, SolicitudService
from app.services.email_service import (
    notificar_resolucion_solicitud, 
    notificar_movimiento_admin_a_jo, 
    notificar_nueva_solicitud
)

# Definimos el nuevo mini-blueprint
asignaciones_api = Blueprint('asignaciones_api', __name__)

# ==============================================================================
# 1. RUTA UNIFICADA DE ASIGNACIÓN (Sustituye a /admin/assign_worker)
# ==============================================================================
@asignaciones_api.route("/v6/assign", methods=["POST"])
@login_required
def api_assign_worker():
    data = request.get_json() or {}
    try:
        worker_id = int(data.get("worker_id"))
        target_obra_id = int(data.get("target_obra_id") or data.get("obra_id"))
        selected_dates = data.get("selected_dates")
        mode = data.get("overwrite_mode", "check")

        # Compatibilidad con el formato antiguo (fecha inicio + número de días)
        if not selected_dates and data.get("selected_date"):
            start_str = data.get("selected_date")
            num = int(data.get("number_of_days", 1))
            s_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            selected_dates = [(s_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num)]

        if not selected_dates:
            raise ValueError("Fechas no proporcionadas")
            
    except (TypeError, ValueError) as e:
        return jsonify({"success": False, "message": f"Datos inválidos: {str(e)}"}), 400

    result = process_assignment_action(
        actor_user=current_user,
        worker_id=worker_id,
        target_obra_id=target_obra_id,
        date_list=selected_dates,
        mode=mode
    )
    
    status_code = 200 if result.get('success') or result.get('conflict') else 400
    return jsonify(result), status_code

# ==============================================================================
# 2. RUTA UNIFICADA DE DESASIGNACIÓN
# ==============================================================================
@asignaciones_api.route("/v6/unassign_worker", methods=["POST"])
@login_required
def api_unassign_worker():
    data = request.get_json() or {}
    worker_id = data.get('worker_id')
    obra_id = data.get('obra_id')
    dates = data.get('dates', [])
    mode = data.get('mode', 'selected')

    if not worker_id:
        return jsonify({'success': False, 'message': 'Faltan datos (worker_id)'}), 400

    try:
        result = process_unassign_action(
            actor_user=current_user,
            worker_id=worker_id,
            target_obra_id=obra_id,
            date_list=dates,
            mode=mode
        )
        status_code = 200 if result.get('success') else 400
        return jsonify(result), status_code
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# ==============================================================================
# 3. RUTA INTELIGENTE DE DÍAS SUELTOS (Con gestión de conflictos)
# ==============================================================================
@asignaciones_api.route("/v6/solicitudes/<int:solicitud_id>/asignar_parcial", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_solicitud_asignar_parcial(solicitud_id):
    solicitud = Solicitud.query.get_or_404(solicitud_id)
    data = request.get_json() or {}
    
    worker_id = data.get('worker_id')
    selected_dates = data.get('dates')
    mode = data.get('mode', 'overwrite') # Capturamos el mode del frontend

    if not worker_id or not selected_dates:
        return jsonify({'success': False, 'message': 'Faltan datos.'}), 400

    accion = getattr(solicitud, 'accion', 'ASIGNAR')
    count_processed = 0

    # A. EJECUTAR LA ACCIÓN EN BD
    if accion == 'DESASIGNAR':
        for d_str in selected_dates:
            try:
                d_obj = datetime.strptime(d_str, '%Y-%m-%d').date()
                asig = Asignacion.query.filter_by(user_id=int(worker_id), obra_id=solicitud.obra_id, fecha=d_obj).first()
                if asig:
                    db.session.delete(asig)
                    count_processed += 1
            except ValueError: 
                continue
    else:
        res = process_assignment_action(
            actor_user=current_user, 
            worker_id=int(worker_id),
            target_obra_id=solicitud.obra_id, 
            date_list=selected_dates, 
            mode=mode, 
            solicitud_id=solicitud.id
        )
        
        if res.get('conflict'):
            return jsonify(res) # Interceptamos el conflicto y lo mandamos a la UI
            
        if not res.get('success'):
            return jsonify(res), 400
            
        count_processed = len(selected_dates)

    # B. ACTUALIZAR LA SOLICITUD (EL "TACHADO" VISUAL)
    try:
        config = json.loads(solicitud.comentarios or '{}')
        pending_dates = config.get('dates', [])
    except:
        pending_dates = []

    if not pending_dates and solicitud.fecha_inicio and solicitud.fecha_fin:
        curr = solicitud.fecha_inicio
        while curr <= solicitud.fecha_fin:
            pending_dates.append(curr.strftime("%Y-%m-%d"))
            curr += timedelta(days=1)

    remaining_dates = [d for d in pending_dates if d not in selected_dates]
    new_config = {'mode': 'selected', 'dates': remaining_dates}
    solicitud.comentarios = json.dumps(new_config)

    # C. VERIFICAR SI SE CIERRA O QUEDA ABIERTA
    if len(remaining_dates) == 0:
        solicitud.estado = 'CUMPLIDA'
        solicitud.resolved_at = datetime.utcnow()
        solicitud.resolved_by_id = current_user.id
        msg = f"Acción completada ({count_processed} días). Solicitud cerrada."
        notificar_resolucion_solicitud(solicitud, current_user.name)
    else:
        if solicitud.estado == 'PENDIENTE': 
            solicitud.estado = 'EN_PROCESO'
        msg = f"Parcial realizado ({count_processed} días). Quedan {len(remaining_dates)} pendientes."

    db.session.commit()
    
    # Mantenemos el flash() para que al hacer reload el usuario vea el mensaje verde
    flash(msg, "success")
    return jsonify({'success': True})

# ==============================================================================
# 4. EL MOTOR DEL PLANIFICADOR (Arrastrar y Soltar)
# ==============================================================================
@asignaciones_api.route("/v6/planificador/action", methods=['POST'])
@login_required
def api_planificador_action():
    data = request.json
    worker_id = data.get('worker_id')
    target_obra_id = data.get('target_obra_id')
    old_obra_id = data.get('old_obra_id', target_obra_id)
    start_date_str = data.get('start_date')
    end_date_str = data.get('end_date')
    original_start_str = data.get('original_start')
    original_end_str = data.get('original_end')
    include_weekends = data.get('include_weekends', False)
    overwrite_mode = data.get('overwrite_mode', 'check') 
    
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        hoy = datetime.today().date()

        if str(worker_id) == 'GENERICO' and start_date < hoy:
            return jsonify({"success": False, "error": "No puedes solicitar personal en fechas pasadas."})

        obra = Obra.query.get(target_obra_id)
        if obra and obra.fecha_fin:
            if start_date > obra.fecha_fin:
                return jsonify({"success": False, "error": f"Imposible asignar. La obra finalizó el {obra.fecha_fin.strftime('%d/%m/%Y')}."})
            if end_date > obra.fecha_fin:
                end_date = obra.fecha_fin

        # Excluir fines de semana y festivos
        festivos_bd = Festivo.query.filter(Festivo.fecha >= start_date, Festivo.fecha <= end_date).all()
        fechas_festivas = [f.fecha for f in festivos_bd]

        fechas = []
        curr = start_date
        while curr <= end_date:
            if (curr.weekday() < 5 or include_weekends) and curr not in fechas_festivas:
                fechas.append(curr)
            curr += timedelta(days=1)

        if not fechas:
            return jsonify({"success": False, "error": "El rango no contiene días laborables válidos."})

        sol_baja_creada = False
        msg_baja = ""
        
        # --- LÓGICA DE BORRADO INTELIGENTE (Acortar / Desasignar) ---
        if original_start_str and original_end_str and str(worker_id) != 'GENERICO':
            orig_start = datetime.strptime(original_start_str, "%Y-%m-%d").date()
            orig_end = datetime.strptime(original_end_str, "%Y-%m-%d").date()
            
            fechas_a_borrar = []
            curr_borrar = orig_start
            while curr_borrar <= orig_end:
                if curr_borrar >= hoy:
                    if curr_borrar not in fechas:
                        if old_obra_id == target_obra_id or overwrite_mode == 'overwrite':
                            fechas_a_borrar.append(curr_borrar)
                curr_borrar += timedelta(days=1)

            if fechas_a_borrar:
                if current_user.role == ROLE_ADMIN:
                    Asignacion.query.filter(
                        Asignacion.user_id == worker_id,
                        Asignacion.obra_id == old_obra_id,
                        Asignacion.fecha.in_(fechas_a_borrar)
                    ).delete(synchronize_session=False)
                    db.session.commit()
                    
                    for d_borrada in fechas_a_borrar:
                        update_solicitudes_for_assignment(old_obra_id, int(worker_id), d_borrada, resolved_by_id=current_user.id)
                    
                    if old_obra_id != target_obra_id and overwrite_mode == 'overwrite':
                        worker = User.query.get(int(worker_id))
                        if worker:
                            worker_name = f"{worker.name} {worker.lastname}"
                            fechas_str = f"{len(fechas_a_borrar)} días movidos a otra obra."
                            notificar_movimiento_admin_a_jo(old_obra_id, worker_name, "Desasignar (Traslado)", fechas_str, current_user.name)
                            
                elif current_user.role == ROLE_JEFE:
                    # Deduplicación de solicitudes de baja del Jefe
                    dates_str = [d.strftime('%Y-%m-%d') for d in fechas_a_borrar]
                    existing_baja = Solicitud.query.filter_by(
                        tipo='CONCRETA', accion='DESASIGNAR', obra_id=old_obra_id, empleado_id=worker_id
                    ).filter(Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])).first()

                    if existing_baja:
                        existing_baja.fecha_inicio = min(existing_baja.fecha_inicio, min(fechas_a_borrar))
                        existing_baja.fecha_fin = max(existing_baja.fecha_fin, max(fechas_a_borrar))
                        try:
                            comentarios_json = json.loads(existing_baja.comentarios or '{}')
                            merged_dates = sorted(list(set(comentarios_json.get('dates', []) + dates_str)))
                            comentarios_json['dates'] = merged_dates
                            existing_baja.comentarios = json.dumps(comentarios_json)
                        except Exception: pass
                        
                        db.session.commit()
                        sol_baja_creada = True
                        msg_baja = "La solicitud de baja existente ha sido ampliada."
                    else:
                        comentarios_json = json.dumps({'mode': 'selected', 'dates': dates_str})
                        sol_baja = Solicitud(
                            tipo='CONCRETA', accion='DESASIGNAR', obra_id=old_obra_id,
                            requested_by_id=current_user.id, empleado_id=worker_id,
                            fecha_inicio=min(fechas_a_borrar), fecha_fin=max(fechas_a_borrar),
                            cantidad_solicitada=1, estado='PENDIENTE', comentarios=comentarios_json
                        )
                        db.session.add(sol_baja)
                        db.session.commit()
                        notificar_nueva_solicitud(sol_baja, current_user.name)
                        sol_baja_creada = True
                        msg_baja = "Se generó una solicitud de baja para los días recortados."

        # --- CONSTRUIR LOS DÍAS A ASIGNAR (Omitiendo los que ya estaban para la misma obra) ---
        orig_start = None
        orig_end = None
        if original_start_str and original_end_str:
            orig_start = datetime.strptime(original_start_str, "%Y-%m-%d").date()
            orig_end = datetime.strptime(original_end_str, "%Y-%m-%d").date()

        fechas_a_procesar = []
        for f in fechas:
            if f >= hoy:
                if old_obra_id == target_obra_id and orig_start and orig_end:
                    if orig_start <= f <= orig_end:
                        continue 
                fechas_a_procesar.append(f)
        
        if not fechas_a_procesar:
            if sol_baja_creada:
                return jsonify({"success": True, "action": "requested", "message": msg_baja})
            return jsonify({"success": True, "message": "No hubo cambios."})

        # --- LÓGICA DE AÑADIR/MOVER ---
        # --- LÓGICA DE AÑADIR/MOVER ---
        if str(worker_id) == 'GENERICO':
            detalles = data.get('detalles', 'Personal Genérico')
            cantidad_pedida = int(data.get('cantidad', 1)) # <--- CAPTURAMOS EL NÚMERO
            
            SolicitudService.create_solicitud_generica(
                solicitante_id=current_user.id, obra_id=target_obra_id,
                fecha_inicio=fechas_a_procesar[0], fecha_fin=fechas_a_procesar[-1],
                cantidad=cantidad_pedida, # <--- SE LO PASAMOS AL SERVICIO
                perfil=detalles, comentarios=f"Creado desde Planificador: {detalles}"
            )
            return jsonify({"success": True, "action": "requested_generic", "message": "Solicitud genérica enviada."})

        # --- LLAMADA AL MOTOR DE ASIGNACIONES ---
        result = process_assignment_action(
            actor_user=current_user, worker_id=int(worker_id), target_obra_id=target_obra_id,
            date_list=fechas_a_procesar, mode=overwrite_mode
        )
        
        # Combinar mensajes si se recortó y añadió a la vez
        if sol_baja_creada:
            base_msg = result.get('message', '')
            result['message'] = f"{msg_baja} {base_msg}"
            if result.get('action') == 'assigned':
                result['action'] = 'partial_request'
        
        if result.get('success') and str(worker_id) != 'GENERICO' and fechas_a_procesar and current_user.role == ROLE_ADMIN:
            worker = User.query.get(int(worker_id))
            if worker:
                worker_name = f"{worker.name} {worker.lastname}"
                fechas_str = f"Desde {fechas_a_procesar[0].strftime('%d/%m/%Y')} hasta {fechas_a_procesar[-1].strftime('%d/%m/%Y')}"
                notificar_movimiento_admin_a_jo(target_obra_id, worker_name, "Asignar (Planificador)", fechas_str, current_user.name)
        
        return jsonify(result)

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})
    
    
# app/api/asignaciones.py

@asignaciones_api.route("/v6/solicitudes/<int:solicitud_id>/asignar_candidatos", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_solicitud_asignar_candidatos(solicitud_id):
    """Asigna múltiples operarios desde una solicitud genérica."""
    solicitud = Solicitud.query.get_or_404(solicitud_id)
    data = request.get_json() or {}
    worker_ids = data.get('worker_ids', [])
    force_move = data.get('force_move', False)

    if not worker_ids:
        return jsonify({'success': False, 'message': 'No has seleccionado ningún trabajador.'}), 400

    dias = []
    curr = solicitud.fecha_inicio
    while curr <= solicitud.fecha_fin:
        dias.append(curr)
        curr += timedelta(days=1)

    count_exito = 0
    for wid in worker_ids:
        try:
            res = process_assignment_action(
                actor_user=current_user,
                worker_id=int(wid),
                target_obra_id=solicitud.obra_id,
                date_list=dias,
                overwrite=force_move,
                solicitud_id=solicitud.id # ATA LA ASIGNACIÓN A LA SOLICITUD
            )
            if res.get('success'):
                count_exito += 1
        except Exception as e:
            current_app.logger.error(f"Error al asignar en bloque: {e}")
            continue

    if count_exito > 0:
        db.session.commit()
        db.session.refresh(solicitud)
        
        # Centralizamos el cierre y notificación
        if solicitud.estado == 'CUMPLIDA':
            notificar_resolucion_solicitud(solicitud, current_user.name)
        
        flash(f'Se han procesado {count_exito} asignaciones.', 'success')
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'message': 'No se pudo asignar. Verifica conflictos.'}), 400


@asignaciones_api.route("/v6/solicitudes/<int:solicitud_id>/desasignar_candidato", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_solicitud_desasignar_candidato(solicitud_id):
    """Desasigna a un operario específico de una obra dentro del rango de la solicitud."""
    solicitud = Solicitud.query.get_or_404(solicitud_id)
    data = request.get_json() or {}
    worker_id = data.get('worker_id')

    if not worker_id:
        return jsonify({'success': False, 'message': 'Falta el ID del trabajador.'}), 400

    worker_id = int(worker_id)

    asignaciones = Asignacion.query.filter(
        Asignacion.obra_id == solicitud.obra_id,
        Asignacion.user_id == worker_id,
        Asignacion.fecha >= solicitud.fecha_inicio,
        Asignacion.fecha <= solicitud.fecha_fin
    ).all()
    
    if not asignaciones:
        return jsonify({'success': False, 'message': 'No se encontraron asignaciones para eliminar.'}), 400

    count = len(asignaciones)
    fechas_eliminadas = [a.fecha for a in asignaciones] 
    
    for a in asignaciones:
        db.session.delete(a)
    
    db.session.flush()
    
    # Llama al servicio centralizado para recalcular estados de la solicitud
    for d_obj in fechas_eliminadas:
        update_solicitudes_for_assignment(solicitud.obra_id, worker_id, d_obj, resolved_by_id=current_user.id)

    db.session.commit()
    
    flash(f"Se han eliminado {count} días de asignación y recalculado la solicitud.", "success")
    return jsonify({'success': True})


# app/api/asignaciones.py (al final del archivo)

@asignaciones_api.route("/v6/solicitudes/<int:solicitud_id>/resolver", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_resolver_solicitud(solicitud_id):
    """API unificada para Aceptar, Denegar o Reabrir solicitudes."""
    from app.services.solicitud_service import resolver_solicitud_admin
    
    solicitud = Solicitud.query.get_or_404(solicitud_id)
    data = request.get_json() or {}
    accion = data.get('accion')
    
    if not accion:
        return jsonify({'success': False, 'message': 'Falta la acción a realizar.'}), 400
        
    try:
        # Llamamos a nuestro servicio limpio
        mensaje = resolver_solicitud_admin(solicitud, accion, current_user)
        # Metemos un flash para que al hacer reload en el frontend, Flask muestre el mensajito verde
        flash(mensaje, "success" if accion in ['aceptar_concreta', 'reabrir'] else "warning")
        return jsonify({'success': True, 'message': mensaje})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400