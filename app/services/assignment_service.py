# app/services/assignment_service.py

from datetime import datetime, date
from app import db
from app.models import Asignacion, Solicitud, Obra, User, ROLE_ADMIN, ROLE_JEFE, ConfiguracionGlobal
from app.services.solicitud_service import (
    update_solicitudes_for_assignment,
    build_comentarios_config,
    merge_comentarios_dates,
    merge_notas,
    log_nueva_solicitud,
)
from app.services.email_service import send_email, notificar_nueva_solicitud, notificar_traslado_interno
from app.services.core_assignment_service import CoreAssignmentService
from app.utils.timezone_utils import today_local

def process_assignment_action(actor_user, worker_id, target_obra_id, date_list, mode='check', overwrite=None, solicitud_id=None, notas=None):
    if overwrite is True:
        mode = 'overwrite'
    elif overwrite is False:
        mode = 'keep_both'

    worker = User.query.get(worker_id)
    target_obra = Obra.query.get(target_obra_id)

    if not worker or not target_obra:
        return {'success': False, 'error': 'Trabajador u Obra no encontrados'}

    valid_dates = []
    for d in date_list:
        if isinstance(d, str):
            try:
                valid_dates.append(datetime.strptime(d, "%Y-%m-%d").date())
            except ValueError:
                continue
        elif isinstance(d, date):
            valid_dates.append(d)
    
    valid_dates = sorted(list(set(valid_dates)))
    if not valid_dates:
        return {'success': False, 'error': 'No hay fechas válidas'}

    # Bloqueo duro: no asignar a obra si hay ausencia aprobada (igual que flota).
    from app.services.leave_service import user_has_approved_leave
    leave_dates = [d for d in valid_dates if user_has_approved_leave(worker.id, d)]
    if leave_dates:
        sample = ', '.join(d.strftime('%d/%m') for d in leave_dates[:5])
        extra = f' (+{len(leave_dates) - 5} más)' if len(leave_dates) > 5 else ''
        return {
            'success': False,
            'conflict': True,
            'conflict_type': 'leave',
            'message': (
                f'El trabajador tiene ausencia aprobada el/los día(s) {sample}{extra}. '
                'No se puede asignar a obra (igual que con vehículos). '
                'Cancela la ausencia o elige otras fechas.'
            ),
            'leave_dates': [d.isoformat() for d in leave_dates],
            'req_count': len(leave_dates),
        }

    # ==========================================
    # LÓGICA DE ADMINISTRADOR (Modo Dios)
    # ==========================================
    if actor_user.role == ROLE_ADMIN:
        if mode in ['check', 'pure_check']:
            conflict_details = {}
            count_conflict = 0
            
            for d in valid_dates:
                asigs = Asignacion.query.filter_by(user_id=worker.id, fecha=d).all()
                asigs_reales = [a for a in asigs if a.obra_id != target_obra.id]

                if asigs_reales:
                    count_conflict += 1
                    for a in asigs_reales:
                        obra_ocupada = Obra.query.get(a.obra_id)
                        obra_str = obra_ocupada.nombre if obra_ocupada else "Otra Obra"
                        if obra_str not in conflict_details: conflict_details[obra_str] = []
                        if d.strftime('%d/%m') not in conflict_details[obra_str]:
                            conflict_details[obra_str].append(d.strftime('%d/%m'))
                            
            if count_conflict > 0:
                return {
                    'success': False, 
                    'conflict': True, 
                    'conflict_type': 'admin_hard',
                    'message': f'El trabajador ya está ocupado {count_conflict} día(s) en estas fechas en otras obras.',
                    'conflict_details': conflict_details,
                    'req_count': count_conflict
                }
            
            # FIX: Si solo era un simulacro, devolvemos OK sin tocar la BD
            if mode == 'pure_check':
                return {'success': True, 'message': 'Sin conflictos'}
                
            return _handle_direct_assignment(actor_user, worker, target_obra, valid_dates, overwrite=False, solicitud_id=solicitud_id)
            
        elif mode == 'overwrite':
            return _handle_direct_assignment(actor_user, worker, target_obra, valid_dates, overwrite=True, solicitud_id=solicitud_id)
        elif mode == 'keep_both':
            return _handle_direct_assignment(actor_user, worker, target_obra, valid_dates, overwrite=False, solicitud_id=solicitud_id)
        elif mode == 'only_free':
            free_dates = []
            for d in valid_dates:
                asigs = Asignacion.query.filter_by(user_id=worker.id, fecha=d).all()
                asigs_reales = [a for a in asigs if a.obra_id != target_obra.id]
                if not asigs_reales:
                    free_dates.append(d)

            if free_dates:
                res = _handle_direct_assignment(actor_user, worker, target_obra, free_dates, overwrite=False, solicitud_id=solicitud_id)
                res['message'] = f"Asignados {len(free_dates)} día(s) libre(s). Los ocupados en otras obras se ignoraron."
                return res
            else:
                return {'success': True, 'action': 'assigned', 'message': 'No quedaban días libres. No se asignó nada nuevo.'}

    # ==========================================
    # LÓGICA DE JEFE DE OBRA
    # ==========================================
    elif actor_user.role == ROLE_JEFE:
        if target_obra.jefe_obra_id != actor_user.id:
            return {'success': False, 'error': 'No tienes permiso sobre la obra destino.'}

        conf_custodia = ConfiguracionGlobal.query.filter_by(clave='limite_custodia').first()
        limite_dias = int(conf_custodia.valor) if conf_custodia and conf_custodia.valor.isdigit() else 15

        start_date = valid_dates[0]
        tiene_custodia = False
        
        last_asig = Asignacion.query.filter(
            Asignacion.user_id == worker.id, 
            Asignacion.fecha < start_date
        ).order_by(Asignacion.fecha.desc()).first()

        if last_asig:
            dias_diff = (start_date - last_asig.fecha).days
            if dias_diff <= limite_dias:
                asigs_ultimo_dia = Asignacion.query.filter_by(user_id=worker.id, fecha=last_asig.fecha).all()
                for asig in asigs_ultimo_dia:
                    obra_historial = Obra.query.get(asig.obra_id)
                    if obra_historial and obra_historial.jefe_obra_id == actor_user.id:
                        tiene_custodia = True
                        break 
        else:
            tiene_custodia = False

        dias_auto = []
        dias_solicitud = []
        conflict_details = {} 
        obras_origen_traslado = set() 
        
        for d in valid_dates:
            asigs_dia = Asignacion.query.filter_by(user_id=worker.id, fecha=d).all()
            
            if not asigs_dia:
                if tiene_custodia:
                    dias_auto.append(d)
                else:
                    dias_solicitud.append(d)
                    cat_name = "Libre (Falta custodia)"
                    if cat_name not in conflict_details: conflict_details[cat_name] = []
                    conflict_details[cat_name].append(d.strftime('%d/%m'))
            else:
                es_mio = False
                nombres_ajenas = []
                for a in asigs_dia:
                    obra_ocupada = Obra.query.get(a.obra_id)
                    if obra_ocupada and obra_ocupada.jefe_obra_id == actor_user.id:
                        es_mio = True
                        if obra_ocupada.id != target_obra.id:
                            obras_origen_traslado.add(obra_ocupada.nombre)
                    elif obra_ocupada:
                        nombres_ajenas.append(obra_ocupada.nombre)
                        
                if es_mio:
                    tiene_custodia = True 
                    dias_auto.append(d) 
                else:
                    dias_solicitud.append(d) 
                    obra_str = " / ".join(list(set(nombres_ajenas))) if nombres_ajenas else "Otra Obra"
                    if obra_str not in conflict_details: conflict_details[obra_str] = []
                    conflict_details[obra_str].append(d.strftime('%d/%m'))
                    
        if mode in ['check', 'pure_check']:
            if dias_auto and dias_solicitud:
                return {
                    'success': False,
                    'conflict': True,
                    'conflict_type': 'custody_partial',
                    'message': f"Tienes custodia para asignar {len(dias_auto)} días libres o propios, pero {len(dias_solicitud)} días pertenecen a otras obras o requieren autorización.",
                    'auto_count': len(dias_auto),
                    'req_count': len(dias_solicitud),
                    'conflict_details': conflict_details 
                }
            elif not dias_auto and dias_solicitud:
                mode = 'assign_and_request' 
            elif dias_auto and not dias_solicitud:
                mode = 'assign_all_custody'

        # FIX: Evitar grabar a fuego en BD si solo queríamos simular el conflicto
        if mode == 'pure_check':
            return {'success': True, 'message': 'Sin conflictos para el jefe'}

        msgs = []
        action_taken = 'assigned'

        if mode in ['assign_and_request', 'assign_all_custody', 'only_custody', 'overwrite']:
            
            if dias_auto and mode != 'only_requests':
                _handle_direct_assignment(actor_user, worker, target_obra, dias_auto, overwrite=True, solicitud_id=solicitud_id)
                msgs.append(f"Asignados automáticamente ({len(dias_auto)}d)")
                notificar_traslado_interno(actor_user.name, worker, target_obra, dias_auto, list(obras_origen_traslado))

            if dias_solicitud and mode in ['assign_and_request', 'overwrite']:
                sol, sol_status = _create_solicitud_concreta_obj(actor_user, worker, target_obra, dias_solicitud, notas=notas)
                
                if sol_status == "new":
                    notificar_nueva_solicitud(sol, actor_user.name)
                    msgs.append(f"Solicitud generada a RRHH ({len(dias_solicitud)}d)")
                elif sol_status == "merged":
                    msgs.append(f"Solicitud existente ampliada para cubrir días nuevos")
                elif sol_status == "duplicate":
                    msgs.append(f"Ya existía una solicitud (omitida para evitar duplicados)")

                action_taken = 'partial_request' if dias_auto else 'requested'

            return {'success': True, 'action': action_taken, 'message': " | ".join(msgs)}

    return {'success': False, 'error': 'Rol no autorizado o acción no contemplada'}


def _create_solicitud_concreta_obj(jefe, worker, obra, dates, notas=None):
    from datetime import timedelta
    start_date = min(dates)
    end_date = max(dates)
    dates_str = [d.strftime('%Y-%m-%d') if isinstance(d, date) else d for d in dates]

    open_solicitudes = Solicitud.query.filter_by(
        tipo='CONCRETA',
        obra_id=obra.id,
        empleado_id=worker.id
    ).filter(
        Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])
    ).all()

    for existing in open_solicitudes:
        if getattr(existing, 'accion', 'ASIGNAR') == 'DESASIGNAR':
            continue

        if (existing.fecha_inicio - timedelta(days=1)) <= end_date and (existing.fecha_fin + timedelta(days=1)) >= start_date:
            if existing.fecha_inicio <= start_date and existing.fecha_fin >= end_date:
                if notas:
                    existing.notas = merge_notas(existing.notas, notas)
                    db.session.commit()
                return existing, "duplicate"
            else:
                existing.fecha_inicio = min(existing.fecha_inicio, start_date)
                existing.fecha_fin = max(existing.fecha_fin, end_date)
                existing.comentarios = merge_comentarios_dates(existing.comentarios, dates_str)
                existing.notas = merge_notas(existing.notas, notas)
                db.session.commit()
                return existing, "merged"

    solicitud = Solicitud(
        tipo='CONCRETA',
        obra_id=obra.id,
        requested_by_id=jefe.id,
        empleado_id=worker.id,
        fecha_inicio=start_date,
        fecha_fin=end_date,
        perfil_categoria=worker.categoria_profesional,
        perfil_empresa_id=worker.company_id,
        cantidad_solicitada=1,
        cantidad_cubierta=0,
        estado='PENDIENTE',
        comentarios=build_comentarios_config(dates_str),
        notas=(notas or '').strip() or None,
    )
    db.session.add(solicitud)
    db.session.commit()
    log_nueva_solicitud(solicitud)
    return solicitud, "new"

def _handle_direct_assignment(actor, worker, obra, dates, overwrite, solicitud_id=None):
    count = 0
    deleted_info = []
    assigned_dates = []

    for d in dates:
        same_obra_conflict = Asignacion.query.filter_by(
            user_id=worker.id, fecha=d, obra_id=obra.id
        ).first()

        if same_obra_conflict:
            continue

        if overwrite:
            existing_others = Asignacion.query.filter_by(user_id=worker.id, fecha=d).all()
            for exist in existing_others:
                deleted_info.append((exist.obra_id, exist.user_id, d))
                CoreAssignmentService.desasignar(
                    exist.user_id, exist.obra_id, exist.fecha, actor.id,
                    "Planificación Manual", "Sobreescritura de asignación previa.",
                    registrar_log=False,
                )

        CoreAssignmentService.asignar(
            worker.id, obra.id, d, actor.id, "Planificación Manual",
            company_id=worker.company_id, solicitud_id=solicitud_id,
            registrar_log=False,
        )
        assigned_dates.append(d)
        count += 1

    if count:
        CoreAssignmentService.registrar_log_rango(
            worker.id, obra.id,
            min(assigned_dates), max(assigned_dates), count,
            actor.id, "Planificación Manual", True,
            detalle_extra=(
                f"Incluye sobreescritura de {len(deleted_info)} día(s)."
                if deleted_info else None
            ),
        )

    for o_id, w_id, d_del in deleted_info:
        update_solicitudes_for_assignment(o_id, w_id, d_del, resolved_by_id=actor.id)

    for d in dates:
        update_solicitudes_for_assignment(obra.id, worker.id, d, resolved_by_id=actor.id)

    db.session.commit()

    return {'success': True, 'action': 'assigned', 'message': f'Asignación realizada ({count} días).'}

def process_unassign_action(actor_user, worker_id, target_obra_id, date_list, mode='selected'):
    from app.services.solicitud_service import SolicitudService, update_solicitudes_for_assignment
    from app.services.email_service import notificar_movimiento_admin_a_jo
    
    worker_id = int(worker_id) if worker_id else None
    target_obra_id = int(target_obra_id) if target_obra_id else None

    if not worker_id:
        return {'success': False, 'message': 'Falta ID trabajador'}

    query = Asignacion.query.filter_by(user_id=worker_id)
    if target_obra_id:
        query = query.filter_by(obra_id=target_obra_id)

    date_objs = []
    if mode == 'all_obra':
        asignaciones = query.filter(Asignacion.fecha >= today_local()).all()
        if not asignaciones:
            return {'success': False, 'message': 'No hay asignaciones futuras para borrar.'}
        date_objs = [a.fecha for a in asignaciones]
    else:
        raw_dates = sorted([datetime.strptime(d, '%Y-%m-%d').date() if isinstance(d, str) else d for d in date_list])
        date_objs = [d for d in raw_dates if d >= today_local()]
        asignaciones = query.filter(Asignacion.fecha.in_(date_objs)).all()

    if not date_objs:
        return {'success': False, 'message': 'No hay fechas válidas.'}
    
    fechas_con_asignacion = [a.fecha for a in asignaciones]
    
    if actor_user.role == ROLE_JEFE:
        if not fechas_con_asignacion:
            return {'success': False, 'message': 'El trabajador no tiene asignaciones en este periodo.'}
            
        sol, status = SolicitudService.create_or_merge_solicitud_baja(
            actor_user.id, target_obra_id, worker_id, fechas_con_asignacion
        )
        if not sol or status == 'none':
            return {
                'success': False,
                'message': 'No se puede solicitar la baja: no hay asignación en esos días.',
            }
        msg = (
            'Se ha generado una solicitud de baja.'
            if status == 'new'
            else 'Se han añadido los días a una solicitud existente.'
        )
        return {'success': True, 'action': 'requested', 'message': msg}


    count = len(asignaciones)
    fechas_borradas = [a.fecha.strftime('%d/%m/%Y') for a in asignaciones]
    fechas_objs = sorted({a.fecha for a in asignaciones})

    for a in asignaciones:
        CoreAssignmentService.desasignar(
            a.user_id, a.obra_id, a.fecha, actor_user.id,
            "Planificación Manual",
            registrar_log=False,
        )

    if count and fechas_objs:
        CoreAssignmentService.registrar_log_rango(
            worker_id, target_obra_id or asignaciones[0].obra_id,
            fechas_objs[0], fechas_objs[-1], count,
            actor_user.id, "Planificación Manual", False,
        )
    
    for d_obj in date_objs:
        try:
            update_solicitudes_for_assignment(target_obra_id, worker_id, d_obj, resolved_by_id=actor_user.id)
        except Exception:
            pass

    db.session.commit()
    
    if target_obra_id and count > 0:
        worker = User.query.get(worker_id)
        worker_name = f"{worker.name} {worker.lastname}" if worker else f"ID {worker_id}"
        
        if len(fechas_borradas) > 10:
            fechas_str = ", ".join(fechas_borradas[:10]) + f" ... y {len(fechas_borradas)-10} días más."
        else:
            fechas_str = ", ".join(fechas_borradas)

        notificar_movimiento_admin_a_jo(target_obra_id, worker_name, "Desasignar", fechas_str, actor_user.name)

    return {'success': True, 'action': 'unassigned', 'message': f'Se han eliminado {count} asignaciones.'}