# app/api/asignaciones.py
from flask import Blueprint, request, jsonify, flash
from flask_login import login_required, current_user
from datetime import datetime, timedelta, date
import json

from app import db
from app.models import User, Obra, Asignacion, Solicitud, Festivo, ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_OPERARIO
from app.decorators import roles_required

from app.services.assignment_service import process_assignment_action, process_unassign_action
from app.services.solicitud_service import (
    update_solicitudes_for_assignment,
    SolicitudService,
    merge_comentarios_dates,
    merge_notas,
    build_comentarios_config,
    log_nueva_solicitud,
)
from app.services.core_assignment_service import CoreAssignmentService
from app.services.email_service import (
    notificar_resolucion_solicitud, 
    notificar_movimiento_admin_a_jo, 
    notificar_nueva_solicitud
)
from app.services.permission_service import is_laboral, can_write_assignments, user_can
from app.services.i18n_service import translate

asignaciones_api = Blueprint('asignaciones_api', __name__)


def _assignment_mode_from_payload(data, default='check'):
    """overwrite solo después de que el usuario elija en el pop-up de conflicto."""
    mode = (data or {}).get('overwrite_mode', default) or default
    if mode == 'overwrite' and not (data or {}).get('conflict_resolved'):
        return 'check'
    return mode


def _parse_workers_payload(data):
    """
    Normaliza multi-trabajador desde el planificador.
    Acepta:
      - workers: [{worker_id, vehicle_id?}, ...]
      - worker_ids: [id, ...]
    Devuelve lista de dicts, o None si el payload es single worker_id (legacy).
    Lista vacía = clave presente pero sin trabajadores válidos.
    """
    if not data:
        return None

    has_batch_key = False
    raw_workers = data.get('workers')
    if isinstance(raw_workers, list):
        has_batch_key = True
        out = []
        for idx, item in enumerate(raw_workers):
            if isinstance(item, dict):
                wid = item.get('worker_id')
                vid = item.get('vehicle_id')
            else:
                wid = item
                vid = None
            if wid is None or str(wid) in ('', 'GENERICO'):
                continue
            try:
                entry = {'worker_id': int(wid), 'index': idx}
            except (TypeError, ValueError):
                continue
            if vid not in (None, '', 'null'):
                try:
                    entry['vehicle_id'] = int(vid)
                except (TypeError, ValueError):
                    pass
            out.append(entry)
        return out

    raw_ids = data.get('worker_ids')
    if isinstance(raw_ids, list):
        has_batch_key = True
        out = []
        for idx, wid in enumerate(raw_ids):
            if wid is None or str(wid) in ('', 'GENERICO'):
                continue
            try:
                out.append({'worker_id': int(wid), 'index': idx})
            except (TypeError, ValueError):
                continue
        return out

    return None if not has_batch_key else []


def _process_batch_planificador_assignments(
    *,
    actor_user,
    workers,
    target_obra_id,
    fechas_a_procesar,
    overwrite_mode,
    notas,
):
    """
    Asigna varios trabajadores al mismo rango de obra.
    Conflictos de ausencia (y otros) se reportan por fila sin abortar el lote.
    """
    from app.services.vehicle_assignment_service import process_vehicle_assignment_action

    results = []
    ok_count = 0
    fail_count = 0
    leave_fail_count = 0

    for entry in workers:
        wid = entry['worker_id']
        row = {
            'index': entry.get('index', 0),
            'worker_id': wid,
            'vehicle_id': entry.get('vehicle_id'),
            'success': False,
        }
        worker = User.query.get(wid)
        if worker:
            row['worker_name'] = f"{worker.name} {worker.lastname}".strip()
        else:
            row['worker_name'] = f'ID {wid}'

        try:
            result = process_assignment_action(
                actor_user=actor_user,
                worker_id=wid,
                target_obra_id=target_obra_id,
                date_list=list(fechas_a_procesar),
                mode=overwrite_mode,
                notas=notas,
            )
        except Exception as exc:
            db.session.rollback()
            row['success'] = False
            row['error'] = str(exc)
            fail_count += 1
            results.append(row)
            continue

        if result.get('success'):
            row['success'] = True
            row['message'] = result.get('message')
            row['action'] = result.get('action')
            ok_count += 1

            if actor_user.role == ROLE_ADMIN and fechas_a_procesar:
                fechas_str = (
                    f"Desde {fechas_a_procesar[0].strftime('%d/%m/%Y')} "
                    f"hasta {fechas_a_procesar[-1].strftime('%d/%m/%Y')}"
                )
                notificar_movimiento_admin_a_jo(
                    target_obra_id, row['worker_name'], "Asignar (Planificador)",
                    fechas_str, actor_user.name,
                )

            vehicle_id = entry.get('vehicle_id')
            if vehicle_id:
                vres = process_vehicle_assignment_action(
                    actor_user, wid, vehicle_id, list(fechas_a_procesar),
                    notas=notas, overwrite_mode=overwrite_mode, accion='ASIGNAR',
                )
                row['vehicle_result'] = {
                    'success': bool(vres.get('success')),
                    'message': vres.get('message') or vres.get('error'),
                    'conflict': bool(vres.get('conflict')),
                }
                if not vres.get('success'):
                    row['vehicle_ok'] = False
                else:
                    row['vehicle_ok'] = True
        else:
            row['success'] = False
            row['message'] = result.get('message') or result.get('error')
            row['conflict'] = bool(result.get('conflict'))
            row['conflict_type'] = result.get('conflict_type')
            row['conflict_details'] = result.get('conflict_details')
            row['leave_dates'] = result.get('leave_dates')
            fail_count += 1
            if result.get('conflict_type') == 'leave':
                leave_fail_count += 1

        results.append(row)

    any_ok = ok_count > 0
    parts = [translate('{count} asignado(s)', count=ok_count)]
    if fail_count:
        parts.append(translate('{count} con error', count=fail_count))
    if leave_fail_count:
        parts.append(translate('{count} por ausencia', count=leave_fail_count))

    return {
        'success': any_ok,
        'batch': True,
        'message': '; '.join(parts) + '.',
        'ok_count': ok_count,
        'fail_count': fail_count,
        'leave_fail_count': leave_fail_count,
        'results': results,
        # Compat: no disparar modal de conflicto global en lote
        'conflict': False,
    }


@asignaciones_api.route("/v6/assign", methods=["POST"])
@login_required
def api_assign_worker():
    if is_laboral(current_user):
        return jsonify({"success": False, "message": translate("Modo solo lectura para perfil laboral.")}), 403
    if not can_write_assignments(current_user):
        return jsonify({
            "success": False,
            "message": translate("No tienes permisos de escritura para asignar personal."),
            "permission_denied": True,
        }), 403
    data = request.get_json() or {}
    try:
        worker_id = int(data.get("worker_id"))
        target_obra_id = int(data.get("target_obra_id") or data.get("obra_id"))
        selected_dates = data.get("selected_dates")
        mode = _assignment_mode_from_payload(data, "check")

        if not selected_dates and data.get("selected_date"):
            start_str = data.get("selected_date")
            num = int(data.get("number_of_days", 1))
            s_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            selected_dates = [(s_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num)]

        if not selected_dates:
            raise ValueError(translate("Fechas no proporcionadas"))
            
    except (TypeError, ValueError) as e:
        return jsonify({"success": False, "message": translate("Datos inválidos: {error}", error=str(e))}), 400

    result = process_assignment_action(
        actor_user=current_user,
        worker_id=worker_id,
        target_obra_id=target_obra_id,
        date_list=selected_dates,
        mode=mode
    )
    
    status_code = 200 if result.get('success') or result.get('conflict') else 400
    return jsonify(result), status_code


@asignaciones_api.route("/v6/free_workers", methods=["GET"])
@login_required
def api_free_workers():
    """Operarios libres en una fecha (picker móvil tablero/planificador)."""
    if is_laboral(current_user):
        return jsonify({"success": False, "message": translate("Modo solo lectura.")}), 403
    if not can_write_assignments(current_user):
        return jsonify({
            "success": False,
            "message": translate("No tienes permisos para asignar personal."),
            "permission_denied": True,
        }), 403

    raw = (request.args.get("date") or "").strip()
    try:
        selected = datetime.strptime(raw, "%Y-%m-%d").date() if raw else date.today()
    except ValueError:
        return jsonify({"success": False, "message": translate("Fecha inválida.")}), 400

    busy_ids = {
        row.user_id
        for row in Asignacion.query.filter_by(fecha=selected).all()
    }
    operarios = (
        User.query.filter_by(role=ROLE_OPERARIO, active=True, is_deleted=False)
        .order_by(User.name, User.lastname)
        .all()
    )
    workers = []
    for w in operarios:
        if w.id in busy_ids:
            continue
        comp = w.company_rel
        workers.append({
            "id": w.id,
            "name": f"{w.name} {w.lastname}".strip(),
            "company": (comp.code if comp and comp.code else "") or (
                comp.nombre if comp else translate("Ext")
            ),
        })

    return jsonify({
        "success": True,
        "date": selected.isoformat(),
        "workers": workers,
    })


@asignaciones_api.route("/v6/unassign_worker", methods=["POST"])
@login_required
def api_unassign_worker():
    if is_laboral(current_user):
        return jsonify({'success': False, 'message': translate('Modo solo lectura para perfil laboral.')}), 403
    if not can_write_assignments(current_user):
        return jsonify({
            'success': False,
            'message': translate('No tienes permisos de escritura para desasignar personal.'),
            'permission_denied': True,
        }), 403
    data = request.get_json() or {}
    worker_id = data.get('worker_id')
    obra_id = data.get('obra_id')
    dates = data.get('dates', [])
    mode = data.get('mode', 'selected')

    if not worker_id:
        return jsonify({'success': False, 'message': translate('Faltan datos (worker_id)')}), 400

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

@asignaciones_api.route("/v6/solicitudes/<int:solicitud_id>/asignar_parcial", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_solicitud_asignar_parcial(solicitud_id):
    solicitud = Solicitud.query.get_or_404(solicitud_id)
    data = request.get_json() or {}
    
    worker_id = data.get('worker_id')
    selected_dates = data.get('dates')
    mode = data.get('mode', 'overwrite')

    if not worker_id or not selected_dates:
        return jsonify({'success': False, 'message': translate('Faltan datos.')}), 400

    accion = getattr(solicitud, 'accion', 'ASIGNAR')
    count_processed = 0

    # =========================================================================
    # LÓGICA EXCLUSIVA PARA DESASIGNACIONES (BAJAS) - BYPASS DE CONFLICTOS
    # =========================================================================
    if accion == 'DESASIGNAR':
        fechas_ok = []
        for d_str in selected_dates:
            try:
                d_obj = datetime.strptime(d_str, '%Y-%m-%d').date()
                borrado = CoreAssignmentService.desasignar(
                    int(worker_id), solicitud.obra_id, d_obj, current_user.id,
                    "Resolución de Solicitud de Baja",
                    registrar_log=False,
                )
                if borrado:
                    count_processed += 1
                    fechas_ok.append(d_obj)
            except ValueError: 
                continue

        if count_processed and fechas_ok:
            fechas_ok = sorted(set(fechas_ok))
            CoreAssignmentService.registrar_log_rango(
                int(worker_id), solicitud.obra_id,
                fechas_ok[0], fechas_ok[-1], count_processed,
                current_user.id, "Resolución de Solicitud de Baja", False,
                fechas=fechas_ok,
            )
        
        # Mandamos recalcular al motor puro de coberturas
        for d_str in selected_dates:
            try:
                d_obj = datetime.strptime(d_str, '%Y-%m-%d').date()
                update_solicitudes_for_assignment(solicitud.obra_id, int(worker_id), d_obj, resolved_by_id=current_user.id)
            except ValueError:
                pass
                
        db.session.commit()
        db.session.refresh(solicitud)
        
        # El motor ya ha evaluado si quedan asignaciones. Si es 0, la habrá puesto como CUMPLIDA.
        if solicitud.estado == 'CUMPLIDA':
            msg = translate(
                'Baja procesada ({count} días). Ya no hay asignaciones, solicitud cerrada.',
                count=count_processed,
            )
        else:
            msg = translate(
                'Se borraron {count} días, pero siguen quedando días asignados a este trabajador.',
                count=count_processed,
            )
            
        flash(msg, "success")
        return jsonify({'success': True})
    
    # =========================================================================
    # LÓGICA ORIGINAL PARA ASIGNACIONES (ALTAS)
    # =========================================================================
    if getattr(solicitud, 'tipo', '') == 'GENERICA':
        requested = solicitud.cantidad_solicitada or 1
        valid_selected_dates = []
        for d_str in selected_dates:
            try:
                d_obj = datetime.strptime(d_str, '%Y-%m-%d').date()
                existing = Asignacion.query.filter_by(user_id=int(worker_id), obra_id=solicitud.obra_id, fecha=d_obj).first()
                if existing and existing.solicitud_id is None:
                    existing.solicitud_id = solicitud.id
                    db.session.add(existing)
                    db.session.flush()

                asignados_actuales = Asignacion.query.filter_by(
                    obra_id=solicitud.obra_id, solicitud_id=solicitud.id, fecha=d_obj
                ).count()
                
                if asignados_actuales < requested:
                    valid_selected_dates.append(d_str)
            except ValueError:
                continue
                
        if not valid_selected_dates:
            return jsonify({'success': False, 'message': translate('Los días seleccionados ya tienen el cupo completo.')}), 400
        
        selected_dates = valid_selected_dates

    res = process_assignment_action(
        actor_user=current_user, 
        worker_id=int(worker_id),
        target_obra_id=solicitud.obra_id, 
        date_list=selected_dates, 
        mode=mode, 
        solicitud_id=solicitud.id
    )
    
    if res.get('conflict'): return jsonify(res) 
    if not res.get('success'): return jsonify(res), 400
    count_processed = len(selected_dates)

    if solicitud.tipo == "CONCRETA":
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

        if len(remaining_dates) == 0:
            solicitud.estado = 'CUMPLIDA'
            from app.utils.timezone_utils import utc_now
            solicitud.resolved_at = utc_now()
            solicitud.resolved_by_id = current_user.id
            msg = translate(
                'Acción completada ({count} días). Solicitud cerrada.',
                count=count_processed,
            )
            notificar_resolucion_solicitud(solicitud, current_user.name)
        else:
            if solicitud.estado == 'PENDIENTE': solicitud.estado = 'EN_PROCESO'
            msg = translate(
                'Parcial realizado ({count} días). Quedan {remaining} pendientes.',
                count=count_processed,
                remaining=len(remaining_dates),
            )
    else:
        db.session.refresh(solicitud)
        if solicitud.estado == 'CUMPLIDA':
            msg = translate(
                'Asignación completada ({count} días). Cupo de la solicitud lleno.',
                count=count_processed,
            )
        else:
            msg = translate(
                'Asignación inteligente ({count} días). Progreso: {cubierta} de {solicitada} cubiertos.',
                count=count_processed,
                cubierta=solicitud.cantidad_cubierta,
                solicitada=solicitud.cantidad_solicitada,
            )

    db.session.commit()
    flash(msg, "success")
    return jsonify({'success': True})

@asignaciones_api.route("/v6/planificador/action", methods=['POST'])
@login_required
def api_planificador_action():
    if is_laboral(current_user):
        return jsonify({"success": False, "error": translate("Perfil laboral sin permisos de edición.")}), 403
    if not can_write_assignments(current_user):
        return jsonify({
            "success": False,
            "error": translate("No tienes permisos de escritura para asignar o mover personal."),
            "message": translate("No tienes permisos de escritura para asignar o mover personal."),
            "permission_denied": True,
        }), 403
    data = request.json or {}
    worker_id = data.get('worker_id')

    def _as_int_id(raw, default=None):
        if raw in (None, '', 'null', 'undefined'):
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    target_obra_id = _as_int_id(data.get('target_obra_id'))
    old_obra_id = _as_int_id(data.get('old_obra_id'), target_obra_id)
    start_date_str = data.get('start_date')
    end_date_str = data.get('end_date')
    original_start_str = data.get('original_start')
    original_end_str = data.get('original_end')
    include_weekends = data.get('include_weekends', False)
    overwrite_mode = _assignment_mode_from_payload(data, 'check')
    notas = (data.get('notas') or '').strip() or None

    if target_obra_id is None:
        return jsonify({"success": False, "error": translate("Obra destino no válida.")})
    
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        from app.utils.timezone_utils import today_local
        hoy = today_local()

        if str(worker_id) == 'GENERICO' and start_date < hoy:
            return jsonify({"success": False, "error": translate("No puedes solicitar personal en fechas pasadas.")})

        obra = Obra.query.get(target_obra_id)
        if obra and obra.fecha_fin:
            if start_date > obra.fecha_fin:
                return jsonify({"success": False, "error": translate("Imposible asignar. La obra finalizó el {date}.", date=obra.fecha_fin.strftime('%d/%m/%Y'))})
            if end_date > obra.fecha_fin:
                end_date = obra.fecha_fin

        festivos_bd = Festivo.query.filter(Festivo.fecha >= start_date, Festivo.fecha <= end_date).all()
        fechas_festivas = [f.fecha for f in festivos_bd]

        fechas = []
        curr = start_date
        while curr <= end_date:
            if (curr.weekday() < 5 or include_weekends) and curr not in fechas_festivas:
                fechas.append(curr)
            curr += timedelta(days=1)

        if not fechas:
            return jsonify({"success": False, "error": translate("El rango no contiene días laborables válidos.")})

        sol_baja_creada = False
        msg_baja = ""
        
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
                    for d_borrar in fechas_a_borrar:
                        CoreAssignmentService.desasignar(
                            int(worker_id), old_obra_id, d_borrar, current_user.id,
                            "Planificación Manual", "Recorte de rango desde planificador.",
                            registrar_log=False,
                        )
                    if fechas_a_borrar:
                        CoreAssignmentService.registrar_log_rango(
                            int(worker_id), old_obra_id,
                            min(fechas_a_borrar), max(fechas_a_borrar), len(fechas_a_borrar),
                            current_user.id, "Planificación Manual", False,
                            detalle_extra="Recorte de rango desde planificador.",
                            fechas=fechas_a_borrar,
                        )
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
                    dates_str = [d.strftime('%Y-%m-%d') for d in fechas_a_borrar]
                    existing_baja = Solicitud.query.filter_by(
                        tipo='CONCRETA', accion='DESASIGNAR', obra_id=old_obra_id, empleado_id=worker_id
                    ).filter(Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])).first()

                    if existing_baja:
                        existing_baja.fecha_inicio = min(existing_baja.fecha_inicio, min(fechas_a_borrar))
                        existing_baja.fecha_fin = max(existing_baja.fecha_fin, max(fechas_a_borrar))
                        existing_baja.comentarios = merge_comentarios_dates(existing_baja.comentarios, dates_str)
                        existing_baja.notas = merge_notas(existing_baja.notas, notas)
                        db.session.commit()
                        sol_baja_creada = True
                        msg_baja = translate("La solicitud de baja existente ha sido ampliada.")
                    else:
                        sol_baja = Solicitud(
                            tipo='CONCRETA', accion='DESASIGNAR', obra_id=old_obra_id,
                            requested_by_id=current_user.id, empleado_id=worker_id,
                            fecha_inicio=min(fechas_a_borrar), fecha_fin=max(fechas_a_borrar),
                            cantidad_solicitada=1, estado='PENDIENTE',
                            comentarios=build_comentarios_config(dates_str),
                            notas=notas,
                        )
                        db.session.add(sol_baja)
                        db.session.commit()
                        log_nueva_solicitud(sol_baja)
                        notificar_nueva_solicitud(sol_baja, current_user.name)
                        sol_baja_creada = True
                        msg_baja = translate("Se generó una solicitud de baja para los días recortados.")

        orig_start = None
        orig_end = None
        if original_start_str and original_end_str:
            orig_start = datetime.strptime(original_start_str, "%Y-%m-%d").date()
            orig_end = datetime.strptime(original_end_str, "%Y-%m-%d").date()

        # Traslado entre obras: hay que procesar TODOS los días del rango destino.
        # El skip "ya estaba en este rango" solo aplica al redimensionar en la MISMA obra.
        same_obra_move = old_obra_id == target_obra_id
        fechas_a_procesar = []
        for f in fechas:
            if f >= hoy:
                if same_obra_move and orig_start and orig_end:
                    if orig_start <= f <= orig_end:
                        continue
                fechas_a_procesar.append(f)

        if not fechas_a_procesar:
            if sol_baja_creada:
                return jsonify({"success": True, "action": "requested", "message": msg_baja})
            return jsonify({
                "success": True,
                "noop": True,
                "unchanged": True,
                "message": translate("No hubo cambios."),
            })

        batch_workers = _parse_workers_payload(data)
        if batch_workers is not None:
            if not batch_workers:
                return jsonify({"success": False, "error": translate("No hay trabajadores válidos en la lista.")})
            batch_result = _process_batch_planificador_assignments(
                actor_user=current_user,
                workers=batch_workers,
                target_obra_id=target_obra_id,
                fechas_a_procesar=fechas_a_procesar,
                overwrite_mode=overwrite_mode,
                notas=notas,
            )
            return jsonify(batch_result)

        if str(worker_id) == 'GENERICO':
            from app.services.tenant_modules import jefe_sin_buzon_solicitudes
            if jefe_sin_buzon_solicitudes(current_user):
                return jsonify({
                    "success": False,
                    "error": translate("Asigna personas concretas en el cuadrante. El buzón de solicitudes no aplica para jefes de obra."),
                })
            detalles = data.get('detalles', 'Personal Genérico')
            cantidad_pedida = int(data.get('cantidad', 1))
            
            SolicitudService.create_solicitud_generica(
                solicitante_id=current_user.id, obra_id=target_obra_id,
                fecha_inicio=fechas_a_procesar[0], fecha_fin=fechas_a_procesar[-1],
                cantidad=cantidad_pedida,
                perfil=detalles, notas=notas, fechas_explicitas=fechas_a_procesar,
            )
            return jsonify({"success": True, "action": "requested_generic", "message": translate("Solicitud genérica enviada.")})

        result = process_assignment_action(
            actor_user=current_user, worker_id=int(worker_id), target_obra_id=target_obra_id,
            date_list=fechas_a_procesar, mode=overwrite_mode, notas=notas,
        )
        if sol_baja_creada:
            base_msg = result.get('message', '')
            result['message'] = f"{msg_baja} {base_msg}"
            if result.get('action') == 'assigned':
                result['action'] = 'partial_request'
        
        if result.get('success') and str(worker_id) != 'GENERICO' and fechas_a_procesar and current_user.role == ROLE_ADMIN:
            try:
                worker = User.query.get(int(worker_id))
                if worker:
                    worker_name = f"{worker.name} {worker.lastname}"
                    fechas_str = f"Desde {fechas_a_procesar[0].strftime('%d/%m/%Y')} hasta {fechas_a_procesar[-1].strftime('%d/%m/%Y')}"
                    notificar_movimiento_admin_a_jo(
                        target_obra_id, worker_name, "Asignar (Planificador)",
                        fechas_str, current_user.name,
                    )
            except Exception:
                pass
        
        return jsonify(result)

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})

@asignaciones_api.route("/v6/solicitudes/<int:solicitud_id>/asignar_candidatos", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_solicitud_asignar_candidatos(solicitud_id):
    solicitud = Solicitud.query.get_or_404(solicitud_id)
    data = request.get_json() or {}
    worker_ids = data.get('worker_ids', [])
    force_move = data.get('force_move', False)

    if not worker_ids:
        return jsonify({'success': False, 'message': translate('No has seleccionado ningún trabajador.')}), 400

    dias_base = []
    try:
        config = json.loads(solicitud.comentarios or '{}')
        fechas_json = config.get('original_dates') or config.get('dates', [])
        if fechas_json:
            dias_base = [datetime.strptime(d, '%Y-%m-%d').date() for d in fechas_json if solicitud.fecha_inicio <= datetime.strptime(d, '%Y-%m-%d').date() <= solicitud.fecha_fin]
    except Exception:
        pass

    if not dias_base:
        festivos = Festivo.query.filter(Festivo.fecha >= solicitud.fecha_inicio, Festivo.fecha <= solicitud.fecha_fin).all()
        fechas_festivas = [f.fecha for f in festivos]
        curr = solicitud.fecha_inicio
        while curr <= solicitud.fecha_fin:
            if curr.weekday() < 5 and curr not in fechas_festivas:
                dias_base.append(curr)
            curr += timedelta(days=1)

    count_exito = 0
    # Obtenemos qué tipo de acción es la solicitud antes de entrar al bucle
    accion = getattr(solicitud, 'accion', 'ASIGNAR') 
    
    for wid in worker_ids:
        try:
            # =========================================================================
            # BLOQUE NUEVO: BYPASS PARA SOLICITUDES DE DESASIGNACIÓN (BAJAS)
            # =========================================================================
            if accion == 'DESASIGNAR':
                asignaciones_a_borrar = Asignacion.query.filter(
                    Asignacion.obra_id == solicitud.obra_id,
                    Asignacion.user_id == int(wid),
                    Asignacion.fecha.in_(dias_base)
                ).all()
                
                if asignaciones_a_borrar:
                    fechas = sorted({a.fecha for a in asignaciones_a_borrar})
                    for a in asignaciones_a_borrar:
                        CoreAssignmentService.desasignar(
                            a.user_id, a.obra_id, a.fecha, current_user.id,
                            "Resolución de Solicitud de Baja",
                            registrar_log=False,
                        )
                    CoreAssignmentService.registrar_log_rango(
                        int(wid), solicitud.obra_id,
                        fechas[0], fechas[-1], len(asignaciones_a_borrar),
                        current_user.id, "Resolución de Solicitud de Baja", False,
                        fechas=fechas,
                    )
                    count_exito += 1
                    
                continue # Saltamos a la siguiente iteración del for, no validamos nada más
            # =========================================================================

            dias_para_este_trabajador = []
            
            # LÓGICA ESTRICTA DÍA A DÍA (Solo para asignaciones reales)
            if solicitud.tipo == "GENERICA":
                requested = solicitud.cantidad_solicitada or 1
                for d_obj in dias_base:
                    # Auto-Corrección: Si el simulador JS lo insertó libre, lo atamos
                    existing = Asignacion.query.filter_by(user_id=int(wid), obra_id=solicitud.obra_id, fecha=d_obj).first()
                    if existing and existing.solicitud_id is None:
                        existing.solicitud_id = solicitud.id
                        db.session.add(existing)
                        db.session.flush()
                        
                    asignados_actuales = Asignacion.query.filter_by(
                        obra_id=solicitud.obra_id, solicitud_id=solicitud.id, fecha=d_obj
                    ).count()
                    
                    if asignados_actuales < requested:
                        dias_para_este_trabajador.append(d_obj.strftime("%Y-%m-%d"))
            else:
                for d_obj in dias_base:
                    existing = Asignacion.query.filter_by(user_id=int(wid), obra_id=solicitud.obra_id, fecha=d_obj).first()
                    if existing and existing.solicitud_id is None:
                        existing.solicitud_id = solicitud.id
                        db.session.add(existing)
                        db.session.flush()
                dias_para_este_trabajador = [d.strftime("%Y-%m-%d") for d in dias_base]

            if not dias_para_este_trabajador:
                # El operario se salta porque ya no queda hueco para él en ninguno de los días
                continue
                
            res = process_assignment_action(
                actor_user=current_user,
                worker_id=int(wid),
                target_obra_id=solicitud.obra_id,
                date_list=dias_para_este_trabajador,
                overwrite=force_move,
                solicitud_id=solicitud.id # <-- SIEMPRE PASAMOS EL ID PARA ATARLO
            )
            
            if res.get('success') or (existing and existing.solicitud_id == solicitud.id):
                count_exito += 1
                db.session.flush()
                    
        except Exception as e:
            continue

    if count_exito > 0:
        db.session.commit()
        db.session.refresh(solicitud)
        
        # Le decimos al motor que recalcule visuales
        for d_obj in dias_base:
            update_solicitudes_for_assignment(solicitud.obra_id, int(worker_ids[0]), d_obj, resolved_by_id=current_user.id)
            
        db.session.commit()
        db.session.refresh(solicitud)
        
        if solicitud.estado == 'CUMPLIDA':
            try:
                from app.services.email_service import notificar_resolucion_solicitud
                notificar_resolucion_solicitud(solicitud, current_user.name)
            except Exception:
                pass

        accion_txt = translate("desasignaciones") if accion == 'DESASIGNAR' else translate("asignaciones")
        flash(translate('Se han procesado {count} {accion} correctamente.', count=count_exito, accion=accion_txt), 'success')
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'message': translate('No hay hueco en ningún día de esta solicitud o ya estaban cubiertos.')}), 400

@asignaciones_api.route("/v6/solicitudes/<int:solicitud_id>/desasignar_candidato", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_solicitud_desasignar_candidato(solicitud_id):
    solicitud = Solicitud.query.get_or_404(solicitud_id)
    data = request.get_json() or {}
    worker_id = data.get('worker_id')

    if not worker_id:
        return jsonify({'success': False, 'message': translate('Falta el ID del trabajador.')}), 400

    worker_id = int(worker_id)

    asignaciones = Asignacion.query.filter(
        Asignacion.obra_id == solicitud.obra_id,
        Asignacion.user_id == worker_id,
        Asignacion.fecha >= solicitud.fecha_inicio,
        Asignacion.fecha <= solicitud.fecha_fin
    ).all()
    
    if not asignaciones:
        return jsonify({'success': False, 'message': translate('No se encontraron asignaciones para eliminar.')}), 400

    count = len(asignaciones)
    fechas_eliminadas = [a.fecha for a in asignaciones]
    fechas_sorted = sorted(set(fechas_eliminadas))

    for a in asignaciones:
        CoreAssignmentService.desasignar(
            a.user_id, a.obra_id, a.fecha, current_user.id,
            "Desasignación de Candidato",
            registrar_log=False,
        )
    if count and fechas_sorted:
        CoreAssignmentService.registrar_log_rango(
            worker_id, solicitud.obra_id,
            fechas_sorted[0], fechas_sorted[-1], count,
            current_user.id, "Desasignación de Candidato", False,
            fechas=fechas_sorted,
        )
    
    for d_obj in fechas_eliminadas:
        update_solicitudes_for_assignment(solicitud.obra_id, worker_id, d_obj, resolved_by_id=current_user.id)

    db.session.commit()
    
    flash(translate("Se han eliminado {count} días de asignación y recalculado la solicitud.", count=count), "success")
    return jsonify({'success': True})

@asignaciones_api.route("/v6/solicitudes/<int:solicitud_id>/resolver", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_resolver_solicitud(solicitud_id):
    from app.services.solicitud_service import resolver_solicitud_admin
    
    solicitud = Solicitud.query.get_or_404(solicitud_id)
    data = request.get_json() or {}
    accion = data.get('accion')
    
    if not accion:
        return jsonify({'success': False, 'message': translate('Falta la acción a realizar.')}), 400
        
    try:
        mensaje = resolver_solicitud_admin(solicitud, accion, current_user, target_obra_id=data.get('target_obra_id'))
        flash(translate(mensaje), "success" if accion in ['aceptar_concreta', 'aceptar_concreta_traslado', 'reabrir'] else "warning")
        return jsonify({'success': True, 'message': translate(mensaje)})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': translate('Error del servidor: {error}', error=e)}), 500