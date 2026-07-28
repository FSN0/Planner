# app/services/dashboard_service.py

from datetime import date, datetime, timedelta
import calendar
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from flask import url_for

from app import db
# IMPORTANTE: Añadido RegistroFichaje a los imports
from app.models import Obra, User, Asignacion, Solicitud, Company, ROLE_JEFE, ROLE_OPERARIO, ROLE_ADMIN, ROLE_LABORAL, UserObraConfig, RegistroFichaje
from app.utils.timezone_utils import today_local

def parse_date(date_str):
    """Utilidad interna para parsear fechas de forma segura"""
    if not date_str:
        return date.today()
    try:
        if isinstance(date_str, (date, datetime)):
            return date_str if isinstance(date_str, date) else date_str.date()
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return date.today()

def get_dashboard_data(user, date_arg, view_param='mis'):
    """
    Función MAESTRA unificada.
    """
    
    # 1. Gestión de Fechas
    selected_date = parse_date(date_arg)
    year = selected_date.year
    month = selected_date.month
    
    if month == 1:
        prev_date = date(year - 1, 12, 1)
    else:
        prev_date = date(year, month - 1, 1)
        
    if month == 12:
        next_date = date(year + 1, 1, 1)
    else:
        next_date = date(year, month + 1, 1)

    meses = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
             "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    month_name = meses[month]

    # 2. Query de Obras
    query = Obra.query.options(
        joinedload(Obra.jefe_obra),
        joinedload(Obra.encargado)
    ).filter(
        Obra.is_deleted.is_(False),
        Obra.estado == 'En Curso'
    )

    if user.role == ROLE_JEFE:
        query = query.filter(Obra.jefe_obra_id == user.id)
    elif view_param == 'mis':
        query = query.filter(Obra.jefe_obra_id == user.id)
    
    # Obtenemos la lista inicial
    obras = query.order_by(Obra.fecha_inicio.desc()).all()

    # --- 3. PRE-CARGA Y ORDENACIÓN (LÓGICA NUEVA) ---
    obra_ids = [o.id for o in obras]
    mapa_asig = {oid: [] for oid in obra_ids}

    # Precargar fichajes del día para admin / laboral
    fichajes_dict = {}
    if user.role in (ROLE_ADMIN, ROLE_LABORAL):
        fichajes = RegistroFichaje.query.filter_by(fecha=selected_date).all()
        for f in fichajes:
            fichajes_dict[f.user_id] = f.estado

    if obra_ids:
        # Buscamos asignaciones HOY para saber cuántos hay en cada obra
        asig_hoy = Asignacion.query.filter(
            Asignacion.obra_id.in_(obra_ids), 
            Asignacion.fecha == selected_date
        ).all()
        
        for a in asig_hoy:
            if a.obra_id in mapa_asig:
                u = User.query.get(a.user_id)
                if u: 
                    # Inyectamos estado de fichaje al usuario (admin y laboral)
                    u.temp_estado_fichaje = (
                        fichajes_dict.get(u.id, 'Sin_Registro')
                        if user.role in (ROLE_ADMIN, ROLE_LABORAL)
                        else None
                    )
                    mapa_asig[a.obra_id].append(u)

    # Overlay vacaciones/ausencias del día seleccionado (tarjeta distinta en tablero)
    from app.services.leave_service import (
        build_leaves_by_user,
        leave_covering,
        leave_overlay_meta,
    )
    worker_ids_hoy = {u.id for workers in mapa_asig.values() for u in workers}
    leaves_idx = build_leaves_by_user(worker_ids_hoy, selected_date, selected_date)
    for workers in mapa_asig.values():
        for u in workers:
            leave = leave_covering(leaves_idx.get(u.id, []), selected_date)
            meta = leave_overlay_meta(leave)
            u.temp_en_ausencia = bool(meta)
            u.temp_ausencia_tipo = meta['label_prefix'] if meta else None
            u.temp_ausencia_aprobada = meta['aprobada'] if meta else False
    
    # --- DIVISIÓN: PINEADAS vs NO PINEADAS ---
    # Recuperamos configuración del usuario
    user_configs = UserObraConfig.query.filter_by(user_id=user.id).all()
    config_map = {c.obra_id: c for c in user_configs}

    custom_order_obras = []
    default_obras = []

    for obra in obras:
        conf = config_map.get(obra.id)
        obra.is_pinned = conf.is_pinned if conf else False
        obra.personnel_count = len(mapa_asig.get(obra.id, []))

        if conf is not None:
            custom_order_obras.append((conf.position, obra))
        else:
            default_obras.append(obra)

    custom_order_obras.sort(key=lambda item: item[0])
    default_obras.sort(key=lambda o: o.personnel_count, reverse=True)
    obras = [obra for _, obra in custom_order_obras] + default_obras
    # ---------------------------------------------------------

    # 4. Datos de Cabecera
    _, num_days = calendar.monthrange(year, month)
    header_days = []
    today = today_local()
    
    all_operarios_count = User.query.filter_by(role=ROLE_OPERARIO, active=True, is_deleted=False).count()
    
    month_start = date(year, month, 1)
    month_end = date(year, month, num_days)
    
    asignaciones_mes = db.session.query(Asignacion.fecha, func.count(Asignacion.user_id))\
        .filter(Asignacion.fecha >= month_start, Asignacion.fecha <= month_end)\
        .group_by(Asignacion.fecha).all()
    
    ocupados_por_dia = {fecha: count for fecha, count in asignaciones_mes}

    for day in range(1, num_days + 1):
        current = date(year, month, day)
        ocupados = ocupados_por_dia.get(current, 0)
        libres = max(0, all_operarios_count - ocupados)
        
        header_days.append({
            'date': current,
            'date_str': current.strftime('%Y-%m-%d'),
            'date_human': current.strftime('%d/%m/%Y'),
            'day_num': day,
            'weekday': current.strftime('%a'),
            'is_weekend': current.weekday() >= 5,
            'is_selected': current == selected_date,
            'is_today': current == today,
            'free_count': libres,
            'ins': 0,
            'outs': 0
        })

    # 5. Estructura de Datos de Obras (Ya vienen ordenadas)
    obra_data = []
    for obra in obras:
        obra_data.append({
            'obra': obra,
            'workers': mapa_asig.get(obra.id, [])
        })

    # 6. Timeline
    timeline_data = []
    for obra in obras:
        days_status = []
        start = getattr(obra, 'fecha_inicio', None)
        end = getattr(obra, 'fecha_fin', None)
        
        for day in range(1, num_days + 1):
            curr = date(year, month, day)
            is_active = False
            if start:
                if end:
                    if start <= curr <= end: is_active = True
                elif start <= curr: is_active = True
            
            days_status.append({
                'date': curr,
                'is_active': is_active,
                'is_weekend': curr.weekday() >= 5
            })
        
        timeline_data.append({'obra': obra, 'days': days_status})

    # 7. Listas Auxiliares
    all_operarios = User.query.filter_by(role=ROLE_OPERARIO, active=True, is_deleted=False).order_by(User.name).all()
    
    asig_global_hoy = Asignacion.query.filter_by(fecha=selected_date).all()
    busy_ids = {a.user_id for a in asig_global_hoy}
    
    free_workers = []
    busy_workers = []
    
    for w in all_operarios:
        # Inyectamos estado de fichaje al usuario libre/ocupado
        w.temp_estado_fichaje = fichajes_dict.get(w.id, 'Sin_Registro') if user.role == ROLE_ADMIN else None
        
        if w.id not in busy_ids:
            free_workers.append(w)
        else:
            busy_workers.append(w)

    jefes_list = User.query.filter(User.role.in_([ROLE_JEFE, ROLE_ADMIN]), User.is_deleted==False, User.active==True).all()
    companies_list = Company.query.all()
    companies_dict = {c.code: c.nombre for c in companies_list}
    company_colors = {c.code: c.color for c in companies_list}

    # 8. Notificaciones
    notification_counts = {}
    if obra_ids:
        pendientes = db.session.query(Solicitud.obra_id, func.count(Solicitud.id))\
            .filter(Solicitud.obra_id.in_(obra_ids), Solicitud.estado.in_(["PENDIENTE", "EN_PROCESO"]))\
            .group_by(Solicitud.obra_id).all()
        temp_map = {oid: c for oid, c in pendientes}
        for o in obras:
            notification_counts[o.id] = temp_map.get(o.id, 0)

    return {
        'selected_date': selected_date,
        'year': year,
        'month': month,
        'month_name': month_name,
        'header_days': header_days,
        'obra_data': obra_data,
        'timeline_data': timeline_data,
        'free_workers': free_workers,
        'busy_workers': busy_workers,
        'jefes': jefes_list,
        'companies': companies_dict,
        'company_colors': company_colors,
        'notification_counts': notification_counts,
        'prev_date_str': prev_date.strftime('%Y-%m-%d'),
        'next_date_str': next_date.strftime('%Y-%m-%d'),
        'encargados': [], 
        'calendar_events': [],
        'datetime': datetime
    }