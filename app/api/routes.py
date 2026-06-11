from flask import Blueprint, request, jsonify, url_for
from flask_login import login_required, current_user
# IMPORTAMOS db AQUÍ
from app import db 
from app.models import Asignacion, User, Solicitud, Obra, Company, UserObraConfig, ROLE_ADMIN, ROLE_JEFE
from datetime import datetime, timedelta
import json
from collections import defaultdict # AÑADIDO PARA LA LÓGICA DE AGRUPACIÓN
# IMPORTAMOS LA LÓGICA COMPARTIDA


api_bp = Blueprint('api_v6', __name__, url_prefix='/api/v6')


@api_bp.route('/recursos_activos', methods=['GET'])
@login_required
def recursos_activos():
    """Devuelve las obras y usuarios activos filtrados por el rol (Para selectores y modales)"""
    
    # 1. Filtro de seguridad para Obras
    if current_user.role == ROLE_ADMIN:
        obras = Obra.query.filter_by(is_deleted=False).order_by(Obra.nombre).all()
    elif current_user.role == ROLE_JEFE:
        # MAGIA: Si es jefe, solo traemos las que tienen su ID
        obras = Obra.query.filter_by(is_deleted=False, jefe_obra_id=current_user.id).order_by(Obra.nombre).all()
    else:
        obras = []
        
    # 2. Usuarios (Siguen saliendo todos de momento, a menos que quieras filtrarlos también)
    users = User.query.filter_by(is_deleted=False).order_by(User.name).all()
    
    return jsonify({
        'obras': [{'id': o.id, 'text': o.nombre} for o in obras],
        'users': [{'id': u.id, 'text': f"{u.name} {u.lastname}"} for u in users]
    })
    
@api_bp.route('/toggle_pin_obra', methods=['POST'])
@login_required
def toggle_pin_obra():
    data = request.get_json()
    obra_id = data.get('obra_id')
    if not obra_id: return jsonify({'success': False}), 400
    conf = UserObraConfig.query.filter_by(user_id=current_user.id, obra_id=obra_id).first()
    if not conf:
        conf = UserObraConfig(user_id=current_user.id, obra_id=obra_id, is_pinned=True, position=0)
        db.session.add(conf)
        action = 'pinned'
    else:
        conf.is_pinned = not conf.is_pinned
        action = 'pinned' if conf.is_pinned else 'unpinned'
    db.session.commit()
    return jsonify({'success': True, 'action': action})

@api_bp.route('/reorder_pinned_obras', methods=['POST'])
@login_required
def reorder_pinned_obras():
    data = request.get_json()
    ordered_ids = data.get('ordered_ids', [])
    if not ordered_ids: return jsonify({'success': False})
    for idx, obra_id in enumerate(ordered_ids):
        conf = UserObraConfig.query.filter_by(user_id=current_user.id, obra_id=obra_id).first()
        if not conf:
            conf = UserObraConfig(user_id=current_user.id, obra_id=obra_id, is_pinned=False, position=idx)
            db.session.add(conf)
        else:
            conf.position = idx
            db.session.add(conf)
    db.session.commit()
    return jsonify({'success': True})

# ==============================================================================
# NUEVO: ENDPOINT PARA EL CALENDARIO UNIVERSAL (DRAG & DROP, AGRUPADO)
# ==============================================================================
# ==============================================================================
# NUEVO: ENDPOINT PARA EL CALENDARIO UNIVERSAL (DRAG & DROP, AGRUPADO)
# ==============================================================================
@api_bp.route('/universal-calendar', methods=['GET'])
@login_required
def get_universal_calendar_events():
    context = request.args.get('context')
    entity_id = request.args.get('id', type=int)
    mode = request.args.get('mode', 'empleados') # 'empleados' o 'empresas'
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    show_fichajes = request.args.get('show_fichajes') == '1'
    if not start_str or not end_str: return jsonify([])

    try:
        s_clean = start_str.replace('Z', '').split('T')[0]
        e_clean = end_str.replace('Z', '').split('T')[0]
        start_date = datetime.strptime(s_clean, "%Y-%m-%d").date()
        end_date = datetime.strptime(e_clean, "%Y-%m-%d").date()
    except Exception:
        return jsonify([])

    events = []

    # =====================================================================
    # 1. CONTEXTO: FICHA DE OPERARIO
    # =====================================================================
    if context == 'worker':
        asignaciones = Asignacion.query.filter(
            Asignacion.user_id == entity_id,
            Asignacion.fecha >= start_date,
            Asignacion.fecha < end_date
        ).order_by(Asignacion.fecha).all()

        raw_events = []
        for a in asignaciones:
            obra = a.obra
            if not obra and a.obra_id: obra = Obra.query.get(a.obra_id)
            obra_name = obra.nombre if obra else "Obra desconocida"
            obra_color = obra.color if obra else "#3b82f6"
            
            raw_events.append({
                'title': obra_name,
                'start_date': a.fecha,
                'end_date': a.fecha,
                'color': obra_color,
                'extendedProps': {'type': 'asignacion', 'obra_id': obra.id if obra else 0}
            })
        # Agrupamos los raw_events en bloques continuos (Capa 1)
        events.extend(merge_events_v2(raw_events, group_by=['title', 'color']))

        # --- MOTOR UNIVERSAL DE PRIORIDADES PARA FICHAJES MULTI-OBRA (Capa 2) ---
        show_fichajes = request.args.get('show_fichajes') == '1'
        
        if show_fichajes:
            from app.models import RegistroFichaje
            fichajes = RegistroFichaje.query.filter(
                RegistroFichaje.user_id == entity_id,
                RegistroFichaje.fecha >= start_date,
                RegistroFichaje.fecha < end_date
            ).all()

            # Agrupamos los fichajes que existan por fecha
            fichajes_dict = {}
            for f in fichajes:
                if f.fecha not in fichajes_dict:
                    fichajes_dict[f.fecha] = []
                fichajes_dict[f.fecha].append(f)

            # EXTRAEMOS TODAS LAS FECHAS ASIGNADAS (Para obligar a pintar la bola gris si no hay datos)
            fechas_asignadas = set(a.fecha for a in asignaciones)

            for fecha in fechas_asignadas:
                lista_fichajes = fichajes_dict.get(fecha, [])
                
                if not lista_fichajes:
                    color_final = "#94a3b8"  # ⚪ Gris (Sin datos en BD)
                    tooltip_html = f"<div style='text-align:left;'><strong>{fecha.strftime('%d/%m/%Y')}:</strong><br>⚪ Sin Registro (Aún no ha fichado)</div>"
                else:
                    estados = [f.estado for f in lista_fichajes]
                    
                    # Matriz de prioridades
                    if any(est in ['Conflicto', 'Paracaidista', 'Resuelto_Ausencia'] for est in estados):
                        color_final = "#ef4444" # 🔴 Rojo
                    elif any(est in ['Ausencia', 'Pendiente', 'Retraso'] for est in estados) or len(set(estados)) > 1:
                        color_final = "#f59e0b" # 🟠 Naranja
                    elif any(est.startswith('Resuelto') for est in estados):
                        color_final = "#3b82f6" # 🔵 Azul
                    else:
                        color_final = "#10b981" # 🟢 Verde

                    html_items = []
                    for f in lista_fichajes:
                        icono = "🔴" if f.estado in ['Conflicto', 'Paracaidista', 'Resuelto_Ausencia'] else \
                                "🟠" if f.estado in ['Ausencia', 'Pendiente', 'Retraso'] else \
                                "🔵" if f.estado.startswith('Resuelto') else \
                                "⚪" if f.estado == 'Sin_Registro' else "🟢"
                        nom_obra = f.obra_planificada.nombre if f.obra_planificada else "Obra Externa"
                        html_items.append(f"<li>{icono} <b>{nom_obra}</b>: {f.estado.replace('_', ' ')}</li>")

                    tooltip_html = f"<div style='text-align:left;'><strong style='border-bottom:1px solid #ccc; padding-bottom:3px; display:block; margin-bottom:5px;'>Fichajes ({fecha.strftime('%d/%m/%Y')}):</strong><ul style='padding-left:15px; margin-bottom:0; font-size:0.85em; list-style:none;'>{''.join(html_items)}</ul></div>"

                events.append({
                    "start": fecha.strftime("%Y-%m-%d"),
                    "display": "background",
                    "extendedProps": {
                        "isFichaje": True,
                        "estado_color": color_final,
                        "tooltipContent": tooltip_html
                    }
                })

        # --- AÑADIR SOLICITUDES ---
        solicitudes = Solicitud.query.filter(
            Solicitud.empleado_id == entity_id,
            Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO']),
            Solicitud.fecha_inicio <= end_date,
            Solicitud.fecha_fin >= start_date
        ).all()

        for s in solicitudes:
            accion = getattr(s, 'accion', 'ASIGNAR')
            url_sol = url_for('admin.solicitud_detail', solicitud_id=s.id)
            nom_obra = s.obra.nombre if s.obra else '?'

            if accion == 'DESASIGNAR':
                title = "LIBRE (Salida)"
                color = "#dc3545"
                visual_end = s.fecha_fin
                if s.comentarios and 'all_obra' in s.comentarios:
                    visual_end = s.obra.fecha_fin if (s.obra and s.obra.fecha_fin) else s.fecha_inicio + timedelta(days=365)
            else:
                title = f"Solicitado: {nom_obra}"
                color = "#F59E0B"
                visual_end = s.fecha_fin

            end_to_draw = min(visual_end, end_date)
            events.append({
                "title": title,
                "start": s.fecha_inicio.strftime("%Y-%m-%d"),
                "end": (end_to_draw + timedelta(days=1)).strftime("%Y-%m-%d"),
                "color": color,
                "url": url_sol, # URL PARA REDIRIGIR AL CLICAR
                "extendedProps": {"type": "request"}
            })

    # =====================================================================
    # 2. CONTEXTO: FICHA DE OBRA
    # =====================================================================
    elif context == 'obra':
        asignaciones = Asignacion.query.filter(
            Asignacion.obra_id == entity_id,
            Asignacion.fecha >= start_date,
            Asignacion.fecha < end_date
        ).order_by(Asignacion.fecha).all()

        if mode == 'empleados':
            raw_events = []
            for a in asignaciones:
                worker = getattr(a, 'user_obj', getattr(a, 'user', None))
                if not worker and a.user_id: worker = User.query.get(a.user_id)
                if not worker: continue

                if a.company:
                    c_name, c_color = a.company.nombre, a.company.color
                elif worker.company_rel:
                    c_name, c_color = worker.company_rel.nombre, worker.company_rel.color
                else:
                    c_name, c_color = "Sin Empresa", "#10b981"

                raw_events.append({
                    'title': f"{worker.name} {worker.lastname} ({c_name})",
                    'start_date': a.fecha,
                    'end_date': a.fecha,
                    'color': c_color,
                    'extendedProps': {'type': 'asignacion', 'worker_id': worker.id}
                })
            events.extend(merge_events_v2(raw_events, group_by=['title', 'color']))
        
        elif mode == 'empresas':
            events.extend(procesar_bloques_empresa(asignaciones))

        # --- AÑADIR SOLICITUDES ---
        solicitudes = Solicitud.query.filter(
            Solicitud.obra_id == entity_id,
            Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO']),
            Solicitud.fecha_inicio <= end_date,
            Solicitud.fecha_fin >= start_date
        ).all()

        for s in solicitudes:
            accion = getattr(s, 'accion', 'ASIGNAR')
            url_sol = url_for('admin.solicitud_detail', solicitud_id=s.id)

            if s.tipo == 'CONCRETA':
                emp_name = s.empleado.name if s.empleado else '?'
                title = f"BAJA: {emp_name}" if accion == 'DESASIGNAR' else f"FALTA: {emp_name}"
            else:
                faltan = s.cantidad_solicitada - s.cantidad_cubierta
                if faltan <= 0: continue
                title = f"FALTAN: {faltan} ({s.perfil_categoria or 'Cualquiera'})"

            color = "#dc3545" if accion == 'DESASIGNAR' else "#F59E0B"
            visual_end = s.fecha_fin
            if accion == 'DESASIGNAR' and s.comentarios and 'all_obra' in s.comentarios:
                visual_end = s.obra.fecha_fin if (s.obra and s.obra.fecha_fin) else s.fecha_inicio + timedelta(days=365)

            end_to_draw = min(visual_end, end_date)
            events.append({
                "title": title,
                "start": s.fecha_inicio.strftime("%Y-%m-%d"),
                "end": (end_to_draw + timedelta(days=1)).strftime("%Y-%m-%d"),
                "color": color,
                "url": url_sol, # URL PARA REDIRIGIR AL CLICAR
                "extendedProps": {"type": "request"}
            })

    # =====================================================================
    # 3. CONTEXTO: FICHA DE EMPRESA
    # =====================================================================
    elif context == 'empresa':
        asignaciones = Asignacion.query.outerjoin(User, Asignacion.user_id == User.id).filter(
            db.or_(Asignacion.company_id == entity_id, User.company_id == entity_id),
            Asignacion.fecha >= start_date,
            Asignacion.fecha < end_date
        ).order_by(Asignacion.fecha).all()

        raw_events = []
        for a in asignaciones:
            worker = getattr(a, 'user_obj', getattr(a, 'user', None))
            if not worker and a.user_id: worker = User.query.get(a.user_id)
            if not worker: continue

            obra = a.obra
            if not obra and a.obra_id: obra = Obra.query.get(a.obra_id)
            
            obra_name = obra.nombre if obra else "Sin Obra"
            obra_color = obra.color if obra else "#3b82f6"

            raw_events.append({
                'title': f"{worker.name} {worker.lastname} ({obra_name})",
                'start_date': a.fecha,
                'end_date': a.fecha,
                'color': obra_color,
                'extendedProps': {'type': 'asignacion', 'worker_id': worker.id, 'obra_id': obra.id if obra else 0}
            })
        
        events.extend(merge_events_v2(raw_events, group_by=['title', 'color']))

        # --- AÑADIR SOLICITUDES ---
        solicitudes = Solicitud.query.filter(
            Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO']),
            Solicitud.fecha_inicio <= end_date,
            Solicitud.fecha_fin >= start_date,
            db.or_(
                Solicitud.perfil_empresa_id == entity_id,
                Solicitud.empleado.has(User.company_id == entity_id)
            )
        ).all()

        for s in solicitudes:
            accion = getattr(s, 'accion', 'ASIGNAR')
            url_sol = url_for('admin.solicitud_detail', solicitud_id=s.id)

            if s.tipo == 'CONCRETA':
                emp_name = s.empleado.name if s.empleado else '?'
                title = f"BAJA: {emp_name} ({s.obra.nombre})" if accion == 'DESASIGNAR' else f"FALTA: {emp_name} ({s.obra.nombre})"
            else:
                faltan = s.cantidad_solicitada - s.cantidad_cubierta
                if faltan <= 0: continue
                title = f"FALTAN: {faltan} ({s.obra.nombre})"

            color = "#dc3545" if accion == 'DESASIGNAR' else "#F59E0B"
            visual_end = s.fecha_fin
            if accion == 'DESASIGNAR' and s.comentarios and 'all_obra' in s.comentarios:
                visual_end = s.obra.fecha_fin if (s.obra and s.obra.fecha_fin) else s.fecha_inicio + timedelta(days=365)

            end_to_draw = min(visual_end, end_date)
            events.append({
                "title": title,
                "start": s.fecha_inicio.strftime("%Y-%m-%d"),
                "end": (end_to_draw + timedelta(days=1)).strftime("%Y-%m-%d"),
                "color": color,
                "url": url_sol, # URL PARA REDIRIGIR AL CLICAR
                "extendedProps": {"type": "request"}
            })
    # =====================================================================
    # 4. CONTEXTO: DETALLE DE SOLICITUD
    # =====================================================================
    elif context == 'solicitud':
        solicitud = Solicitud.query.get(entity_id)
        if not solicitud:
            return jsonify([])

        # Cargamos las asignaciones de la obra en el rango visible
        asignaciones = Asignacion.query.filter(
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.fecha >= start_date,
            Asignacion.fecha < end_date
        ).all()

        raw_events = []
        
        if solicitud.tipo == 'CONCRETA' and solicitud.empleado_id:
            # Filtrar asignaciones solo del trabajador solicitado
            fechas_asignadas = {a.fecha for a in asignaciones if a.user_id == solicitud.empleado_id}
            accion = getattr(solicitud, 'accion', 'ASIGNAR')
            
            curr = max(solicitud.fecha_inicio, start_date)
            # Ajuste para las bajas indefinidas (las prolongamos visualmente)
            fin_visual = solicitud.fecha_fin
            if accion == 'DESASIGNAR' and solicitud.comentarios and 'all_obra' in solicitud.comentarios:
                fin_visual = solicitud.obra.fecha_fin if (solicitud.obra and solicitud.obra.fecha_fin) else end_date

            fin_loop = min(fin_visual, end_date - timedelta(days=1))
            
            while curr <= fin_loop:
                esta_asignado = curr in fechas_asignadas
                if accion == 'ASIGNAR':
                    if esta_asignado:
                        raw_events.append({'title': '✅ Asignado', 'start_date': curr, 'end_date': curr, 'color': '#10B981'})
                    else:
                        raw_events.append({'title': '⚠️ Falta asignar', 'start_date': curr, 'end_date': curr, 'color': '#F59E0B'})
                elif accion == 'DESASIGNAR':
                    if esta_asignado: # Si es una baja y sigue asignado, está pendiente de borrarse (rojo)
                        raw_events.append({'title': '❌ Pendiente Baja', 'start_date': curr, 'end_date': curr, 'color': '#dc3545'})
                curr += timedelta(days=1)

        elif solicitud.tipo == 'GENERICA':
            # Contar cuántos están cubriendo el perfil cada día
            day_counts = defaultdict(int)
            for a in asignaciones:
                worker = getattr(a, 'user_obj', getattr(a, 'user', None))
                if not worker and a.user_id: worker = User.query.get(a.user_id)
                if not worker or worker.is_deleted: continue
                
                # Si la solicitud exige una empresa concreta, filtramos y descartamos a los demás
                if solicitud.perfil_empresa_id and worker.company_id != solicitud.perfil_empresa_id:
                    continue
                day_counts[a.fecha] += 1
                
            curr = max(solicitud.fecha_inicio, start_date)
            fin_loop = min(solicitud.fecha_fin, end_date - timedelta(days=1))
            
            while curr <= fin_loop:
                assigned = day_counts[curr]
                missing = solicitud.cantidad_solicitada - assigned
                
                if assigned > 0:
                    raw_events.append({
                        'title': f"✅ Cubiertos ({min(assigned, solicitud.cantidad_solicitada)})", 
                        'start_date': curr, 'end_date': curr, 'color': '#10B981'
                    })
                if missing > 0:
                    raw_events.append({
                        'title': f"⚠️ Faltan ({missing})", 
                        'start_date': curr, 'end_date': curr, 'color': '#F59E0B'
                    })
                curr += timedelta(days=1)
                
        # Usamos nuestro motor de fusión para agrupar los días seguidos y que quede limpio
        events.extend(merge_events_v2(raw_events, group_by=['title', 'color']))


    return jsonify(events)


def merge_events_v2(raw_events, group_by):
    groups = defaultdict(list)
    for ev in raw_events:
        # Clave dinámica basada en los campos de group_by
        key = tuple(ev.get(k) for k in group_by)
        groups[key].append(ev)
        
    merged_events = []
    for key, ev_list in groups.items():
        ev_list.sort(key=lambda x: x['start_date'])
        if not ev_list: continue
        
        current = ev_list[0].copy()
        for next_ev in ev_list[1:]:
            if (next_ev['start_date'] - current['end_date']).days == 1:
                current['end_date'] = next_ev['end_date']
            else:
                merged_events.append(format_event(current))
                current = next_ev.copy()
        merged_events.append(format_event(current))
        
    return merged_events

def format_event(ev):
    end_date_exclusive = (ev['end_date'] + timedelta(days=1)).strftime("%Y-%m-%d")
    return {
        'title': ev['title'],
        'start': ev['start_date'].strftime("%Y-%m-%d"),
        'end': end_date_exclusive,
        'color': ev['color'],
        'extendedProps': ev.get('extendedProps', {})
    }

def procesar_bloques_empresa(asignaciones):
    day_counts = defaultdict(lambda: defaultdict(int))
    day_workers = defaultdict(lambda: defaultdict(list))
    colors = {}
    company_ids = {} # <-- NUEVO: Guardamos el ID de la empresa
    
    for a in asignaciones:
        worker = getattr(a, 'user_obj', getattr(a, 'user', None))
        if not worker and a.user_id: worker = User.query.get(a.user_id)
        if not worker: continue

        if a.company:
            c_name, c_color = a.company.nombre, a.company.color
            c_id = a.company.id # <-- Extraemos la ID
        elif worker.company_rel:
            c_name, c_color = worker.company_rel.nombre, worker.company_rel.color
            c_id = worker.company_rel.id # <-- Extraemos la ID
        else:
            c_name, c_color = "Sin Empresa", "#6366f1"
            c_id = 0 # <-- 0 para los que no tienen empresa
            
        day_counts[c_name][a.fecha] += 1
        day_workers[c_name][a.fecha].append(f"{worker.name} {worker.lastname}") 
        colors[c_name] = c_color
        company_ids[c_name] = c_id # <-- Lo guardamos en el diccionario

    final_events = []
    for empresa, days in day_counts.items():
        sorted_dates = sorted(days.keys())
        if not sorted_dates: continue
        
        current_start = sorted_dates[0]
        current_count = days[current_start]
        current_workers = sorted(day_workers[empresa][current_start]) 
        last_date = current_start
        empresa_id = company_ids[empresa] # <-- Rescatamos el ID para esta empresa
        
        for date_obj in sorted_dates[1:]:
            workers_today = sorted(day_workers[empresa][date_obj])
            
            # Cortamos el bloque si: hay hueco, cambia el número, o cambian LOS NOMBRES
            if (date_obj - last_date).days > 1 or days[date_obj] != current_count or workers_today != current_workers:
                # Le pasamos el empresa_id a la función creadora
                final_events.append(crear_evento_empresa(empresa, empresa_id, current_start, last_date, current_count, colors[empresa], current_workers))
                current_start = date_obj
                current_count = days[date_obj]
                current_workers = workers_today
                
            last_date = date_obj
            
        # Añadir el último bloque de la iteración
        final_events.append(crear_evento_empresa(empresa, empresa_id, current_start, last_date, current_count, colors[empresa], current_workers))
        
    return final_events

def crear_evento_empresa(empresa, empresa_id, start_date, end_date, count, color, workers_list):
    end_date_exclusive = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
    
    if not color or color.strip() == "":
        color = "#f3f4f6"
        
    text_color = "#ffffff"
    try:
        hex_c = color.lstrip('#')
        if len(hex_c) == 6:
            r, g, b = int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16)
            if ((r * 299) + (g * 587) + (b * 114)) / 1000 >= 128:
                text_color = "#111827" 
    except Exception:
        pass 
        
    html_list = "".join([f"<li>{w}</li>" for w in workers_list])
    tooltip_html = f"<div style='text-align:left;'><strong style='border-bottom: 1px solid #ccc; padding-bottom: 3px; display: block; margin-bottom: 5px;'>{empresa} ({count} operarios)</strong><ul style='padding-left:15px; margin-bottom:0; font-size: 0.85em;'>{html_list}</ul></div>"
    
    return {
        'title': f"({count}) {empresa}",
        'start': start_date.strftime("%Y-%m-%d"),
        'end': end_date_exclusive,
        'backgroundColor': color,       
        'textColor': text_color,        
        'extendedProps': {
            'type': 'empresa_group', 
            'empresa': empresa,
            'empresa_id': empresa_id,  # <--- AQUÍ ESTÁ LA MAGIA, AHORA SÍ VIAJA AL JAVASCRIPT
            'tooltipContent': tooltip_html
        }
    }


@api_bp.route('/person-day-timeline/<int:user_id>/<string:fecha_str>', methods=['GET'])
@login_required
def person_day_timeline(user_id, fecha_str):
    from app.services.person_day_timeline_service import build_person_day_timeline

    if current_user.role != ROLE_ADMIN:
        return jsonify({'success': False, 'error': 'Acceso denegado'}), 403

    data = build_person_day_timeline(user_id, fecha_str)
    if not data:
        return jsonify({'success': False, 'error': 'Operario no encontrado'}), 404
    return jsonify(data)
