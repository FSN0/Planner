# app/services/solicitud_service.py
from datetime import datetime, timedelta
import json
from app import db
from app.models import Solicitud, Asignacion, User, Festivo
from app.services.email_service import notificar_nueva_solicitud

def update_solicitudes_for_assignment(obra_id, worker_id, fecha, resolved_by_id=None):
    """
    Trigger: Llamar cuando se crea/borra una Asignacion.
    Busca solicitudes afectadas (GENERICAS Y CONCRETAS) y recalcula su estado.
    """
    from datetime import date
    if fecha < date.today():
        return
    
    # --- FIX CRÍTICO: Obligamos a que sean números para evitar que 14 != "14" ---
    worker_id = int(worker_id)
    if obra_id:
        obra_id = int(obra_id)
        
    worker = User.query.get(worker_id)
    if not worker:
        return

    # 1. Buscamos TODAS las solicitudes abiertas en esa obra y fecha
    qs = Solicitud.query.filter(
        Solicitud.obra_id == obra_id,
        Solicitud.estado.in_(["PENDIENTE", "EN_PROCESO", "CUMPLIDA"]),
        Solicitud.fecha_inicio <= fecha,
        Solicitud.fecha_fin >= fecha,
    ).all()

    for sol in qs:
        # Si la solicitud especifica una empresa obligatoria y el currante es de otra, no le afecta (Solo genéricas)
        if sol.tipo == "GENERICA" and sol.perfil_empresa_id and sol.perfil_empresa_id != worker.company_id:
            continue
        
        # Si es concreta para OTRO empleado distinto, la ignoramos (optimización)
        if sol.tipo == "CONCRETA" and sol.empleado_id != worker_id:
            continue

        # Guardamos el estado que tiene la solicitud ANTES de pasar por el motor de recálculo
        estado_previo = sol.estado

        # El motor hace sus matemáticas y actualiza el objeto 'sol' por dentro
        _recalculate_solicitud_coverage(sol, resolved_by_id)

        # --- FIX: NOTIFICAR SI EL SISTEMA AUTO-CUMPLE LA SOLICITUD ---
        if estado_previo != 'CUMPLIDA' and sol.estado == 'CUMPLIDA':
            from app.services.email_service import notificar_resolucion_solicitud
            
            # Buscar el nombre de quien provocó esto
            admin_user = User.query.get(resolved_by_id) if resolved_by_id else None
            admin_name = f"{admin_user.name} {admin_user.lastname}" if admin_user else "Sistema Automático"
            
            # CAMBIO AQUÍ: Le inyectamos el worker_id del tío que acabamos de mover
            notificar_resolucion_solicitud(sol, admin_name, worker_id=worker_id)
        # -------------------------------------------------------------


def _recalculate_solicitud_coverage(solicitud, resolved_by_id=None):
    """
    Calcula cobertura EXACTA (leyendo los días específicos del JSON) y actualiza estado.
    ATENCIÓN: Esta función NO hace db.session.commit(). Delega el guardado a la ruta principal.
    """
    start = solicitud.fecha_inicio
    end = solicitud.fecha_fin
    valid_dates = []

    # Extraer las fechas EXACTAS solicitadas desde el JSON
    explicit_dates = []
    if solicitud.comentarios:
        try:
            data = json.loads(solicitud.comentarios)
            if 'dates' in data:
                explicit_dates = [datetime.strptime(d, '%Y-%m-%d').date() for d in data['dates']]
        except Exception:
            pass

    if explicit_dates:
        valid_dates = [d for d in explicit_dates if start <= d <= end]

    # Respaldo si no hay fechas en el JSON
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

    # ==========================================
    # LÓGICA A: SOLICITUDES GENÉRICAS
    # ==========================================
    if solicitud.tipo == "GENERICA":
        requested = solicitud.cantidad_solicitada or 1

        from sqlalchemy import or_, and_
        
        # 1. Filtros base innegociables
        base_filters = [
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.fecha >= start,
            Asignacion.fecha <= end,
            User.is_deleted == False
        ]

        # 2. Asignado EXPLÍCITAMENTE a esta solicitud (salta las reglas de perfil)
        cond_explicita = (Asignacion.solicitud_id == solicitud.id)

        # 3. Asignado libremente en el cuadrante general (exigimos que coincida con lo pedido)
        cond_libre = [Asignacion.solicitud_id == None]
        if solicitud.perfil_categoria:
            cond_libre.append(User.categoria_profesional.ilike(f"%{solicitud.perfil_categoria}%"))
        if solicitud.created_at:
            cond_libre.append(Asignacion.created_at >= solicitud.created_at)
        if solicitud.perfil_empresa_id:
            cond_libre.append(User.company_id == solicitud.perfil_empresa_id)

        # Unimos todo y ejecutamos
        q = Asignacion.query.join(User).filter(
            *base_filters,
            or_(cond_explicita, and_(*cond_libre))
        )

        asignaciones = q.all()

        counts_by_day = {d: 0 for d in valid_dates}
        for a in asignaciones:
            if a.fecha in counts_by_day:
                counts_by_day[a.fecha] += 1

        min_coverage = min(counts_by_day.values()) if counts_by_day else 0
        solicitud.cantidad_cubierta = min_coverage
        total_assignments_count = sum(counts_by_day.values())

        if min_coverage >= requested:
            solicitud.estado = "CUMPLIDA"
            solicitud.resolved_at = datetime.utcnow()
            if resolved_by_id: solicitud.resolved_by_id = resolved_by_id
        elif total_assignments_count > 0:
            solicitud.estado = "EN_PROCESO"
        else:
            solicitud.estado = "PENDIENTE"
            solicitud.resolved_at = None

# ==========================================
    # LÓGICA B: SOLICITUDES CONCRETAS (Altas y Bajas)
    # ==========================================
    elif solicitud.tipo == "CONCRETA":
        accion = getattr(solicitud, 'accion', 'ASIGNAR')
        
        # --- FIX: PREVENCIÓN DE BAJAS ZOMBI ---
        # Si es una petición de baja que ya se completó en su momento, 
        # re-asignar al trabajador en el futuro no debe reabrir este ticket histórico.
        if accion == 'DESASIGNAR' and prev_estado == 'CUMPLIDA':
            return
        # --------------------------------------
        
        # Consultamos las asignaciones SÓLO para los días válidos
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
            # BAJA: Se cumple cuando YA NO ESTÁ asignado en ninguno de esos días
            is_fulfilled = (cobertura_count == 0)
            is_in_process = (cobertura_count > 0 and cobertura_count < total_validos)
        else:
            # ALTA: Se cumple cuando ESTÁ asignado en todos esos días
            is_fulfilled = (cobertura_count == total_validos and total_validos > 0)
            is_in_process = (cobertura_count > 0 and cobertura_count < total_validos)

        if is_fulfilled:
            solicitud.estado = "CUMPLIDA"
            solicitud.cantidad_cubierta = solicitud.cantidad_solicitada
            solicitud.resolved_at = datetime.utcnow()
            if resolved_by_id: solicitud.resolved_by_id = resolved_by_id
        elif is_in_process:
            solicitud.estado = "EN_PROCESO"
        else:
            solicitud.estado = "PENDIENTE"
            solicitud.cantidad_cubierta = 0
            solicitud.resolved_at = None

    # NO HACEMOS COMMIT AQUÍ. Lo delegamos a la función padre para que sea seguro.
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
        """Inteligencia para no duplicar solicitudes de baja, respetando islas de fechas."""
        if not date_objs: return None, "none"
        
        start_date = min(date_objs)
        end_date = max(date_objs)
        dates_str = [d.strftime('%Y-%m-%d') for d in date_objs]

        # 1. Buscamos TODAS las peticiones de baja vivas para este operario
        open_bajas = Solicitud.query.filter_by(
            tipo='CONCRETA', accion='DESASIGNAR', obra_id=obra_id, empleado_id=empleado_id
        ).filter(Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])).all()

        for baja in open_bajas:
            # 2. Comprobamos si el nuevo rango se solapa o es contiguo (se tocan por 1 día) al de la baja existente
            if (baja.fecha_inicio - timedelta(days=1)) <= end_date and (baja.fecha_fin + timedelta(days=1)) >= start_date:
                # Se tocan o solapan, así que fusionamos
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

        # 3. Si el bucle termina sin fusionar (porque es una fecha lejana como de mayo a junio), creamos una limpia
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
                            user_id=solicitud.empleado_id, 
                            obra_id=solicitud.obra_id, 
                            fecha=d_obj
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
                actor_user=user_actor,
                worker_id=solicitud.empleado_id,
                target_obra_id=solicitud.obra_id,
                date_list=dias,
                overwrite=True 
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