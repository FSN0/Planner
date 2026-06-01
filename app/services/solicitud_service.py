# app/services/solicitud_service.py
from datetime import datetime, timedelta
import json
from app import db
from app.models import Solicitud, Asignacion, User, Festivo
from app.services.email_service import notificar_nueva_solicitud

def update_solicitudes_for_assignment(obra_id, worker_id, fecha, resolved_by_id=None):
    from datetime import date
    if fecha < date.today():
        return
    
    worker_id = int(worker_id)
    if obra_id:
        obra_id = int(obra_id)
        
    worker = User.query.get(worker_id)
    if not worker:
        return

    qs = Solicitud.query.filter(
        Solicitud.obra_id == obra_id,
        Solicitud.estado.in_(["PENDIENTE", "EN_PROCESO"]),
        Solicitud.fecha_inicio <= fecha,
        Solicitud.fecha_fin >= fecha,
    ).all()

    for sol in qs:
        if sol.tipo == "CONCRETA" and sol.empleado_id != worker_id:
            continue

        estado_previo = sol.estado
        _recalculate_solicitud_coverage(sol, resolved_by_id)

        if estado_previo != 'CUMPLIDA' and sol.estado == 'CUMPLIDA':
            from app.services.email_service import notificar_resolucion_solicitud
            admin_user = User.query.get(resolved_by_id) if resolved_by_id else None
            admin_name = f"{admin_user.name} {admin_user.lastname}" if admin_user else "Sistema Automático"
            notificar_resolucion_solicitud(sol, admin_name, worker_id=worker_id)

def _recalculate_solicitud_coverage(solicitud, resolved_by_id=None):
    start = solicitud.fecha_inicio
    end = solicitud.fecha_fin
    valid_dates = []

    explicit_dates = []
    if solicitud.comentarios:
        try:
            if not solicitud.comentarios.strip().startswith('{'):
                data = {}
            else:
                data = json.loads(solicitud.comentarios)
            
            fechas_base = data.get('original_dates') or data.get('dates', [])
            if fechas_base:
                explicit_dates = [datetime.strptime(d, '%Y-%m-%d').date() for d in fechas_base]
        except Exception:
            pass

    if explicit_dates:
        valid_dates = [d for d in explicit_dates if start <= d <= end]

    if not valid_dates:
        festivos = Festivo.query.filter(Festivo.fecha >= start, Festivo.fecha <= end).all()
        fechas_festivas = [f.fecha for f in festivos]
        curr = start
        while curr <= end:
            if curr.weekday() < 5 and curr not in fechas_festivas:
                valid_dates.append(curr)
            curr += timedelta(days=1)
            
        if not valid_dates:
            valid_dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    total_validos = len(valid_dates)
    prev_estado = solicitud.estado

    if solicitud.tipo == "GENERICA":
        requested = solicitud.cantidad_solicitada or 1

        # FIX DEFINITIVO: Ahora el motor es puro. No roba asignaciones huérfanas o fantasmas.
        # SÓLO cuenta aquellas que tú le inyectas directamente desde los endpoints, 
        # que siempre vendrán atadas con su solicitud.id.
        asignaciones_vinculadas = Asignacion.query.filter(
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.solicitud_id == solicitud.id,
            Asignacion.fecha.in_(valid_dates)
        ).all()

        counts_by_day = {d: 0 for d in valid_dates}
        for a in asignaciones_vinculadas:
            counts_by_day[a.fecha] += 1

        min_coverage = min(counts_by_day.values()) if counts_by_day else 0
        solicitud.cantidad_cubierta = min_coverage
        total_assignments_count = sum(counts_by_day.values())

        # --- AUTO-MANTENIMIENTO DEL FRONTEND (Días Verdes) ---
        dias_incompletos = [d.strftime("%Y-%m-%d") for d, c in counts_by_day.items() if c < requested]
        try:
            if not solicitud.comentarios or not solicitud.comentarios.strip().startswith('{'):
                config = {'mensaje_original': solicitud.comentarios}
            else:
                config = json.loads(solicitud.comentarios)
                
            if 'original_dates' not in config:
                config['original_dates'] = config.get('dates', [])
            if not config['original_dates'] and valid_dates:
                config['original_dates'] = [d.strftime("%Y-%m-%d") for d in valid_dates]
            
            config['mode'] = 'selected'
            config['dates'] = dias_incompletos
            solicitud.comentarios = json.dumps(config)
        except Exception:
            pass
        # ----------------------------------------------------

        if min_coverage >= requested:
            solicitud.estado = "CUMPLIDA"
            solicitud.resolved_at = datetime.utcnow()
            if resolved_by_id: solicitud.resolved_by_id = resolved_by_id
        elif total_assignments_count > 0:
            solicitud.estado = "EN_PROCESO"
            solicitud.resolved_at = None
        else:
            solicitud.estado = "PENDIENTE"
            solicitud.resolved_at = None

    elif solicitud.tipo == "CONCRETA":
        accion = getattr(solicitud, 'accion', 'ASIGNAR')
        
        if accion == 'DESASIGNAR' and prev_estado == 'CUMPLIDA':
            return
        
        asignaciones_reales = Asignacion.query.filter(
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.user_id == solicitud.empleado_id,
            Asignacion.fecha.in_(valid_dates)
        ).all()
        
        asignados_dias = [a.fecha for a in asignaciones_reales]
        cobertura_count = len(set(asignados_dias))
        
        is_fulfilled = False
        is_in_process = False

        if accion == 'DESASIGNAR':
            is_fulfilled = (cobertura_count == 0)
            is_in_process = (cobertura_count > 0 and cobertura_count < total_validos)
        else:
            is_fulfilled = (cobertura_count == total_validos and total_validos > 0)
            is_in_process = (cobertura_count > 0 and cobertura_count < total_validos)

        if is_fulfilled:
            solicitud.estado = "CUMPLIDA"
            solicitud.cantidad_cubierta = solicitud.cantidad_solicitada
            solicitud.resolved_at = datetime.utcnow()
            if resolved_by_id: resolved_by_id = resolved_by_id
        elif is_in_process:
            solicitud.estado = "EN_PROCESO"
        else:
            solicitud.estado = "PENDIENTE"
            solicitud.cantidad_cubierta = 0
            solicitud.resolved_at = None

    db.session.add(solicitud)

class SolicitudService:
    @staticmethod
    def create_solicitud_generica(solicitante_id, obra_id, fecha_inicio, fecha_fin, cantidad, perfil, comentarios):
        solicitante = User.query.get(solicitante_id)
        nueva_solicitud = Solicitud(
            requested_by_id=solicitante_id,
            obra_id=obra_id,
            tipo="GENERICA",
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            cantidad_solicitada=cantidad,
            perfil_categoria=perfil,
            comentarios=comentarios,
            estado="PENDIENTE"
        )
        db.session.add(nueva_solicitud)
        db.session.commit()
        notificar_nueva_solicitud(nueva_solicitud, solicitante.name)
        return nueva_solicitud

    @staticmethod
    def create_or_merge_solicitud_baja(jefe_id, obra_id, empleado_id, date_objs):
        if not date_objs: return None, "none"
        start_date = min(date_objs)
        end_date = max(date_objs)
        dates_str = [d.strftime('%Y-%m-%d') for d in date_objs]

        open_bajas = Solicitud.query.filter_by(
            tipo='CONCRETA', accion='DESASIGNAR', obra_id=obra_id, empleado_id=empleado_id
        ).filter(Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])).all()

        for baja in open_bajas:
            if (baja.fecha_inicio - timedelta(days=1)) <= end_date and (baja.fecha_fin + timedelta(days=1)) >= start_date:
                baja.fecha_inicio = min(baja.fecha_inicio, start_date)
                baja.fecha_fin = max(baja.fecha_fin, end_date)
                try:
                    comentarios_json = json.loads(baja.comentarios or '{}')
                    existing_dates = comentarios_json.get('dates', [])
                    merged_dates = sorted(list(set(existing_dates + dates_str)))
                    comentarios_json['dates'] = merged_dates
                    baja.comentarios = json.dumps(comentarios_json)
                except Exception:
                    pass
                db.session.commit()
                return baja, "merged"

        comentarios_json = json.dumps({'mode': 'selected', 'dates': dates_str})
        sol_baja = Solicitud(
            tipo='CONCRETA', accion='DESASIGNAR', obra_id=obra_id,
            requested_by_id=jefe_id, empleado_id=empleado_id,
            fecha_inicio=start_date, fecha_fin=end_date,
            cantidad_solicitada=1, estado='PENDIENTE', comentarios=comentarios_json
        )
        db.session.add(sol_baja)
        db.session.commit()
        
        jefe = User.query.get(jefe_id)
        notificar_nueva_solicitud(sol_baja, jefe.name if jefe else 'Sistema')
        return sol_baja, "new"
    
def resolver_solicitud_admin(solicitud, accion, user_actor):
    from app.services.assignment_service import process_assignment_action
    from app.services.email_service import notificar_resolucion_solicitud
    from datetime import date
    
    if accion == 'aceptar_concreta':
        if not solicitud.empleado_id:
            raise ValueError("Error: Solicitud concreta sin empleado asignado.")

        tipo_accion = getattr(solicitud, 'accion', 'ASIGNAR')

        if tipo_accion == 'DESASIGNAR':
            mode = 'all_obra'
            dates_to_remove = []
            if solicitud.comentarios and '{' in solicitud.comentarios:
                try:
                    config = json.loads(solicitud.comentarios)
                    mode = config.get('mode', 'all_obra')
                    dates_to_remove = config.get('dates', [])
                except Exception: pass

            count = 0
            if mode == 'all_obra':
                start_del = solicitud.fecha_inicio if solicitud.fecha_inicio else date.today()
                asigs = Asignacion.query.filter(
                    Asignacion.user_id == solicitud.empleado_id, 
                    Asignacion.obra_id == solicitud.obra_id, 
                    Asignacion.fecha >= start_del
                ).all()
                count = len(asigs)
                for a in asigs: db.session.delete(a)
                
            elif mode == 'selected' and dates_to_remove:
                for d_str in dates_to_remove:
                    try:
                        d_obj = datetime.strptime(d_str, '%Y-%m-%d').date()
                        asig = Asignacion.query.filter_by(
                            user_id=solicitud.empleado_id, obra_id=solicitud.obra_id, fecha=d_obj
                        ).first()
                        if asig:
                            db.session.delete(asig)
                            count += 1
                    except ValueError: continue
                    
            elif mode == 'auto_range':
                asigs = Asignacion.query.filter(
                    Asignacion.user_id == solicitud.empleado_id, 
                    Asignacion.obra_id == solicitud.obra_id, 
                    Asignacion.fecha >= solicitud.fecha_inicio, 
                    Asignacion.fecha <= solicitud.fecha_fin
                ).all()
                count = len(asigs)
                for a in asigs: db.session.delete(a)
            
            mensaje = f"Devolución aprobada. Se han eliminado {count} asignaciones."

        else:
            dias = []
            curr = solicitud.fecha_inicio
            while curr <= solicitud.fecha_fin:
                dias.append(curr)
                curr += timedelta(days=1)
            
            result = process_assignment_action(
                actor_user=user_actor, worker_id=solicitud.empleado_id,
                target_obra_id=solicitud.obra_id, date_list=dias, overwrite=True 
            )
            
            if not result.get('success'):
                raise ValueError(f"Error al asignar: {result.get('message')}")
            
            mensaje = "Solicitud aceptada y trabajador asignado."

        solicitud.estado = 'CUMPLIDA'
        solicitud.cantidad_cubierta = solicitud.cantidad_solicitada 
        solicitud.resolved_at = datetime.utcnow()
        solicitud.resolved_by_id = user_actor.id
        db.session.commit()
        notificar_resolucion_solicitud(solicitud, user_actor.name)
        return mensaje

    elif accion == 'denegar':
        solicitud.estado = 'DENEGADA'
        solicitud.resolved_at = datetime.utcnow()
        solicitud.resolved_by_id = user_actor.id
        db.session.commit()
        notificar_resolucion_solicitud(solicitud, user_actor.name)
        return "Solicitud denegada."

    elif accion == 'reabrir':
        solicitud.estado = 'PENDIENTE'
        solicitud.resolved_at = None
        solicitud.resolved_by_id = None
        db.session.commit()
        return "Solicitud reabierta."
    else:
        raise ValueError("Acción no reconocida.")