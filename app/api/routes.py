from flask import Blueprint, request, jsonify, url_for
from flask_login import login_required, current_user
# IMPORTAMOS db AQUÍ
from app import db 
from app.models import Asignacion, User, Solicitud, Obra, Company, UserObraConfig, ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH, ROLE_OPERARIO
from app.services.permission_service import is_laboral
from app.decorators import roles_required_api
from datetime import datetime, timedelta
import json
from collections import defaultdict # AÑADIDO PARA LA LÓGICA DE AGRUPACIÓN
# IMPORTAMOS LA LÓGICA COMPARTIDA


api_bp = Blueprint('api_v6', __name__, url_prefix='/api/v6')

_ROLES_OFICINA = (ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH)


def _obra_label(obra, fallback='Obra desconocida'):
    """Formato consistente código - nombre para calendarios y selectores."""
    if not obra:
        return fallback
    if getattr(obra, 'codigo', None):
        return f"{obra.codigo} - {obra.nombre}"
    return obra.nombre or fallback


def _jefe_obra_ids():
    return [
        o.id for o in Obra.query.filter_by(
            is_deleted=False, jefe_obra_id=current_user.id
        ).all()
    ]


def _jefe_puede_ver_worker(user_id):
    """El jefe solo ve trabajadores ligados a sus obras (asignación o jefatura)."""
    if user_id == current_user.id:
        return True
    obra_ids = _jefe_obra_ids()
    if not obra_ids:
        return False
    return Asignacion.query.filter(
        Asignacion.user_id == user_id,
        Asignacion.obra_id.in_(obra_ids),
    ).first() is not None


def _autorizar_calendario(context, entity_id):
    """
    Perfiles de oficina + operario con web_access solo sobre sí mismo.
    El PIN del operario no abre calendarios ajenos (RGPD).
    """
    if current_user.role == ROLE_OPERARIO:
        if (
            getattr(current_user, 'web_access', False)
            and context == 'worker'
            and entity_id == current_user.id
        ):
            return None
        return jsonify({'success': False, 'error': 'Acceso no autorizado'}), 403

    if current_user.role not in _ROLES_OFICINA:
        return jsonify({'success': False, 'error': 'Acceso no autorizado'}), 403

    if current_user.role in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH):
        return None

    # Jefe de obra: ámbito por obra / trabajador / vehículo de su círculo
    if context == 'obra':
        obra = Obra.query.get(entity_id)
        if not obra or obra.jefe_obra_id != current_user.id:
            return jsonify({'success': False, 'error': 'No tienes permiso sobre esta obra'}), 403
    elif context == 'worker':
        if not _jefe_puede_ver_worker(entity_id):
            return jsonify({'success': False, 'error': 'No tienes permiso sobre este trabajador'}), 403
    elif context == 'empresa':
        return jsonify({'success': False, 'error': 'Acceso no autorizado'}), 403
    # vehiculo / solicitud: el jefe puede consultar (planificación compartida)
    return None


@api_bp.route('/recursos_activos', methods=['GET'])
@login_required
@roles_required_api(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def recursos_activos():
    """Devuelve las obras y usuarios activos filtrados por el rol (Para selectores y modales)"""
    
    # 1. Filtro de seguridad para Obras
    if current_user.role == ROLE_ADMIN:
        obras = Obra.query.filter_by(is_deleted=False).order_by(Obra.nombre).all()
    elif current_user.role == ROLE_JEFE:
        obras = Obra.query.filter_by(is_deleted=False, jefe_obra_id=current_user.id).order_by(Obra.nombre).all()
    elif current_user.role in (ROLE_LABORAL, ROLE_RRHH):
        obras = Obra.query.filter_by(is_deleted=False).order_by(Obra.nombre).all()
    else:
        obras = []

    # 2. Usuarios: nunca la plantilla completa a quien no sea admin/laboral
    if current_user.role in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH):
        users = User.query.filter_by(is_deleted=False).order_by(User.name).all()
    elif current_user.role == ROLE_JEFE:
        obra_ids = [o.id for o in obras]
        user_ids = {current_user.id}
        if obra_ids:
            for row in Asignacion.query.filter(Asignacion.obra_id.in_(obra_ids)).with_entities(Asignacion.user_id).distinct():
                user_ids.add(row[0])
        users = (
            User.query.filter(User.id.in_(user_ids), User.is_deleted.is_(False))
            .order_by(User.name)
            .all()
            if user_ids else []
        )
    else:
        users = []
    
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

    denied = _autorizar_calendario(context, entity_id)
    if denied is not None:
        return denied

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
            VEHICLE_COLOR_AUSENCIA,
            VEHICLE_COLOR_CONFLICTO,
            VEHICLE_COLOR_CUMPLIDO,
            VEHICLE_COLOR_PLAN,
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

            plan_status = v_meta.get('plan_status') or 'plan'
            if plan_status == 'ausencia' or plan_status == 'muerto':
                color = VEHICLE_COLOR_AUSENCIA
                ev_type = 'vehiculo'
                tip = (
                    f'<b>Turquesa · Libre (ausencia)</b><br>'
                    f'Asignado en ausencia ({v_meta.get("ausencia_tipo") or "ausencia"}). '
                    f'El coche cuenta como libre.'
                )
            elif plan_status == 'cumplido' or plan_status == 'conductor_real':
                color = VEHICLE_COLOR_CUMPLIDO
                ev_type = 'vehiculo'
                tip = (
                    '<b>Verde · Conductor real</b><br>Usó el coche según Odoo sin estar planificado.'
                    if plan_status == 'conductor_real'
                    else '<b>Verde · Cumplido</b><br>Planificado y con kilómetros en Odoo.'
                )
            elif plan_status == 'conflicto' or plan_status == 'efectivo':
                color = VEHICLE_COLOR_CONFLICTO
                ev_type = 'vehiculo_odoo'
                if v_meta.get('mismatch') and v_meta.get('effective_other'):
                    tip = (
                        f'<b>Naranja · Conflicto</b><br>Estaba planificado pero lo usó '
                        f'{v_meta["effective_other"]}.'
                    )
                elif (v_meta.get('source') or '') == 'odoo':
                    tip = '<b>Naranja · Conflicto</b><br>Hay km en Odoo pero no había plan propio ese día.'
                else:
                    tip = '<b>Naranja · Conflicto</b><br>Planificado sin kilómetros reportados, o desajuste con Odoo.'
            else:
                color = VEHICLE_COLOR_PLAN
                ev_type = 'vehiculo'
                tip = '<b>Azul · Planificado</b><br>Asignado a este vehículo (aún sin km de Odoo).'
            raw_veh.append({
                'title': title,
                'start_date': d,
                'end_date': d,
                'color': color,
                'extendedProps': {
                    'type': ev_type,
                    'source': v_meta.get('source') or 'planificado',
                    'plan_status': plan_status,
                    'vehiculo_label': v_label,
                    'vehiculo_id': v_meta.get('vehiculo_id'),
                    'km': v_meta.get('km'),
                    'en_ausencia': bool(v_meta.get('en_ausencia')),
                    'mismatch': bool(v_meta.get('mismatch')),
                    'tooltipContent': tip,
                    'tooltipText': tip.replace('<br>', ' · ').replace('<b>', '').replace('</b>', ''),
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

            # Días con plan O con fichaje (paracaidista/conflicto sin asignación)
            fechas_asignadas = set(a.fecha for a in asignaciones)
            fechas_a_pintar = fechas_asignadas | set(fichajes_dict.keys())

            for fecha in fechas_a_pintar:
                lista_fichajes = fichajes_dict.get(fecha, [])
                
                if not lista_fichajes:
                    color_final = "#94a3b8"  # ⚪ Gris (Sin datos en BD)
                    tooltip_html = f"<div style='text-align:left;'><strong>{fecha.strftime('%d/%m/%Y')}:</strong><br>⚪ Sin Registro (Aún no ha fichado)</div>"
                else:
                    estados = [f.estado for f in lista_fichajes]

                    from app.services.fichaje_estado_service import (
                        FICHAJE_OK,
                        FICHAJE_NARANJA,
                        FICHAJE_ROJO,
                        color_fichaje_agregado,
                    )

                    def _label_estado_fichaje(estado):
                        return {
                            'Correcto': 'Correcto',
                            'Correcto_Automatico': 'Correcto (automático)',
                            'Resuelto_Asignado': 'Correcto (asignado por admin)',
                            'Resuelto_Movido': 'Correcto (movido por admin)',
                            'Resuelto_Dividido': 'Correcto (dividido por admin)',
                            'Resuelto_Ignorado': 'Ignorado por admin',
                            'Resuelto_Falta': 'Correcto (falta resuelta)',
                            'Resuelto_Ausencia': 'Ausencia confirmada',
                            'Exento_Ausencia': 'Exento (ausencia planificada)',
                            'Conflicto': 'Conflicto (pendiente)',
                            'Paracaidista': 'Paracaidista (pendiente)',
                            'Ausencia': 'Ausencia (pendiente)',
                            'Pendiente': 'Pendiente',
                            'Retraso': 'Retraso',
                        }.get(estado, (estado or '').replace('_', ' '))

                    color_final = color_fichaje_agregado(estados)

                    html_items = []
                    for f in lista_fichajes:
                        est = f.estado or ''
                        if est in FICHAJE_ROJO:
                            icono = "🔴"
                        elif est in FICHAJE_NARANJA:
                            icono = "🟠"
                        elif est in FICHAJE_OK or est.startswith('Resuelto'):
                            icono = "🟢"
                        else:
                            icono = "⚪"
                        nom_obra = _obra_label(f.obra_planificada, fallback=None)
                        if not nom_obra and getattr(f, 'obra_real', None):
                            nom_obra = _obra_label(f.obra_real, fallback=None)
                        if not nom_obra:
                            nom_obra = 'Sin obra en plan'
                        elif getattr(f, 'obra_real', None):
                            nom_real = _obra_label(f.obra_real, fallback=None)
                            if nom_real and nom_real != nom_obra:
                                nom_obra = f"{nom_obra} → {nom_real}"
                        html_items.append(
                            f"<li>{icono} <b>{nom_obra}</b>: {_label_estado_fichaje(est)}</li>"
                        )

                    tooltip_html = (
                        f"<div style='text-align:left;'>"
                        f"<strong style='border-bottom:1px solid #ccc; padding-bottom:3px; "
                        f"display:block; margin-bottom:5px;'>"
                        f"Fichajes ({fecha.strftime('%d/%m/%Y')}):</strong>"
                        f"<ul style='padding-left:15px; margin-bottom:0; font-size:0.85em; "
                        f"list-style:none;'>{''.join(html_items)}</ul></div>"
                    )

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
                title = f"Solicitud de Baja: {emp_name}" if accion == 'DESASIGNAR' else f"FALTA: {emp_name}"
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
                title = f"Solicitud de Baja: {emp_name} ({obra_txt})" if accion == 'DESASIGNAR' else f"FALTA: {emp_name} ({obra_txt})"
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
            VEHICLE_COLOR_AUSENCIA,
            VEHICLE_COLOR_CONFLICTO,
            VEHICLE_COLOR_CUMPLIDO,
            VEHICLE_COLOR_ODOO_EXT,
            VEHICLE_COLOR_PLAN,
        )
        from app.models import LEAVE_STATUS_APROBADA
        from app.utils.timezone_utils import today_local

        users_by_odoo, users_by_name = _build_user_indexes()
        raw_events = []
        hoy = today_local()

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

        def _has_odoo_usage(reg):
            return bool(
                reg and (
                    reg.valor is not None
                    or (reg.qty_km is not None)
                    or (reg.odoo_driver_name or '').strip()
                    or reg.odoo_driver_partner_id
                )
            )

        def _veh_tip(estado_label, motivo, extra=None):
            """Tooltip HTML + texto plano para el hover del evento."""
            lines = [f'<b>{estado_label}</b>', motivo]
            if extra:
                lines.append(extra)
            html = '<br>'.join(lines)
            plain = ' · '.join(
                p.replace('<b>', '').replace('</b>', '') for p in lines
            )
            return html, plain

        def _append_veh(title, fecha, color, props, tip_html, tip_plain):
            props = dict(props)
            props['tooltipContent'] = tip_html
            props['tooltipText'] = tip_plain
            raw_events.append({
                'title': title,
                'start_date': fecha,
                'end_date': fecha,
                'color': color,
                'extendedProps': props,
            })

        all_dates = sorted(set(planned_by_date.keys()) | set(odo_by_date.keys()))
        for fecha in all_dates:
            av = planned_by_date.get(fecha)
            reg = odo_by_date.get(fecha)
            has_odoo = _has_odoo_usage(reg)

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
            if has_odoo:
                odoo_worker, odoo_title, odoo_external = _resolve_odoo_driver(reg)

            leave = _leave_for(av.user_id, fecha) if av else None
            on_leave = bool(leave)
            km_bit = ""
            if reg and reg.valor is not None:
                km_bit = f" · {int(reg.valor)} km"
            elif reg and reg.qty_km is not None:
                km_bit = f" · {int(reg.qty_km)} km"

            # —— Solo plan ——
            if av and not has_odoo:
                obra = _obra_for_user_day(av.user_id, fecha)
                title = planned_name
                if on_leave:
                    tipo = (leave.tipo or 'Ausencia').strip() or 'Ausencia'
                    title = f"{planned_name} · {tipo}"
                    tip_h, tip_p = _veh_tip(
                        'Turquesa · Libre (ausencia)',
                        f'{planned_name} está de {tipo.lower()} y sigue asignado a este coche.',
                        'El coche cuenta como libre a efectos prácticos (misma regla que Coches libres).',
                    )
                    color = VEHICLE_COLOR_AUSENCIA
                    status = 'ausencia'
                elif fecha < hoy:
                    from flask import g as _g
                    _tenant = getattr(_g, 'current_tenant', None)
                    _mods = getattr(_tenant, 'modulos_activos', None) or {} if _tenant else {}
                    if _mods.get('odoo'):
                        if obra:
                            title = f"{planned_name} · {_obra_label(obra)}"
                        title = f"{title} · sin km"
                        tip_h, tip_p = _veh_tip(
                            'Naranja · Conflicto',
                            f'{planned_name} estaba planificado pero no hay kilómetros reportados en Odoo.',
                        )
                        color = VEHICLE_COLOR_CONFLICTO
                        status = 'conflicto'
                    else:
                        if obra:
                            title = f"{planned_name} · {_obra_label(obra)}"
                        tip_h, tip_p = _veh_tip(
                            'Azul · Planificado',
                            f'{planned_name} estaba asignado a este coche.',
                            'Sin integración ERP no hay contraste con km reales.',
                        )
                        color = VEHICLE_COLOR_PLAN
                        status = 'plan'
                else:
                    if obra:
                        title = f"{planned_name} · {_obra_label(obra)}"
                    tip_h, tip_p = _veh_tip(
                        'Azul · Planificado',
                        f'{planned_name} está asignado a este coche.',
                        'Aún no hay km de Odoo (día futuro o pendiente de sync).',
                    )
                    color = VEHICLE_COLOR_PLAN
                    status = 'plan'
                _append_veh(title, fecha, color, {
                    'type': 'vehiculo',
                    'source': 'planificado',
                    'plan_status': status,
                    'worker_id': av.user_id,
                    'vehiculo_id': entity_id,
                    'obra_id': obra.id if obra else None,
                    'en_ausencia': on_leave,
                    'ausencia_tipo': leave.tipo if leave else None,
                }, tip_h, tip_p)
                continue

            # —— Solo Odoo (km sin plan) → conflicto ——
            if has_odoo and not av:
                obra = _obra_for_user_day(odoo_worker.id, fecha) if odoo_worker else None
                title = f"{odoo_title} · sin plan{km_bit}"
                if obra:
                    title = f"{title} · {_obra_label(obra)}"
                tip_h, tip_p = _veh_tip(
                    'Naranja · Conflicto',
                    f'{odoo_title} reportó km en Odoo pero nadie estaba planificado en este coche.',
                )
                color = VEHICLE_COLOR_ODOO_EXT if odoo_external else VEHICLE_COLOR_CONFLICTO
                _append_veh(title, fecha, color, {
                    'type': 'vehiculo_odoo',
                    'source': 'odoo',
                    'plan_status': 'conflicto',
                    'worker_id': odoo_worker.id if odoo_worker else None,
                    'vehiculo_id': entity_id,
                    'obra_id': obra.id if obra else None,
                    'external': odoo_external,
                    'km': reg.valor if reg else None,
                }, tip_h, tip_p)
                continue

            # —— Plan + Odoo ——
            if av and has_odoo:
                same_person = bool(
                    odoo_worker and av.user_id and odoo_worker.id == av.user_id
                )
                obra_planned = _obra_for_user_day(av.user_id, fecha)

                if on_leave:
                    tipo = (leave.tipo or 'Ausencia').strip() or 'Ausencia'
                    tip_h, tip_p = _veh_tip(
                        'Turquesa · Libre (ausencia)',
                        f'{planned_name} está de {tipo.lower()} y sigue asignado.',
                        (f'Además Odoo reporta uso: {odoo_title}{km_bit}.' if odoo_title else
                         'El coche cuenta como libre a efectos prácticos.'),
                    )
                    _append_veh(
                        f"{planned_name} · {tipo}{km_bit}",
                        fecha,
                        VEHICLE_COLOR_AUSENCIA,
                        {
                            'type': 'vehiculo',
                            'source': 'ambos',
                            'plan_status': 'ausencia',
                            'worker_id': av.user_id,
                            'vehiculo_id': entity_id,
                            'obra_id': obra_planned.id if obra_planned else None,
                            'en_ausencia': True,
                            'ausencia_tipo': leave.tipo,
                            'km': reg.valor if reg else None,
                        },
                        tip_h,
                        tip_p,
                    )
                    if not same_person and odoo_title:
                        obra_odoo = (
                            _obra_for_user_day(odoo_worker.id, fecha) if odoo_worker else None
                        )
                        et = f"Real: {odoo_title}{km_bit}"
                        if obra_odoo:
                            et = f"{et} · {_obra_label(obra_odoo)}"
                        tip_h2, tip_p2 = _veh_tip(
                            'Verde · Conductor real',
                            f'{odoo_title} es quien usó el coche (Odoo){km_bit}.',
                            f'No estaba planificado. Planificado: {planned_name} (de {tipo.lower()}).',
                        )
                        _append_veh(et, fecha, (
                            VEHICLE_COLOR_ODOO_EXT if odoo_external else VEHICLE_COLOR_CUMPLIDO
                        ), {
                            'type': 'vehiculo_odoo',
                            'source': 'odoo',
                            'plan_status': 'conductor_real',
                            'worker_id': odoo_worker.id if odoo_worker else None,
                            'vehiculo_id': entity_id,
                            'km': reg.valor if reg else None,
                            'mismatch': True,
                        }, tip_h2, tip_p2)
                elif same_person:
                    title = planned_name
                    if obra_planned:
                        title = f"{planned_name} · {_obra_label(obra_planned)}"
                    title = f"{title}{km_bit}"
                    tip_h, tip_p = _veh_tip(
                        'Verde · Cumplido',
                        f'{planned_name} estaba planificado y reportó kilómetros en Odoo.',
                    )
                    _append_veh(title, fecha, VEHICLE_COLOR_CUMPLIDO, {
                        'type': 'vehiculo',
                        'source': 'ambos',
                        'plan_status': 'cumplido',
                        'worker_id': av.user_id,
                        'vehiculo_id': entity_id,
                        'obra_id': obra_planned.id if obra_planned else None,
                        'km': reg.valor if reg else None,
                    }, tip_h, tip_p)
                else:
                    # Conflicto: planificado A (naranja), condujo B (verde = conductor real)
                    dead_title = planned_name
                    if obra_planned:
                        dead_title = f"{planned_name} · {_obra_label(obra_planned)}"
                    dead_title = f"{dead_title} · no lo usó"
                    tip_h, tip_p = _veh_tip(
                        'Naranja · Conflicto',
                        f'{planned_name} estaba planificado pero no usó el coche.',
                        f'Conductor real según Odoo: {odoo_title or "desconocido"}{km_bit}.',
                    )
                    _append_veh(dead_title, fecha, VEHICLE_COLOR_CONFLICTO, {
                        'type': 'vehiculo',
                        'source': 'planificado',
                        'plan_status': 'conflicto',
                        'worker_id': av.user_id,
                        'vehiculo_id': entity_id,
                        'obra_id': obra_planned.id if obra_planned else None,
                        'mismatch': True,
                    }, tip_h, tip_p)

                    obra_odoo = (
                        _obra_for_user_day(odoo_worker.id, fecha) if odoo_worker else None
                    )
                    et = f"Real: {odoo_title or 'Conductor Odoo'}{km_bit}"
                    if obra_odoo:
                        et = f"{et} · {_obra_label(obra_odoo)}"
                    tip_h2, tip_p2 = _veh_tip(
                        'Verde · Conductor real',
                        f'{odoo_title or "Conductor Odoo"} usó el coche (Odoo){km_bit}.',
                        f'No estaba planificado. Planificado: {planned_name}.',
                    )
                    _append_veh(et, fecha, (
                        VEHICLE_COLOR_ODOO_EXT if odoo_external else VEHICLE_COLOR_CUMPLIDO
                    ), {
                        'type': 'vehiculo_odoo',
                        'source': 'odoo',
                        'plan_status': 'conductor_real',
                        'worker_id': odoo_worker.id if odoo_worker else None,
                        'vehiculo_id': entity_id,
                        'km': reg.valor if reg else None,
                        'mismatch': True,
                    }, tip_h2, tip_p2)

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
                title = f"{'Solicitud de Baja' if accion == 'DESASIGNAR' else 'SOL'}: {emp_name}"
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

    if current_user.role not in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH):
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

    if current_user.role not in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH):
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