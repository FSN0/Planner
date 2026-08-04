from flask import Blueprint, request, jsonify, url_for
from flask_login import login_required, current_user
# IMPORTAMOS db AQUÍ
from app import db 
from app.models import Asignacion, User, Solicitud, Obra, Company, UserObraConfig, ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL
from app.services.permission_service import is_laboral
from datetime import datetime, timedelta
import json
from collections import defaultdict # AÑADIDO PARA LA LÓGICA DE AGRUPACIÓN
# IMPORTAMOS LA LÓGICA COMPARTIDA


api_bp = Blueprint('api_v6', __name__, url_prefix='/api/v6')


def _obra_label(obra, fallback='Obra desconocida'):
    """Formato consistente código - nombre para calendarios y selectores."""
    if not obra:
        return fallback
    if getattr(obra, 'codigo', None):
        return f"{obra.codigo} - {obra.nombre}"
    return obra.nombre or fallback


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
    elif current_user.role == ROLE_LABORAL:
        obras = Obra.query.filter_by(is_deleted=False).order_by(Obra.nombre).all()
    else:
        obras = []
        
    # 2. Usuarios (Siguen saliendo todos de momento, a menos que quieras filtrarlos también)
    users = User.query.filter_by(is_deleted=False).order_by(User.name).all()
    
    return jsonify({
        'obras': [
            {
                'id': o.id,
                'text': f"{o.codigo} - {o.nombre}" if o.codigo else o.nombre,
                'codigo': o.codigo,
                'nombre': o.nombre,
            }
            for o in obras
        ],
        'users': [{'id': u.id, 'text': f"{u.name} {u.lastname}"} for u in users]
    })
    
@api_bp.route('/toggle_pin_obra', methods=['POST'])
@login_required
def toggle_pin_obra():
    if is_laboral(current_user):
        return jsonify({'success': False, 'message': 'Modo solo lectura'}), 403
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
    if is_laboral(current_user):
        return jsonify({'success': False, 'message': 'Modo solo lectura'}), 403
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
        from app.services.leave_service import (
            apply_leave_overlay_title,
            build_leaves_by_user,
            leave_covering,
            leave_overlay_meta,
        )
        from app.models import AusenciaPlanificada

        asignaciones = Asignacion.query.filter(
            Asignacion.user_id == entity_id,
            Asignacion.fecha >= start_date,
            Asignacion.fecha < end_date
        ).order_by(Asignacion.fecha).all()

        # end_date de FullCalendar es exclusivo → índice inclusivo
        range_end_inclusive = end_date - timedelta(days=1) if end_date > start_date else end_date
        leaves_idx = build_leaves_by_user([entity_id], start_date, range_end_inclusive)
        user_leaves = leaves_idx.get(entity_id, [])
        assigned_dates = {a.fecha for a in asignaciones}

        raw_events = []
        vehicle_by_date = {}
        vehicle_meta_by_date = {}
        try:
            from app.services.entity_panel_service import get_worker_vehicle_day_map
            worker = User.query.get(entity_id)
            if worker:
                vehicle_meta_by_date = get_worker_vehicle_day_map(
                    worker, start_date, end_date, end_exclusive=True
                )
                vehicle_by_date = {
                    d: info['label'] for d, info in vehicle_meta_by_date.items()
                }
        except Exception:
            vehicle_by_date = {}
            vehicle_meta_by_date = {}

        for a in asignaciones:
            obra = a.obra
            if not obra and a.obra_id: obra = Obra.query.get(a.obra_id)
            obra_name = _obra_label(obra)
            v_label = vehicle_by_date.get(a.fecha)
            v_meta = vehicle_meta_by_date.get(a.fecha) or {}
            obra_color = obra.color if obra else "#3b82f6"
            leave = leave_covering(user_leaves, a.fecha)
            title, overlay_color, is_overlay = apply_leave_overlay_title(obra_name, leave)
            color = overlay_color or obra_color
            raw_events.append({
                'title': title,
                'start_date': a.fecha,
                'end_date': a.fecha,
                'color': color,
                'extendedProps': {
                    'type': 'asignacion',
                    'obra_id': obra.id if obra else 0,
                    'vehiculo_label': v_label,
                    'vehiculo_id': v_meta.get('vehiculo_id'),
                    'vehiculo_source': v_meta.get('source'),
                    'en_ausencia': is_overlay,
                    'ausencia_tipo': leave.tipo if leave else None,
                    'ausencia_estado': leave.estado if leave else None,
                }
            })
        events.extend(merge_events_v2(raw_events, group_by=['title', 'color']))

        # Vehículo siempre como evento propio (también si hay obra ese día)
        from app.services.vehicle_availability_service import (
            VEHICLE_COLOR_EFECTIVO,
            VEHICLE_COLOR_PLAN_MUERTO,
            VEHICLE_COLOR_PLAN_OK,
        )
        raw_veh = []
        for d, v_label in vehicle_by_date.items():
            v_meta = vehicle_meta_by_date.get(d) or {}
            title = f"Vehículo: {v_label}"
            if v_meta.get('km') is not None:
                try:
                    title = f"{title} · {int(v_meta['km'])} km"
                except (TypeError, ValueError):
                    pass
            if v_meta.get('en_ausencia') and v_meta.get('ausencia_tipo'):
                title = f"{title} · {v_meta['ausencia_tipo']}"
            elif v_meta.get('mismatch') and v_meta.get('effective_other'):
                title = f"{title} · lo usó {v_meta['effective_other']}"

            plan_status = v_meta.get('plan_status') or 'ok'
            source = v_meta.get('source') or 'planificado'
            if plan_status == 'muerto':
                color = VEHICLE_COLOR_PLAN_MUERTO
                ev_type = 'vehiculo'
            elif plan_status == 'efectivo' or source == 'odoo':
                color = VEHICLE_COLOR_EFECTIVO
                ev_type = 'vehiculo_odoo'
            else:
                color = VEHICLE_COLOR_PLAN_OK
                ev_type = 'vehiculo'
            raw_veh.append({
                'title': title,
                'start_date': d,
                'end_date': d,
                'color': color,
                'extendedProps': {
                    'type': ev_type,
                    'source': source,
                    'plan_status': plan_status,
                    'vehiculo_label': v_label,
                    'vehiculo_id': v_meta.get('vehiculo_id'),
                    'km': v_meta.get('km'),
                    'en_ausencia': bool(v_meta.get('en_ausencia')),
                    'mismatch': bool(v_meta.get('mismatch')),
                }
            })
        if raw_veh:
            events.extend(merge_events_v2(raw_veh, group_by=['title', 'color']))

        # Ausencias en días SIN asignación (sigue viéndose el periodo de vacaciones)
        leaves = AusenciaPlanificada.query.filter(
            AusenciaPlanificada.user_id == entity_id,
            AusenciaPlanificada.fecha_inicio < end_date,
            AusenciaPlanificada.fecha_fin >= start_date,
            AusenciaPlanificada.estado == 'aprobada',
        ).all()
        for leave in leaves:
            meta = leave_overlay_meta(leave)
            if not meta:
                continue
            # Expandir por días sin asignación para no duplicar overlay de asignación
            day = max(leave.fecha_inicio, start_date)
            end_leave = min(leave.fecha_fin, range_end_inclusive)
            gap_start = None
            gap_end = None

            def flush_gap(gs, ge):
                if gs is None:
                    return
                end_excl = ge + timedelta(days=1)
                events.append({
                    'title': meta['label_prefix'],
                    'start': gs.strftime('%Y-%m-%d'),
                    'end': min(end_excl, end_date).strftime('%Y-%m-%d'),
                    'color': meta['color'],
                    'extendedProps': {
                        'type': 'ausencia',
                        'ausencia_id': leave.id,
                        'estado': leave.estado,
                        'tipo': leave.tipo,
                        'conflicto': False,
                    },
                })

            while day <= end_leave:
                if day not in assigned_dates:
                    if gap_start is None:
                        gap_start = day
                    gap_end = day
                else:
                    flush_gap(gap_start, gap_end)
                    gap_start = gap_end = None
                day = day + timedelta(days=1)
            flush_gap(gap_start, gap_end)

        # --- MOTOR UNIVERSAL DE PRIORIDADES PARA FICHAJES MULTI-OBRA (Capa 2) ---
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
                        nom_obra = _obra_label(f.obra_planificada, fallback='Obra Externa')
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
            nom_obra = _obra_label(s.obra, fallback='?')

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
        from app.services.leave_service import (
            apply_leave_overlay_title,
            build_leaves_by_user,
            leave_covering,
        )

        asignaciones = Asignacion.query.filter(
            Asignacion.obra_id == entity_id,
            Asignacion.fecha >= start_date,
            Asignacion.fecha < end_date
        ).order_by(Asignacion.fecha).all()

        range_end_inclusive = end_date - timedelta(days=1) if end_date > start_date else end_date
        leaves_idx = build_leaves_by_user(
            {a.user_id for a in asignaciones}, start_date, range_end_inclusive
        )

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

                base_title = f"{worker.name} {worker.lastname} ({c_name})"
                leave = leave_covering(leaves_idx.get(worker.id, []), a.fecha)
                title, overlay_color, is_overlay = apply_leave_overlay_title(
                    base_title, leave, name_first=True
                )
                raw_events.append({
                    'title': title,
                    'start_date': a.fecha,
                    'end_date': a.fecha,
                    'color': overlay_color or c_color,
                    'extendedProps': {
                        'type': 'asignacion',
                        'worker_id': worker.id,
                        'en_ausencia': is_overlay,
                        'ausencia_tipo': leave.tipo if leave else None,
                    }
                })
            events.extend(merge_events_v2(raw_events, group_by=['title', 'color']))
        
        elif mode == 'empresas':
            events.extend(procesar_bloques_empresa(asignaciones, leaves_by_user=leaves_idx))

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
        from app.services.leave_service import (
            apply_leave_overlay_title,
            build_leaves_by_user,
            leave_covering,
        )

        asignaciones = Asignacion.query.outerjoin(User, Asignacion.user_id == User.id).filter(
            db.or_(Asignacion.company_id == entity_id, User.company_id == entity_id),
            Asignacion.fecha >= start_date,
            Asignacion.fecha < end_date
        ).order_by(Asignacion.fecha).all()

        range_end_inclusive = end_date - timedelta(days=1) if end_date > start_date else end_date
        leaves_idx = build_leaves_by_user(
            {a.user_id for a in asignaciones}, start_date, range_end_inclusive
        )

        raw_events = []
        for a in asignaciones:
            worker = getattr(a, 'user_obj', getattr(a, 'user', None))
            if not worker and a.user_id: worker = User.query.get(a.user_id)
            if not worker: continue

            obra = a.obra
            if not obra and a.obra_id: obra = Obra.query.get(a.obra_id)
            
            obra_name = _obra_label(obra, fallback='Sin Obra')
            obra_color = obra.color if obra else "#3b82f6"
            base_title = f"{worker.name} {worker.lastname} ({obra_name})"
            leave = leave_covering(leaves_idx.get(worker.id, []), a.fecha)
            title, overlay_color, is_overlay = apply_leave_overlay_title(
                base_title, leave, name_first=True
            )

            raw_events.append({
                'title': title,
                'start_date': a.fecha,
                'end_date': a.fecha,
                'color': overlay_color or obra_color,
                'extendedProps': {
                    'type': 'asignacion',
                    'worker_id': worker.id,
                    'obra_id': obra.id if obra else 0,
                    'en_ausencia': is_overlay,
                }
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
            obra_txt = _obra_label(s.obra, fallback='?')

            if s.tipo == 'CONCRETA':
                emp_name = s.empleado.name if s.empleado else '?'
                title = f"BAJA: {emp_name} ({obra_txt})" if accion == 'DESASIGNAR' else f"FALTA: {emp_name} ({obra_txt})"
            else:
                faltan = s.cantidad_solicitada - s.cantidad_cubierta
                if faltan <= 0: continue
                title = f"FALTAN: {faltan} ({obra_txt})"

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

    # =====================================================================
    # 5. CONTEXTO: FICHA DE VEHÍCULO
    # =====================================================================
    elif context == 'vehiculo':
        from app.models import AsignacionVehiculo, RegistroOdometro, SolicitudVehiculo, Vehiculo
        from app.services.vehicle_sync_service import _build_user_indexes, _match_driver_user

        vehiculo = Vehiculo.query.get(entity_id)
        if not vehiculo:
            return jsonify([])

        asig_veh = AsignacionVehiculo.query.filter(
            AsignacionVehiculo.vehiculo_id == entity_id,
            AsignacionVehiculo.fecha >= start_date,
            AsignacionVehiculo.fecha < end_date,
        ).order_by(AsignacionVehiculo.fecha).all()
        planned_by_date = {av.fecha: av for av in asig_veh}

        odo_regs = RegistroOdometro.query.filter(
            RegistroOdometro.vehiculo_id == entity_id,
            RegistroOdometro.fecha >= start_date,
            RegistroOdometro.fecha < end_date,
        ).order_by(RegistroOdometro.fecha).all()
        odo_by_date = {r.fecha: r for r in odo_regs}

        from app.services.leave_service import (
            build_leaves_by_user,
            leave_covering,
        )
        from app.services.vehicle_availability_service import (
            VEHICLE_COLOR_EFECTIVO,
            VEHICLE_COLOR_ODOO_SOLO,
            VEHICLE_COLOR_PLAN_MUERTO,
            VEHICLE_COLOR_PLAN_OK,
        )
        from app.models import LEAVE_STATUS_APROBADA

        users_by_odoo, users_by_name = _build_user_indexes()
        raw_events = []

        planned_user_ids = {av.user_id for av in asig_veh if av.user_id}
        range_end_inclusive = end_date - timedelta(days=1) if end_date > start_date else end_date
        leaves_idx = build_leaves_by_user(
            list(planned_user_ids), start_date, range_end_inclusive
        ) if planned_user_ids else {}

        def _obra_for_user_day(user_id, fecha):
            if not user_id:
                return None
            obra_asig = Asignacion.query.filter_by(user_id=user_id, fecha=fecha).first()
            if not obra_asig:
                return None
            return obra_asig.obra or (
                Obra.query.get(obra_asig.obra_id) if obra_asig.obra_id else None
            )

        def _resolve_odoo_driver(reg):
            matched = _match_driver_user(
                reg.odoo_driver_partner_id,
                reg.odoo_driver_name,
                users_by_odoo,
                users_by_name,
            )
            if matched:
                return matched, f"{matched.name} {matched.lastname}", False
            name = (reg.odoo_driver_name or '').strip()
            if name:
                return None, f"{name} (no está en el programa)", True
            return None, "Uso Odoo (sin conductor)", True

        def _leave_for(user_id, fecha):
            leave = leave_covering(leaves_idx.get(user_id, []), fecha)
            if leave and leave.estado == LEAVE_STATUS_APROBADA:
                return leave
            return None

        all_dates = sorted(set(planned_by_date.keys()) | set(odo_by_date.keys()))
        for fecha in all_dates:
            av = planned_by_date.get(fecha)
            reg = odo_by_date.get(fecha)

            planned_worker = None
            planned_name = None
            if av:
                planned_worker = av.user or (User.query.get(av.user_id) if av.user_id else None)
                planned_name = (
                    f"{planned_worker.name} {planned_worker.lastname}"
                    if planned_worker else f"#{av.user_id}"
                )

            odoo_worker = None
            odoo_title = None
            odoo_external = False
            has_odoo_usage = bool(
                reg and (
                    reg.valor is not None
                    or (reg.odoo_driver_name or '').strip()
                    or reg.odoo_driver_partner_id
                )
            )
            if has_odoo_usage:
                odoo_worker, odoo_title, odoo_external = _resolve_odoo_driver(reg)

            leave = _leave_for(av.user_id, fecha) if av else None
            on_leave = bool(leave)

            # Caso 1: solo planificación
            if av and not has_odoo_usage:
                obra = _obra_for_user_day(av.user_id, fecha)
                title = planned_name
                if on_leave:
                    tipo = (leave.tipo or 'Ausencia').strip() or 'Ausencia'
                    title = f"{planned_name} · {tipo}"
                elif obra:
                    title = f"{planned_name} · {_obra_label(obra)}"
                color = (
                    VEHICLE_COLOR_PLAN_MUERTO if on_leave
                    else VEHICLE_COLOR_PLAN_OK
                )
                raw_events.append({
                    'title': title,
                    'start_date': fecha,
                    'end_date': fecha,
                    'color': color,
                    'extendedProps': {
                        'type': 'vehiculo',
                        'source': 'planificado',
                        'plan_status': 'muerto' if on_leave else 'ok',
                        'worker_id': av.user_id,
                        'vehiculo_id': entity_id,
                        'obra_id': obra.id if obra else None,
                        'en_ausencia': on_leave,
                        'ausencia_tipo': leave.tipo if leave else None,
                    },
                })
                continue

            # Caso 2: solo uso Odoo (lo habitual si aún no hay AsignacionVehiculo)
            if has_odoo_usage and not av:
                obra = _obra_for_user_day(odoo_worker.id, fecha) if odoo_worker else None
                title = odoo_title
                if reg and reg.valor is not None:
                    title = f"{title} · {int(reg.valor)} km"
                if obra:
                    title = f"{title} · {_obra_label(obra)}"
                color = VEHICLE_COLOR_ODOO_SOLO if odoo_external else VEHICLE_COLOR_EFECTIVO
                raw_events.append({
                    'title': title,
                    'start_date': fecha,
                    'end_date': fecha,
                    'color': color,
                    'extendedProps': {
                        'type': 'vehiculo_odoo',
                        'source': 'odoo',
                        'plan_status': 'efectivo',
                        'worker_id': odoo_worker.id if odoo_worker else None,
                        'vehiculo_id': entity_id,
                        'obra_id': obra.id if obra else None,
                        'external': odoo_external,
                        'km': reg.valor if reg else None,
                    },
                })
                continue

            # Caso 3: planificación + Odoo el mismo día
            if av and has_odoo_usage:
                same_person = bool(
                    odoo_worker and av.user_id and odoo_worker.id == av.user_id
                )
                obra_planned = _obra_for_user_day(av.user_id, fecha)
                km_bit = f" · {int(reg.valor)} km" if reg and reg.valor is not None else ""

                if same_person and not on_leave:
                    title = planned_name
                    if obra_planned:
                        title = f"{planned_name} · {_obra_label(obra_planned)}"
                    title = f"{title}{km_bit}"
                    color = VEHICLE_COLOR_PLAN_OK
                    raw_events.append({
                        'title': title,
                        'start_date': fecha,
                        'end_date': fecha,
                        'color': color,
                        'extendedProps': {
                            'type': 'vehiculo',
                            'source': 'ambos',
                            'plan_status': 'ok',
                            'worker_id': av.user_id,
                            'vehiculo_id': entity_id,
                            'obra_id': obra_planned.id if obra_planned else None,
                            'km': reg.valor if reg else None,
                        },
                    })
                elif same_person and on_leave:
                    tipo = (leave.tipo or 'Ausencia').strip() or 'Ausencia'
                    title = f"{planned_name} · {tipo}{km_bit}"
                    raw_events.append({
                        'title': title,
                        'start_date': fecha,
                        'end_date': fecha,
                        'color': VEHICLE_COLOR_PLAN_MUERTO,
                        'extendedProps': {
                            'type': 'vehiculo',
                            'source': 'ambos',
                            'plan_status': 'muerto',
                            'worker_id': av.user_id,
                            'vehiculo_id': entity_id,
                            'obra_id': obra_planned.id if obra_planned else None,
                            'en_ausencia': True,
                            'ausencia_tipo': leave.tipo if leave else None,
                            'km': reg.valor if reg else None,
                        },
                    })
                else:
                    # Plan muerto (otro conductor Odoo y/o ausencia): etiqueta roja
                    dead_title = planned_name
                    if on_leave:
                        tipo = (leave.tipo or 'Ausencia').strip() or 'Ausencia'
                        dead_title = f"{planned_name} · {tipo}"
                    elif obra_planned:
                        dead_title = f"{planned_name} · {_obra_label(obra_planned)}"
                    raw_events.append({
                        'title': dead_title,
                        'start_date': fecha,
                        'end_date': fecha,
                        'color': VEHICLE_COLOR_PLAN_MUERTO,
                        'extendedProps': {
                            'type': 'vehiculo',
                            'source': 'planificado',
                            'plan_status': 'muerto',
                            'worker_id': av.user_id,
                            'vehiculo_id': entity_id,
                            'obra_id': obra_planned.id if obra_planned else None,
                            'en_ausencia': on_leave,
                            'ausencia_tipo': leave.tipo if leave else None,
                            'mismatch': not same_person,
                        },
                    })
                    # Conductor efectivo (Odoo): etiqueta verde aparte
                    obra_odoo = (
                        _obra_for_user_day(odoo_worker.id, fecha) if odoo_worker else None
                    )
                    effective_title = odoo_title or 'Conductor Odoo'
                    if km_bit:
                        effective_title = f"{effective_title}{km_bit}"
                    if obra_odoo:
                        effective_title = f"{effective_title} · {_obra_label(obra_odoo)}"
                    raw_events.append({
                        'title': effective_title,
                        'start_date': fecha,
                        'end_date': fecha,
                        'color': (
                            VEHICLE_COLOR_ODOO_SOLO if odoo_external
                            else VEHICLE_COLOR_EFECTIVO
                        ),
                        'extendedProps': {
                            'type': 'vehiculo_odoo',
                            'source': 'odoo',
                            'plan_status': 'efectivo',
                            'worker_id': odoo_worker.id if odoo_worker else None,
                            'vehiculo_id': entity_id,
                            'obra_id': obra_odoo.id if obra_odoo else None,
                            'external': odoo_external,
                            'km': reg.valor if reg else None,
                            'mismatch': not same_person,
                        },
                    })

        events.extend(merge_events_v2(raw_events, group_by=['title', 'color']))

        # Solicitudes abiertas de este vehículo
        try:
            solicitudes = SolicitudVehiculo.query.filter(
                SolicitudVehiculo.vehiculo_id == entity_id,
                SolicitudVehiculo.estado.in_(('PENDIENTE', 'EN_PROCESO')),
                SolicitudVehiculo.fecha_inicio < end_date,
                SolicitudVehiculo.fecha_fin >= start_date,
            ).all()
            for s in solicitudes:
                emp = s.empleado
                emp_name = f"{emp.name} {emp.lastname}" if emp else '?'
                accion = (s.accion or 'ASIGNAR').upper()
                title = f"{'BAJA' if accion == 'DESASIGNAR' else 'SOL'}: {emp_name}"
                color = "#dc3545" if accion == 'DESASIGNAR' else "#F59E0B"
                end_to_draw = min(s.fecha_fin, end_date - timedelta(days=1))
                events.append({
                    "title": title,
                    "start": s.fecha_inicio.strftime("%Y-%m-%d"),
                    "end": (end_to_draw + timedelta(days=1)).strftime("%Y-%m-%d"),
                    "color": color,
                    "extendedProps": {
                        "type": "solicitud_vehiculo",
                        "worker_id": s.empleado_id,
                        "vehiculo_id": entity_id,
                    },
                })
        except Exception:
            pass

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

def procesar_bloques_empresa(asignaciones, leaves_by_user=None):
    from app.services.leave_service import leave_covering, leave_overlay_meta

    leaves_by_user = leaves_by_user or {}
    day_counts = defaultdict(lambda: defaultdict(int))
    day_workers = defaultdict(lambda: defaultdict(list))
    day_leave_flags = defaultdict(lambda: defaultdict(bool))  # empresa -> fecha -> algún leave
    colors = {}
    company_ids = {}
    
    for a in asignaciones:
        worker = getattr(a, 'user_obj', getattr(a, 'user', None))
        if not worker and a.user_id: worker = User.query.get(a.user_id)
        if not worker: continue

        if a.company:
            c_name, c_color = a.company.nombre, a.company.color
            c_id = a.company.id
        elif worker.company_rel:
            c_name, c_color = worker.company_rel.nombre, worker.company_rel.color
            c_id = worker.company_rel.id
        else:
            c_name, c_color = "Sin Empresa", "#6366f1"
            c_id = 0

        leave = leave_covering(leaves_by_user.get(worker.id, []), a.fecha)
        meta = leave_overlay_meta(leave)
        label = f"{worker.name} {worker.lastname}"
        if meta:
            label = f"{label} · {meta['label_prefix']}"
            day_leave_flags[c_name][a.fecha] = True
            
        day_counts[c_name][a.fecha] += 1
        day_workers[c_name][a.fecha].append(label)
        colors[c_name] = c_color
        company_ids[c_name] = c_id

    final_events = []
    for empresa, days in day_counts.items():
        sorted_dates = sorted(days.keys())
        if not sorted_dates: continue
        
        current_start = sorted_dates[0]
        current_count = days[current_start]
        current_workers = sorted(day_workers[empresa][current_start])
        current_has_leave = day_leave_flags[empresa].get(current_start, False)
        last_date = current_start
        empresa_id = company_ids[empresa]
        
        for date_obj in sorted_dates[1:]:
            workers_today = sorted(day_workers[empresa][date_obj])
            has_leave_today = day_leave_flags[empresa].get(date_obj, False)
            
            if (
                (date_obj - last_date).days > 1
                or days[date_obj] != current_count
                or workers_today != current_workers
                or has_leave_today != current_has_leave
            ):
                final_events.append(crear_evento_empresa(
                    empresa, empresa_id, current_start, last_date, current_count,
                    colors[empresa], current_workers, en_ausencia=current_has_leave,
                ))
                current_start = date_obj
                current_count = days[date_obj]
                current_workers = workers_today
                current_has_leave = has_leave_today
                
            last_date = date_obj
            
        final_events.append(crear_evento_empresa(
            empresa, empresa_id, current_start, last_date, current_count,
            colors[empresa], current_workers, en_ausencia=current_has_leave,
        ))
        
    return final_events

def crear_evento_empresa(empresa, empresa_id, start_date, end_date, count, color, workers_list, en_ausencia=False):
    from app.services.leave_service import LEAVE_COLOR_APROBADA

    end_date_exclusive = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
    
    if en_ausencia:
        color = LEAVE_COLOR_APROBADA
    elif not color or color.strip() == "":
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
    
    title = f"({count}) {empresa}"
    if en_ausencia:
        title = f"Ausencia · {title}"

    return {
        'title': title,
        'start': start_date.strftime("%Y-%m-%d"),
        'end': end_date_exclusive,
        'backgroundColor': color,       
        'textColor': text_color,        
        'extendedProps': {
            'type': 'empresa_group',
            'empresa': empresa,
            'empresa_id': empresa_id,
            'tooltipContent': tooltip_html,
            'en_ausencia': en_ausencia,
        }
    }

@api_bp.route('/person-day-timeline/<int:user_id>/<string:fecha_str>', methods=['GET'])
@login_required
def person_day_timeline(user_id, fecha_str):
    from app.services.person_day_timeline_service import build_person_day_timeline

    if current_user.role not in (ROLE_ADMIN, ROLE_LABORAL):
        return jsonify({'success': False, 'error': 'Acceso denegado'}), 403

    data = build_person_day_timeline(user_id, fecha_str)
    if not data:
        return jsonify({'success': False, 'error': 'Operario no encontrado'}), 404
    return jsonify(data)


@api_bp.route('/person-day-timeline/<int:user_id>', methods=['GET'])
@login_required
def person_day_timeline_range(user_id):
    """Rango de fechas: ?from=YYYY-MM-DD&to=YYYY-MM-DD (uno solo = un día)."""
    from app.services.person_day_timeline_service import build_person_day_timeline_range

    if current_user.role not in (ROLE_ADMIN, ROLE_LABORAL):
        return jsonify({'success': False, 'error': 'Acceso denegado'}), 403

    fecha_from = request.args.get('from') or request.args.get('fecha_inicio')
    fecha_to = request.args.get('to') or request.args.get('fecha_fin')

    if not fecha_from and not fecha_to:
        return jsonify({
            'success': False,
            'error': 'Indica from y/o to (YYYY-MM-DD)',
        }), 400

    if fecha_from and not fecha_to:
        fecha_to = fecha_from
    elif fecha_to and not fecha_from:
        fecha_from = fecha_to

    data = build_person_day_timeline_range(user_id, fecha_from, fecha_to)
    if data is None:
        return jsonify({'success': False, 'error': 'Operario no encontrado'}), 404
    if not data.get('success'):
        return jsonify(data), 400
    return jsonify(data)

# ==============================================================================
# ENDPOINT PARA CADDY (ON-DEMAND TLS)
# ==============================================================================
@api_bp.route('/check-domain', methods=['GET'])
def check_domain():
    from app.services.tenant_domain_service import is_host_allowed_for_tls

    domain = request.args.get('domain')
    if not domain:
        return "Falta dominio", 400

    if is_host_allowed_for_tls(domain):
        return "OK", 200

    return "Not Found", 404


from app.api.odoo_alta_auth import register_odoo_alta_auth_routes  # noqa: E402
register_odoo_alta_auth_routes(api_bp)