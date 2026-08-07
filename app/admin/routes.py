# app/admin/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, g, session
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, func
from app.models import (
    User,
    Obra,
    Asignacion,
    ROLE_ADMIN,
    ROLE_JEFE,
    ROLE_OPERARIO,
    ROLE_LABORAL,
    ROLE_RRHH,
    Company,
    Solicitud,
    SolicitudVehiculo,
    Vehiculo,
)
from app import db
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta, date


from app.services.solicitud_service import update_solicitudes_for_assignment, get_solicitud_notas
from app.services.assignment_service import process_assignment_action
from app.services.core_assignment_service import CoreAssignmentService
from app.decorators import roles_required
from itsdangerous import URLSafeTimedSerializer
import os
from app.services.import_service import (
    allowed_import_file,
    save_import_upload,
    resolve_import_path,
    cleanup_import_file,
    preview_import,
    commit_import,
    ENTITY_LABELS,
)
from app.models import Rating


from app.services.dashboard_service import get_dashboard_data, parse_date
from app.services.entity_panel_service import (
    get_obra_panel_stats,
    get_worker_panel_stats,
    get_company_panel_stats,
    get_worker_vehicle_rows,
    get_obra_vehicle_rows,
    get_vehicle_panel_stats,
    get_vehicle_history_rows,
)
from app.services.permission_service import (
    is_laboral,
    laboral_log_categories,
    user_can,
)

from app.services.email_service import notificar_resolucion_solicitud, notificar_movimiento_admin_a_jo
# Definición del blueprint de admin
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}

IMPORT_WIZARD_CONFIG = {
    "obras": {
        "title": "Importar Obras",
        "subtitle": "Carga un Excel o CSV para crear varias obras a la vez.",
        "required_hint": "Código, Nombre, Cliente, Dirección, Fecha de inicio. Opcional: Fecha de fin.",
        "icon": "fa-hard-hat",
        "upload_endpoint": "admin.import_obras",
        "preview_endpoint": "admin.import_obras_preview",
        "confirm_endpoint": "admin.import_obras_confirm",
        "back_endpoint": "admin.obras_list",
        "back_label": "Volver al listado",
        "success_endpoint": "admin.obras_detailed",
        "success_label": "Ir a obras",
    },
    "users": {
        "title": "Importar Personal",
        "subtitle": "Carga un Excel o CSV para dar de alta usuarios.",
        "required_hint": "Email, Rol, Nombre, Apellidos, DNI, Empresa. Opcional: Contraseña, Activo.",
        "icon": "fa-users",
        "upload_endpoint": "admin.import_users",
        "preview_endpoint": "admin.import_users_preview",
        "confirm_endpoint": "admin.import_users_confirm",
        "back_endpoint": "admin.personal",
        "back_label": "Volver a personal",
        "success_endpoint": "admin.personal",
        "success_label": "Ir a personal",
    },
    "companies": {
        "title": "Importar Subcontratas",
        "subtitle": "Carga un Excel o CSV para dar de alta empresas subcontratadas.",
        "required_hint": "Nombre. Opcional: NIF, Código, Gremio, Email, Descripción, Interna.",
        "icon": "fa-building",
        "upload_endpoint": "admin.import_companies",
        "preview_endpoint": "admin.import_companies_preview",
        "confirm_endpoint": "admin.import_companies_confirm",
        "back_endpoint": "admin.companies",
        "back_label": "Volver a subcontratas",
        "success_endpoint": "admin.companies",
        "success_label": "Ir a subcontratas",
    },
}


@admin_bp.before_request
def _bloquear_operario_en_admin():
    """El operario no entra al panel de oficina (ni por PIN ni por portal web)."""
    if current_user.is_authenticated and current_user.role == ROLE_OPERARIO:
        flash('Tu perfil no tiene acceso al panel de administración.', 'warning')
        if getattr(current_user, 'web_access', False):
            return redirect(url_for('empleado.inicio'))
        return redirect(url_for('operarios.inicio'))


def _exige_email_verificado_para_usuarios():
    """Hasta verificar el correo del admin no se pueden crear/invitar usuarios."""
    if (
        current_user.is_authenticated
        and current_user.role == ROLE_ADMIN
        and hasattr(current_user, 'email_verified')
        and not current_user.email_verified
    ):
        flash(
            'Verifica tu correo electrónico antes de dar de alta o invitar usuarios. '
            'Puedes reenviar el enlace desde el aviso de la parte superior.',
            'warning',
        )
        return False
    return True


def allowed_file(filename):
    return allowed_import_file(filename)


def _import_session_key(entity_type):
    return f"import_{entity_type}"


def _clear_import_session(entity_type):
    data = session.pop(_import_session_key(entity_type), None)
    if data:
        cleanup_import_file(data.get("token", ""), data.get("ext", "xlsx"))


def _store_import_upload(entity_type, file_storage):
    token, ext = save_import_upload(file_storage)
    session[_import_session_key(entity_type)] = {
        "token": token,
        "ext": ext,
        "original_name": file_storage.filename,
        "column_map": None,
    }
    session.modified = True
    return token, ext


def _load_import_path(entity_type):
    data = session.get(_import_session_key(entity_type))
    if not data or not data.get("token"):
        return None, None
    path = resolve_import_path(data["token"], data.get("ext", "xlsx"))
    return path, data


def _column_map_from_form(_entity_type=None):
    """Lee map[campo]=columna desde el formulario de remapeo."""
    prefix = "map_"
    column_map = {}
    for key, value in request.form.items():
        if key.startswith(prefix):
            field_key = key[len(prefix):]
            column_map[field_key] = value if value and value != "__none__" else None
    return column_map or None


def _render_import_upload(entity_type):
    cfg = IMPORT_WIZARD_CONFIG[entity_type]
    # Nuevo ciclo: no reutilizar un fichero de un intento anterior.
    _clear_import_session(entity_type)
    return render_template(
        "admin_import_wizard.html",
        entity_type=entity_type,
        entity_label=ENTITY_LABELS.get(entity_type, entity_type),
        cfg=cfg,
        step=1,
    )


def _render_import_preview(entity_type, preview, column_map=None):
    cfg = IMPORT_WIZARD_CONFIG[entity_type]
    data = session.get(_import_session_key(entity_type)) or {}
    return render_template(
        "admin_import_wizard.html",
        entity_type=entity_type,
        entity_label=ENTITY_LABELS.get(entity_type, entity_type),
        cfg=cfg,
        preview=preview,
        column_map=column_map or preview.get("column_map") or {},
        columns=preview.get("columns") or [],
        fields=preview.get("fields") or [],
        original_name=data.get("original_name"),
        step=2,
    )


def _handle_import_upload_post(entity_type):
    file = request.files.get("file")
    if not file or not allowed_file(file.filename):
        flash("Sube un archivo Excel (.xlsx) o CSV (.csv) válido.", "danger")
        return redirect(url_for(IMPORT_WIZARD_CONFIG[entity_type]["upload_endpoint"]))

    _clear_import_session(entity_type)
    try:
        _store_import_upload(entity_type, file)
    except Exception as exc:
        flash(f"No se pudo guardar el archivo: {exc}", "danger")
        return redirect(url_for(IMPORT_WIZARD_CONFIG[entity_type]["upload_endpoint"]))

    return redirect(url_for(IMPORT_WIZARD_CONFIG[entity_type]["preview_endpoint"]))


def _handle_import_preview(entity_type):
    cfg = IMPORT_WIZARD_CONFIG[entity_type]
    try:
        path, data = _load_import_path(entity_type)
    except (ValueError, FileNotFoundError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for(cfg["upload_endpoint"]))

    if not path:
        flash("Primero sube un archivo para previsualizar.", "warning")
        return redirect(url_for(cfg["upload_endpoint"]))

    column_map = None
    if request.method == "POST":
        column_map = _column_map_from_form(entity_type)
        data["column_map"] = column_map
        session[_import_session_key(entity_type)] = data
        session.modified = True
    else:
        column_map = data.get("column_map")

    preview = preview_import(path, entity_type, column_map)
    if not preview.get("success"):
        flash(preview.get("message") or "Error al leer el archivo", "danger")
        _clear_import_session(entity_type)
        return redirect(url_for(cfg["upload_endpoint"]))

    data["column_map"] = preview.get("column_map")
    session[_import_session_key(entity_type)] = data
    session.modified = True

    return _render_import_preview(entity_type, preview)


def _handle_import_confirm(entity_type):
    cfg = IMPORT_WIZARD_CONFIG[entity_type]
    try:
        path, data = _load_import_path(entity_type)
    except (ValueError, FileNotFoundError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for(cfg["upload_endpoint"]))

    if not path:
        flash("No hay archivo pendiente de importar.", "warning")
        return redirect(url_for(cfg["upload_endpoint"]))

    column_map = _column_map_from_form(entity_type) or data.get("column_map")
    result = commit_import(path, entity_type, column_map)
    _clear_import_session(entity_type)

    if not result.get("success"):
        flash(result.get("message") or "Error en la importación", "danger")
        return redirect(url_for(cfg["upload_endpoint"]))

    return render_template(
        "admin_import_wizard.html",
        entity_type=entity_type,
        entity_label=ENTITY_LABELS.get(entity_type, entity_type),
        cfg=cfg,
        result=result,
        summary=result.get("summary") or {},
        rows=result.get("rows") or [],
        imported=result.get("imported") or [],
        created_companies=result.get("created_companies") or [],
        step=3,
    )


@admin_bp.route("/import_obras", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_obras():
    if request.method == "POST":
        return _handle_import_upload_post("obras")
    return _render_import_upload("obras")


@admin_bp.route("/import_obras/preview", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_obras_preview():
    return _handle_import_preview("obras")


@admin_bp.route("/import_obras/confirm", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_obras_confirm():
    return _handle_import_confirm("obras")

@admin_bp.route('/solicitudes')
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def solicitudes_list():
    seccion = request.args.get('seccion', 'personal')
    if seccion not in ('personal', 'vehiculos'):
        seccion = 'personal'

    estado = request.args.get('estado', 'todas')
    tipo = request.args.get('tipo', 'todas')
    obra_id = request.args.get('obra_id')
    date_filter_str = request.args.get('date_filter')
    estados_posibles = ['todas', 'PENDIENTE', 'EN_PROCESO', 'CUMPLIDA', 'CERRADA_PARCIAL', 'DENEGADA']
    tipos_posibles = ['todas', 'generica', 'concreta']
    target_date = parse_date(date_filter_str) if date_filter_str else None
    obra_seleccionada = Obra.query.get(int(obra_id)) if obra_id and obra_id.isdigit() else None

    # --- SECCIÓN VEHÍCULOS ---
    if seccion == 'vehiculos':
        v_query = SolicitudVehiculo.query
        if current_user.role == ROLE_JEFE:
            v_query = v_query.filter(SolicitudVehiculo.requested_by_id == current_user.id)

        if estado != 'todas':
            v_query = v_query.filter(SolicitudVehiculo.estado == estado)

        if target_date:
            v_query = v_query.filter(
                SolicitudVehiculo.fecha_inicio <= target_date,
                SolicitudVehiculo.fecha_fin >= target_date,
            )

        solicitudes_vehiculo = v_query.order_by(SolicitudVehiculo.created_at.desc()).all()
        return render_template(
            'admin_solicitudes_list.html',
            seccion=seccion,
            solicitudes=[],
            solicitudes_vehiculo=solicitudes_vehiculo,
            stats={},
            estado_filtro=estado,
            tipo_filtro=tipo,
            date_filtro=target_date,
            obra_filtro=obra_seleccionada,
            estados_posibles=estados_posibles,
            tipos_posibles=tipos_posibles,
            can_resolve_vehiculo=(current_user.role == ROLE_ADMIN),
        )

    # --- SECCIÓN PERSONAL (default) ---
    query = Solicitud.query
    if current_user.role == ROLE_JEFE:
        # Un Jefe solo debe ver:
        # 1. Las solicitudes que él mismo creó (requested_by_id)
        # 2. O las solicitudes de Obras donde él es el Jefe (Obra.jefe_obra_id)
        query = query.join(Obra).filter(
            or_(
                Solicitud.requested_by_id == current_user.id,
                Obra.jefe_obra_id == current_user.id
            )
        )

    if obra_id:
        try:
            # 🛠️ CORRECCIÓN: Usar filtro explícito para evitar problemas similares
            query = query.filter(Solicitud.obra_id == int(obra_id))
        except ValueError: pass

    if estado != 'todas':
        # 🛠️ CORRECCIÓN: Forzar que el filtro se aplique a Solicitud, no a Obra
        query = query.filter(Solicitud.estado == estado)

    if tipo != 'todas':
        query = query.filter(func.lower(Solicitud.tipo) == tipo.lower())

    if target_date:
        query = query.filter(
            Solicitud.fecha_inicio <= target_date,
            Solicitud.fecha_fin >= target_date
        )
            
    solicitudes = query.order_by(Solicitud.created_at.desc()).all()

    # --- CÁLCULO DE ESTADÍSTICAS (PORCENTAJE REAL DE JORNADAS) ---
    stats = {}

    
    for s in solicitudes:
        num_dias = (s.fecha_fin - s.fecha_inicio).days + 1
        if num_dias < 1: num_dias = 1
        
        if s.tipo == 'GENERICA':
            total_jornadas_necesarias = s.cantidad_solicitada * num_dias
            
            # --- MISMA LÓGICA DE AISLAMIENTO QUE EN EL MOTOR ---
            cond_explicita = (Asignacion.solicitud_id == s.id)
            cond_libre = [Asignacion.solicitud_id == None]
            
            if s.created_at:
                cond_libre.append(Asignacion.created_at >= s.created_at)
            if s.perfil_categoria:
                cond_libre.append(User.categoria_profesional.ilike(f"%{s.perfil_categoria}%"))
            if s.perfil_empresa_id:
                cond_libre.append(User.company_id == s.perfil_empresa_id)

            q_asig = Asignacion.query.filter(
                Asignacion.obra_id == s.obra_id,
                Asignacion.fecha >= s.fecha_inicio,
                Asignacion.fecha <= s.fecha_fin
            ).join(User).filter(User.is_deleted == False, or_(cond_explicita, and_(*cond_libre)))
            
            total_jornadas_cubiertas = q_asig.count()
            
            if total_jornadas_necesarias > 0:
                pct = int((total_jornadas_cubiertas / total_jornadas_necesarias) * 100)
            else:
                pct = 0
            
            stats[s.id] = {
                'pct': min(pct, 100),
                'cubiertas_total': s.cantidad_cubierta, 
                'plazas_total': s.cantidad_solicitada
            }
            
        else:
            # CONCRETA: Calculamos % en base a si el empleado específico está asignado esos días
            if s.empleado_id:
                dias_asignados = Asignacion.query.filter(
                    Asignacion.obra_id == s.obra_id,
                    Asignacion.user_id == s.empleado_id,
                    Asignacion.fecha >= s.fecha_inicio,
                    Asignacion.fecha <= s.fecha_fin
                ).count()
                
                pct = int((dias_asignados / num_dias) * 100)
            else:
                pct = 0
                
            stats[s.id] = {'pct': min(pct, 100)}

    return render_template(
        'admin_solicitudes_list.html',
        seccion=seccion,
        solicitudes=solicitudes,
        solicitudes_vehiculo=[],
        stats=stats, 
        estado_filtro=estado,
        tipo_filtro=tipo,
        date_filtro=target_date,
        obra_filtro=obra_seleccionada,
        estados_posibles=estados_posibles,
        tipos_posibles=tipos_posibles,
        can_resolve_vehiculo=(current_user.role == ROLE_ADMIN),
    )


@admin_bp.route('/solicitudes-vehiculo/<int:solicitud_id>/resolver', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def resolver_solicitud_vehiculo(solicitud_id):
    from app.services.vehicle_solicitud_service import VehicleSolicitudService

    solicitud = SolicitudVehiculo.query.get_or_404(solicitud_id)
    decision = request.form.get('decision') or (request.get_json() or {}).get('decision')
    if not decision:
        flash('Falta la decisión (aceptar/denegar).', 'danger')
        return redirect(url_for('admin.solicitudes_list', seccion='vehiculos'))

    try:
        mensaje = VehicleSolicitudService.resolve(solicitud, decision, current_user)
        flash(mensaje, 'success')
    except Exception as e:
        db.session.rollback()
        flash(str(e), 'danger')

    return redirect(url_for('admin.solicitudes_list', seccion='vehiculos', estado=request.args.get('estado', 'todas')))

    
@admin_bp.route("/worker_panel/<int:user_id>", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def worker_panel(user_id):
    """
    Ficha del trabajador con calendario de sus asignaciones Y SOLICITUDES.
    (El calendario carga por API V6)
    """
    worker = User.query.get_or_404(user_id)
    panel_stats = get_worker_panel_stats(worker)
    return render_template(
        "admin_worker_panel.html",
        worker=worker,
        stats=panel_stats["stats"],
        chart_14d=panel_stats["chart_14d"],
        chart_14d_max=panel_stats["chart_14d_max"],
        vehicle_rows=get_worker_vehicle_rows(worker),
        can_edit_calendar=user_can(current_user, 'worker_panel', 'w'),
    )


@admin_bp.route("/api/check_obra_status_impact", methods=["POST"])
@login_required
def check_obra_status_impact():
    """
    Calcula cuántas asignaciones futuras se borrarían al pausar una obra.
    """
    data = request.get_json()
    obra_id = data.get("obra_id")
    
    if not obra_id:
        return jsonify({"error": "Falta obra_id"}), 400

    today = date.today()
    
    # Contamos asignaciones desde HOY en adelante (inclusive)
    # porque al ponerla en pendiente, se para YA.
    future_assignments = Asignacion.query.filter(
        Asignacion.obra_id == obra_id,
        Asignacion.fecha >= today
    ).all()

    total_days = len(future_assignments)
    # Contamos trabajadores únicos afectados
    unique_workers = len(set(a.user_id for a in future_assignments))

    return jsonify({
        "success": True,
        "total_days": total_days,
        "unique_workers": unique_workers
    })
    

@admin_bp.route("/company_panel/<int:company_id>", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def company_panel(company_id):
    """
    Ficha de empresa con cronograma de obras donde participa su personal.
    (Los datos del calendario ahora se cargan dinámicamente vía API).
    """
    company = Company.query.get_or_404(company_id)
    panel_stats = get_company_panel_stats(company)

    return render_template(
        "admin_company_panel.html",
        company=company,
        stats=panel_stats["stats"],
        chart_14d=panel_stats["chart_14d"],
        chart_14d_max=panel_stats["chart_14d_max"],
        avg_rating=panel_stats["avg_rating"],
        ratings_count=panel_stats["ratings_count"],
    )

   
    
@admin_bp.route('/solicitudes/<int:solicitud_id>')
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def solicitud_detail(solicitud_id):
    solicitud = Solicitud.query.get_or_404(solicitud_id)
    es_admin = (current_user.role == ROLE_ADMIN)
    fecha_inicio = solicitud.fecha_inicio
    fecha_fin = solicitud.fecha_fin
    cal_initial_date = fecha_inicio or fecha_fin or date.today()

    # 1. RESUMEN PERSONAL ASIGNADO (Se mantiene igual)
    asignaciones_resumen = []
    if fecha_inicio and fecha_fin:
        asignaciones = Asignacion.query.filter(
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.fecha >= fecha_inicio,
            Asignacion.fecha <= fecha_fin
        ).all()

        resumen = {}
        for a in asignaciones:
            if a.user_id not in resumen:
                worker = User.query.get(a.user_id)
                if not worker: continue
                resumen[a.user_id] = {
                    "worker": worker,
                    "empresa": worker.company_rel,
                    "num_dias": 0,
                    "primer_dia": a.fecha,
                    "ultimo_dia": a.fecha
                }
            r = resumen[a.user_id]
            r["num_dias"] += 1
            if a.fecha < r["primer_dia"]: r["primer_dia"] = a.fecha
            if a.fecha > r["ultimo_dia"]: r["ultimo_dia"] = a.fecha
        asignaciones_resumen = list(resumen.values())

    # 2. LÓGICA CANDIDATOS (NUEVA LÓGICA TRINARIA)
    profile_candidates = []
    candidate_states = {} # Diccionario para guardar el estado de cada trabajador
    
    ignore_profile = request.args.get('ignore_profile') 

    if fecha_inicio and fecha_fin:
        query = User.query.filter(
            User.role == ROLE_OPERARIO, 
            User.active.is_(True), 
            User.is_deleted.is_(False)
        )
        
        if not ignore_profile:
            # Eliminado el filtro estricto de categoría para sugerir a todos los trabajadores
            # if solicitud.perfil_categoria:
            #     query = query.filter(User.categoria_profesional.ilike(f"%{solicitud.perfil_categoria}%"))
            if solicitud.perfil_empresa_id:
                query = query.filter(User.company_id == solicitud.perfil_empresa_id)
            
        profile_candidates = query.order_by(User.name).all()
        candidate_ids = {u.id for u in profile_candidates}

        # Calcular duración total de la solicitud (en días)
        total_days_req = (fecha_fin - fecha_inicio).days + 1

        # Asignaciones en el periodo (cualquier obra) — incluye gente visible en calendario
        all_assignments = Asignacion.query.filter(
            Asignacion.fecha >= fecha_inicio,
            Asignacion.fecha <= fecha_fin,
        ).all()

        # Operarios con asignación en el rango que el filtro de empresa excluyó
        extra_user_ids = {a.user_id for a in all_assignments} - candidate_ids
        if extra_user_ids:
            extras = User.query.filter(
                User.id.in_(extra_user_ids),
                User.role == ROLE_OPERARIO,
                User.active.is_(True),
                User.is_deleted.is_(False),
            ).order_by(User.name).all()
            profile_candidates.extend(extras)
            profile_candidates.sort(key=lambda u: (u.name or '', u.lastname or ''))
            candidate_ids.update(u.id for u in extras)

        if solicitud.empleado_id and solicitud.empleado and solicitud.empleado.id not in candidate_ids:
            profile_candidates.append(solicitud.empleado)
            profile_candidates.sort(key=lambda u: (u.name or '', u.lastname or ''))
            candidate_ids.add(solicitud.empleado.id)
        
        # Agrupar asignaciones por usuario para contar días ocupados
        busy_counts = {}
        for a in all_assignments:
            if a.user_id not in candidate_ids:
                continue
            if a.user_id not in busy_counts:
                busy_counts[a.user_id] = set()
            busy_counts[a.user_id].add(a.fecha)
            
        # Determinar estado: LIBRE, PARCIAL, OCUPADO
        for u in profile_candidates:
            days_busy = len(busy_counts.get(u.id, set()))
            
            if days_busy == 0:
                state = 'FREE'
            elif days_busy >= total_days_req:
                state = 'BUSY' # Ocupado todo el periodo
            else:
                state = 'PARTIAL' # Tiene algunos días libres
                
            candidate_states[u.id] = {
                'status': state,
                'days_busy': days_busy
            }

    # 3. Cobertura
    cobertura_texto = f"{solicitud.cantidad_cubierta}/{solicitud.cantidad_solicitada}" if solicitud.tipo == 'GENERICA' else ""

    return render_template(
        'admin_solicitud_detail.html',
        solicitud=solicitud,
        solicitud_notas=get_solicitud_notas(solicitud),
        cobertura_texto=cobertura_texto,
        es_admin=es_admin,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        cal_initial_date=cal_initial_date,
        asignaciones_resumen=asignaciones_resumen, 
        profile_candidates=profile_candidates, 
        candidate_states=candidate_states, # <--- Pasamos el nuevo diccionario de estados
        total_days_req=(fecha_fin - fecha_inicio).days + 1 if fecha_inicio and fecha_fin else 1
    )

@admin_bp.route("/api/update_obra_staff", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_update_obra_staff():
    data = request.get_json()
    obra_id = data.get("obra_id")
    user_id = data.get("user_id") # Puede ser vacío si desasignamos
    role_type = data.get("role_type") # 'jefe' o 'encargado'
    
    obra = Obra.query.get(obra_id)
    if not obra:
        return jsonify({"success": False, "error": "Obra no encontrada"}), 404
        
    try:
        new_id = int(user_id) if user_id else None
        
        if role_type == 'jefe':
            obra.jefe_obra_id = new_id
            # Obtenemos nombre para devolver al frontend
            user_obj = obra.jefe_obra
        elif role_type == 'encargado':
            obra.encargado_id = new_id
            user_obj = obra.encargado
        else:
            return jsonify({"success": False, "error": "Tipo de rol inválido"}), 400
        
        db.session.commit()
        
        new_name = f"{user_obj.name} {user_obj.lastname}" if user_obj else "Sin asignar"
        return jsonify({"success": True, "new_name": new_name})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500



@admin_bp.route("/schedule_status/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def schedule_status(user_id):
    data = request.get_json()
    action = data.get("action")  # "activate" o "deactivate"

    scheduled_date = parse_date(data.get("date"))
    if not scheduled_date:
        return jsonify({"success": False, "error": "Fecha inválida"}), 400

    user = User.query.get(user_id)
    if not user or user.role != ROLE_OPERARIO:
        return jsonify({"success": False, "error": "Usuario no encontrado o rol inválido"}), 404

    if action == "deactivate":
        user.scheduled_deactivation_date = scheduled_date
        user.scheduled_activation_date = None
    elif action == "activate":
        user.scheduled_activation_date = scheduled_date
        user.scheduled_deactivation_date = None
    else:
        return jsonify({"success": False, "error": "Acción inválida"}), 400

    db.session.commit()
    return jsonify({"success": True, "message": "Fecha programada correctamente."})


@admin_bp.route("/buscar_obras", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN)
def buscar_obras():
    start_date_str = request.args.get("start_date", "")
    end_date_str = request.args.get("end_date", "")
    jefe_id = request.args.get("jefe_id", "")
    operario_id = request.args.get("operario_id", "")

    start_date = parse_date(start_date_str, default=None)
    end_date = parse_date(end_date_str, default=None)
    query = Obra.query

    if start_date and end_date:
        query = query.filter(
            or_(
                Obra.fecha_inicio.between(start_date, end_date),
                Obra.fecha_fin.between(start_date, end_date),
            )
        )
    else:
        flash("Formato de fechas inválido", "danger")

    if jefe_id:
        try:
            jefe_id_int = int(jefe_id)
            query = query.filter(Obra.jefe_obra_id == jefe_id_int)
        except ValueError:
            pass

    if operario_id:
        try:
            operario_id_int = int(operario_id)
            query = query.join(Asignacion).filter(Asignacion.user_id == operario_id_int).distinct()
        except ValueError:
            pass

    obras = query.order_by(Obra.fecha_inicio.desc()).all()

    jefes = User.query.filter(User.role.in_([ROLE_JEFE, ROLE_ADMIN])).all()
    operarios = User.query.filter_by(role=ROLE_OPERARIO).all()

    return render_template(
        "admin_busqueda_obras.html",
        obras=obras,
        start_date=start_date_str,
        end_date=end_date_str,
        jefe_id=jefe_id,
        operario_id=operario_id,
        jefes=jefes,
        operarios=operarios,
    )


# --- AÑADIR EN app/admin/routes.py ---
# --- EN app/admin/routes.py ---
@admin_bp.route("/obra_panel/<int:obra_id>", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def obra_panel(obra_id):
    """
    Panel específico de una obra (Ficha de Obra).
    (Los datos del calendario ahora se cargan dinámicamente vía API universal).
    """
    obra = Obra.query.get_or_404(obra_id)
    
    # Seguridad: si es jefe, solo ve sus obras
    if current_user.role == ROLE_JEFE and obra.jefe_obra_id != current_user.id:
        flash("No tienes permisos para ver esta obra.", "danger")
        return redirect(url_for("jefe.panel"))

    jefes = User.query.filter(User.role.in_([ROLE_JEFE, ROLE_ADMIN])).all()
    panel_stats = get_obra_panel_stats(obra)

    return render_template(
        "admin_obra_panel.html",
        obra=obra,
        jefes=jefes,
        today=date.today(),
        stats=panel_stats["stats"],
        chart_14d=panel_stats["chart_14d"],
        chart_14d_max=panel_stats["chart_14d_max"],
        operarios_hoy=panel_stats["operarios_hoy"],
        ocupacion_pct=panel_stats["ocupacion_pct"],
        vehicle_rows=get_obra_vehicle_rows(obra),
        can_edit_calendar=user_can(current_user, 'obra_panel', 'w'),
    )
    
@admin_bp.route("/companies", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN)
def companies():
    """Solo lista las empresas."""
    filter_nombre = request.args.get("nombre", "")
    query = Company.query
    if filter_nombre:
        query = query.filter(Company.nombre.ilike(f"%{filter_nombre}%"))
    companies_list = query.all()
    return render_template("admin_companies.html", companies=companies_list, filter_nombre=filter_nombre)


@admin_bp.route("/vehiculos", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def vehiculos():
    """Listado de flota (alta manual y/o sync Odoo)."""
    show_inactive = request.args.get('show_inactive') in ('1', 'true', 'on', 'yes')
    query = Vehiculo.query
    if not show_inactive:
        query = query.filter(Vehiculo.active.is_(True))
    vehicles = (
        query
        .order_by(Vehiculo.active.desc(), Vehiculo.matricula.asc().nullslast(), Vehiculo.nombre.asc())
        .all()
    )
    return render_template(
        "admin_vehiculos.html",
        vehicles=vehicles,
        show_inactive=show_inactive,
    )


@admin_bp.route("/vehiculos/crear", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def vehiculos_crear():
    """Alta manual de vehículo (sin ERP)."""
    nombre = (request.form.get('nombre') or '').strip()
    matricula = (request.form.get('matricula') or '').strip().upper() or None
    marca = (request.form.get('marca') or '').strip() or None
    modelo = (request.form.get('modelo') or '').strip() or None

    if not nombre:
        flash('Indica un nombre para el vehículo.', 'danger')
        return redirect(url_for('admin.vehiculos'))

    if matricula:
        dup = Vehiculo.query.filter(
            db.func.upper(Vehiculo.matricula) == matricula
        ).first()
        if dup:
            flash(f'Ya existe un vehículo con matrícula {matricula}.', 'danger')
            return redirect(url_for('admin.vehiculos'))

    v = Vehiculo(
        nombre=nombre[:120],
        matricula=matricula[:40] if matricula else None,
        marca=marca[:80] if marca else None,
        modelo=modelo[:80] if modelo else None,
        active=True,
    )
    db.session.add(v)
    db.session.commit()
    flash(f'Vehículo «{v.label()}» dado de alta.', 'success')
    return redirect(url_for('admin.vehicle_panel', vehiculo_id=v.id))


@admin_bp.route("/vehiculos/<int:vehiculo_id>/editar", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def vehiculos_editar(vehiculo_id):
    v = Vehiculo.query.get_or_404(vehiculo_id)
    nombre = (request.form.get('nombre') or '').strip()
    matricula = (request.form.get('matricula') or '').strip().upper() or None
    marca = (request.form.get('marca') or '').strip() or None
    modelo = (request.form.get('modelo') or '').strip() or None

    if not nombre:
        flash('El nombre no puede quedar vacío.', 'danger')
        return redirect(url_for('admin.vehicle_panel', vehiculo_id=v.id))

    if matricula:
        dup = Vehiculo.query.filter(
            db.func.upper(Vehiculo.matricula) == matricula,
            Vehiculo.id != v.id,
        ).first()
        if dup:
            flash(f'Ya existe otro vehículo con matrícula {matricula}.', 'danger')
            return redirect(url_for('admin.vehicle_panel', vehiculo_id=v.id))

    v.nombre = nombre[:120]
    v.matricula = matricula[:40] if matricula else None
    v.marca = marca[:80] if marca else None
    v.modelo = modelo[:80] if modelo else None
    db.session.commit()
    flash('Vehículo actualizado.', 'success')
    return redirect(url_for('admin.vehicle_panel', vehiculo_id=v.id))


@admin_bp.route("/vehiculos/<int:vehiculo_id>/toggle", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def vehiculos_toggle(vehiculo_id):
    v = Vehiculo.query.get_or_404(vehiculo_id)
    v.active = not bool(v.active)
    db.session.commit()
    flash(
        f'Vehículo «{v.label()}» {"activado" if v.active else "desactivado"}.',
        'success',
    )
    return redirect(request.referrer or url_for('admin.vehiculos'))


@admin_bp.route("/vehiculos/libres", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def vehiculos_libres():
    """Coches libres a futuro: sin plan o conductor de ausencia."""
    from app.services.vehicle_availability_service import (
        DEFAULT_HORIZON_MONTHS,
        HORIZON_MONTHS_ALLOWED,
        MOTIVO_AUSENCIA,
        MOTIVO_MIXTO,
        MOTIVO_SIN_PLAN,
        free_vehicle_summary,
        horizon_end,
        list_free_vehicle_stretches,
        parse_horizon_months,
    )
    from app.utils.timezone_utils import today_local

    months = parse_horizon_months(request.args.get('meses'), DEFAULT_HORIZON_MONTHS)
    motivo_filtro = (request.args.get('motivo') or '').strip()
    if motivo_filtro not in (MOTIVO_SIN_PLAN, MOTIVO_AUSENCIA, MOTIVO_MIXTO, ''):
        motivo_filtro = ''
    q = (request.args.get('q') or '').strip()

    today = today_local()
    hasta = horizon_end(today, months)
    stretches = list_free_vehicle_stretches(fecha_desde=today, fecha_hasta=hasta)
    if motivo_filtro:
        stretches = [s for s in stretches if s['motivo'] == motivo_filtro]
    if q:
        q_low = q.lower()
        stretches = [
            s for s in stretches
            if q_low in (s.get('vehiculo_label') or '').lower()
        ]
    summary = free_vehicle_summary(stretches)

    return render_template(
        "admin_vehiculos_libres.html",
        stretches=stretches,
        summary=summary,
        months=months,
        months_allowed=HORIZON_MONTHS_ALLOWED,
        motivo_filtro=motivo_filtro,
        q=q,
        fecha_desde=today,
        fecha_hasta=hasta,
    )


@admin_bp.route("/vehicle_panel/<int:vehiculo_id>", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def vehicle_panel(vehiculo_id):
    """Ficha de vehículo con historial (plegable) y calendario de asignaciones."""
    vehiculo = Vehiculo.query.get_or_404(vehiculo_id)
    panel_stats = get_vehicle_panel_stats(vehiculo)
    try:
        history_days = int(request.args.get('history_days') or 30)
    except (TypeError, ValueError):
        history_days = 30
    history_days = max(1, min(730, history_days))
    history_open = request.args.get('history_open') in ('1', 'true', 'yes')

    return render_template(
        "admin_vehicle_panel.html",
        vehiculo=vehiculo,
        stats=panel_stats["stats"],
        chart_14d=panel_stats["chart_14d"],
        chart_14d_max=panel_stats["chart_14d_max"],
        history_days=history_days,
        history_open=history_open,
        history_rows=get_vehicle_history_rows(vehiculo, days=history_days) if history_open else [],
        can_edit_calendar=(
            current_user.role in (ROLE_ADMIN, ROLE_JEFE) and not is_laboral(current_user)
        ),
    )


@admin_bp.route("/vehicle_panel/<int:vehiculo_id>/historial", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def vehicle_panel_historial(vehiculo_id):
    """Fragmento HTML del historial de uso (rango configurable, máx. 730 días)."""
    vehiculo = Vehiculo.query.get_or_404(vehiculo_id)
    try:
        days = int(request.args.get('days') or 30)
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(730, days))
    rows = get_vehicle_history_rows(vehiculo, days=days)
    return render_template(
        "components/_vehicle_history_table.html",
        history_rows=rows,
        history_days=days,
    )


@admin_bp.route("/create_company", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def create_company():
    """Gestiona el formulario de creación."""
    if request.method == "POST":
        code = request.form.get("code")

        # --- FIX: Generar código automático si viene vacío o "None" ---
        if not code or str(code).strip() == "" or str(code).strip().lower() == "none":
            import uuid
            code = f"AUTO-{uuid.uuid4().hex[:6].upper()}"
        # --------------------------------------------------------------

        nombre = request.form.get("nombre")
        nif = request.form.get("nif")
        descripcion = request.form.get("descripcion")
        gremio = request.form.get("gremio")
        email = request.form.get("email")
        color = (request.form.get("color") or "").strip()
        if not color or color.lower() in ("#ffffff", "#fff", "#cccccc", "#ccc"):
            from app.models import generate_random_color
            color = generate_random_color()

        # LEER CHECKBOX: Si está marcado viene 'on', si no, None.
        is_internal = True if request.form.get("is_internal") == "on" else False

        existing = Company.query.filter_by(code=code).first()
        if existing:
            flash("El código de empresa ya existe.", "danger")
            return redirect(url_for("admin.create_company"))
        
        new_company = Company(
            code=code,
            nombre=nombre,
            nif=nif,
            descripcion=descripcion,
            gremio=gremio,
            email=email,
            color=color,
            is_internal=is_internal
        )
        
        # --- FIX: Envolvemos en try/except para evitar bloqueos del servidor ---
        try:
            db.session.add(new_company)
            db.session.commit()
            flash("Empresa creada exitosamente.", "success")
            return redirect(url_for("admin.companies"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error en la base de datos: {str(e)}", "danger")
            return redirect(url_for("admin.create_company"))

    from app.models import generate_random_color
    return render_template(
        "admin_create_company.html",
        color_sugerido=generate_random_color(),
    )


@admin_bp.route("/company/<int:company_id>/edit", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN, redirect_to="admin.companies")
def edit_company(company_id):
    company = Company.query.get_or_404(company_id)
    if request.method == "POST":
        new_code = request.form.get("code")
        
        # --- FIX: Generar código automático si lo dejan vacío ---
        if not new_code or str(new_code).strip() == "" or str(new_code).strip().lower() == "none":
            # Si ya tenía un código válido, se lo mantenemos por si lo han borrado sin querer
            if company.code and str(company.code).strip().lower() != "none":
                new_code = company.code
            else:
                import uuid
                new_code = f"AUTO-{uuid.uuid4().hex[:6].upper()}"
                
        # Validar que si han metido un código a mano, no coincida con el de OTRA empresa
        if new_code != company.code:
            existing = Company.query.filter_by(code=new_code).first()
            if existing:
                flash(f"El código de empresa '{new_code}' ya está usado por otra subcontrata.", "danger")
                return render_template("admin_edit_company.html", company=company)
        # --------------------------------------------------------

        company.code = new_code
        company.nombre = request.form.get("nombre")
        company.nif = request.form.get("nif")
        company.descripcion = request.form.get("descripcion")
        company.gremio = request.form.get("gremio")
        company.email = request.form.get("email")
        company.color = request.form.get("color") or "#ffffff"
        
        # LEER Y ACTUALIZAR CHECKBOX
        company.is_internal = True if request.form.get("is_internal") == "on" else False

        # --- FIX: Try/Except protector ---
        try:
            db.session.commit()
            flash("Empresa actualizada correctamente", "success")
            return redirect(url_for("admin.companies"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error al guardar los cambios: {str(e)}", "danger")
            return render_template("admin_edit_company.html", company=company)
    
    return render_template("admin_edit_company.html", company=company)


@admin_bp.route("/api/rate_worker", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def rate_worker():
    data = request.get_json()
    worker_id = data.get('worker_id')
    score = data.get('score') 
    reason = data.get('reason')
    
    if not worker_id or not score:
        return jsonify({'success': False, 'message': 'Faltan datos'}), 400
        
    try:
        new_rating = Rating(
            user_id=int(worker_id),
            created_by_id=current_user.id,
            score=int(score),
            reason=reason,
            is_active=True
        )
        db.session.add(new_rating)
        db.session.commit()
        from app.utils import register_log
        operario = User.query.get(int(worker_id))
        nombre_operario = f"{operario.name} {operario.lastname}" if operario else f"ID {worker_id}"
        
        register_log(
            user_id=current_user.id,
            category='valoraciones',
            action='Nueva Valoración',
            detail=f"Ha puntuado a {nombre_operario} con un {score}. Motivo: {reason}"
        )
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


def _can_manage_rating(rating):
    from app.models import ROLE_ADMIN
    return current_user.role == ROLE_ADMIN or rating.created_by_id == current_user.id


@admin_bp.route("/api/rating/<int:rating_id>", methods=["PUT"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def update_rating(rating_id):
    rating = Rating.query.get_or_404(rating_id)
    if not _can_manage_rating(rating):
        return jsonify({'success': False, 'message': 'No autorizado'}), 403
    if not rating.is_active:
        return jsonify({'success': False, 'message': 'Esta valoración ya está archivada'}), 400

    data = request.get_json() or {}
    score = data.get('score')
    reason = data.get('reason')
    if score is None:
        return jsonify({'success': False, 'message': 'Falta la puntuación'}), 400

    try:
        rating.score = int(score)
        rating.reason = reason
        db.session.commit()
        from app.utils import register_log
        register_log(
            user_id=current_user.id,
            category='valoraciones',
            action='Editar Valoración',
            detail=f"Editada valoración #{rating.id} → {rating.score}. Motivo: {reason or '—'}",
            target_user_id=rating.user_id,
        )
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route("/api/rating/<int:rating_id>", methods=["DELETE"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def delete_rating(rating_id):
    rating = Rating.query.get_or_404(rating_id)
    if not _can_manage_rating(rating):
        return jsonify({'success': False, 'message': 'No autorizado'}), 403
    if not rating.is_active:
        return jsonify({'success': False, 'message': 'Ya estaba eliminada'}), 400

    try:
        rating.is_active = False
        db.session.commit()
        from app.utils import register_log
        register_log(
            user_id=current_user.id,
            category='valoraciones',
            action='Eliminar Valoración',
            detail=f"Eliminada valoración #{rating.id} ({rating.score} pts).",
            target_user_id=rating.user_id,
        )
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route("/worker/<int:user_id>/reset_ratings", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN) # Solo Admin puede resetear
def reset_worker_ratings(user_id):
    worker = User.query.get_or_404(user_id)
    
    # Marcamos todos los ratings actuales como inactivos (histórico)
    for r in worker.ratings_received:
        if r.is_active:
            r.is_active = False
            
    db.session.commit()
    from app.utils import register_log
    register_log(
        user_id=current_user.id,
        category='valoraciones',
        action='Reseteo de Historial',
        detail=f"Ha reseteado a 0.0 todas las valoraciones de {worker.name} {worker.lastname}."
    )
    flash(f"Puntuación de {worker.name} restablecida a 0. El historial se ha guardado.", "success")
    return redirect(url_for('admin.worker_panel', user_id=worker.id))

@admin_bp.route("/worker/<int:user_id>/ratings_history")
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def worker_ratings_history(user_id):
    worker = User.query.get_or_404(user_id)
    # Mostramos TODOS (activos e inactivos) ordenados por fecha
    ratings = Rating.query.filter_by(user_id=worker.id).order_by(Rating.created_at.desc()).all()
    return render_template("admin_worker_ratings.html", worker=worker, ratings=ratings)

@admin_bp.route("/obras", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def obras_list():
    # Filtros básicos de SQL (opcional, ya que haremos filtrado en cliente también)
    obras = (
        Obra.query
        .filter(Obra.is_deleted != True)
        .order_by(Obra.fecha_inicio.desc())
        .all()
    )
    
    # NECESARIO: Obtener lista de jefes para el desplegable de edición rápida
    jefes = User.query.filter(
        User.role.in_([ROLE_JEFE, ROLE_ADMIN]),
        User.is_deleted == False
    ).order_by(User.name).all()

    return render_template(
        "admin_obras_list.html",
        obras=obras,
        jefes=jefes
    )

# --- NUEVA RUTA API PARA CAMBIO RÁPIDO DE JEFE ---
@admin_bp.route("/api/update_obra_jefe", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_update_obra_jefe():
    data = request.get_json()
    obra_id = data.get("obra_id")
    new_jefe_id = data.get("jefe_id")
    
    obra = Obra.query.get(obra_id)
    if not obra:
        return jsonify({"success": False, "error": "Obra no encontrada"}), 404
        
    try:
        if new_jefe_id:
            obra.jefe_obra_id = int(new_jefe_id)
        else:
            obra.jefe_obra_id = None
        
        db.session.commit()
        
        # Devolver el nombre para actualizar la interfaz
        nuevo_nombre = f"{obra.jefe_obra.name} {obra.jefe_obra.lastname}" if obra.jefe_obra else "Sin asignar"
        return jsonify({"success": True, "new_name": nuevo_nombre})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# Asegúrate de que tienes estos imports al principio del archivo admin/routes.py
# from sqlalchemy.orm import joinedload
@admin_bp.route("/obras_detailed", methods=["GET"])
@login_required
def obras_detailed():
    # 1. Obtener fecha de la URL
    date_str = request.args.get('selected_date')
    
    # 2. Llamar al SERVICIO CENTRALIZADO
    # 'view_param="todas"' indica que el Admin quiere ver todas las obras activas
    context = get_dashboard_data(current_user, date_str, view_param='todas')
    
    # 3. Inyectar las URLs de navegación específicas para el Admin
    # Esto sobreescribe las del servicio para que los botones apunten a /admin/...
    context['prev_month_url'] = url_for('admin.obras_detailed', selected_date=context['prev_date_str'])
    context['next_month_url'] = url_for('admin.obras_detailed', selected_date=context['next_date_str'])
    
    # 4. Configurar modo vista (para activar botones de edición en el HTML)
    context['view_mode'] = 'readonly' if is_laboral(current_user) else 'admin'
    
    # 5. Renderizar desempaquetando el contexto (header_days, timeline_data, free_workers, etc.)
    return render_template("obras_detailed_unificado.html", **context)



@admin_bp.route("/personal", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN)
def personal():
    # 1. Usuarios INTERNOS (No operarios, O operarios de empresa interna)
    internos = User.query.join(Company, User.company_id == Company.id, isouter=True).filter(
        (User.role != ROLE_OPERARIO) | 
        ((User.role == ROLE_OPERARIO) & (Company.is_internal == True)),
        User.is_deleted == False
    ).order_by(User.name).all()

    # 2. Operarios EXTERNOS (Empresa con is_internal=False)
    base_operarios = User.query.join(Company).filter(
        User.role == ROLE_OPERARIO, 
        Company.is_internal == False, 
        User.is_deleted == False
    )
    
    # Filtro por empresa en la URL (?company_id=5)
    company_filter_id = request.args.get("company_id")
    if company_filter_id:
        base_operarios = base_operarios.filter(User.company_id == int(company_filter_id))

    operarios_activos = base_operarios.filter(User.active == True).order_by(User.name).all()
    operarios_pendientes = base_operarios.filter(User.active == False).order_by(User.name).all()

    # Para el dropdown de filtros en la vista
    companies = Company.query.filter_by(is_internal=False).all()

    from app.services.plan_service import resumen_cupo
    cupo = resumen_cupo()

    return render_template(
        "gestion_personal_unificado.html",
        view_mode="admin",
        internos=internos,
        operarios_activos=operarios_activos,
        operarios_pendientes=operarios_pendientes,
        active_count=len(operarios_activos),
        pending_count=len(operarios_pendientes),
        companies=companies, # Pasamos objetos, no strings
        company_filter=company_filter_id,
        next_url=request.path,
        cupo=cupo,
    )


@admin_bp.route("/deactivate_operario/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def deactivate_operario(user_id):
    user = User.query.get(user_id)
    if user and user.role == ROLE_OPERARIO:
        user.active = False
        db.session.commit()
        flash("Operario desactivado", "success")
    else:
        flash("Usuario no encontrado o rol inválido", "danger")
    return redirect(request.referrer or url_for("admin.personal", tab="operarios"))


@admin_bp.route("/edit_operario/<int:user_id>", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def edit_operario(user_id):
    user = User.query.get_or_404(user_id)
    companies = Company.query.all()

    if request.method == "POST":
        # Recogemos los datos críticos
        new_dni = request.form.get("dni")
        new_email = request.form.get("email")

        # --- 1. VALIDACIÓN: DNI DUPLICADO ---
        # Buscamos si existe otro usuario con ese DNI, excluyendo al propio usuario (user.id)
        existing_dni = User.query.filter(User.dni == new_dni, User.id != user.id).first()
        if existing_dni:
            flash(f"Error: El DNI {new_dni} ya pertenece a otro usuario ({existing_dni.name}).", "danger")
            # Devolvemos la plantilla directamente para no perder lo escrito, pero sin guardar
            return render_template(
                "gestion_operario_form.html",
                edit_mode=True,
                user=user, # Ojo: user sigue teniendo los datos viejos en memoria
                action_url=url_for("admin.edit_operario", user_id=user.id),
                cancel_url=url_for("admin.personal"),
                companies=companies,
            )

        # --- 2. VALIDACIÓN: EMAIL DUPLICADO ---
        existing_email = User.query.filter(User.email == new_email, User.id != user.id).first()
        if existing_email:
            flash(f"Error: El email {new_email} ya está registrado.", "danger")
            return render_template(
                "gestion_operario_form.html",
                edit_mode=True,
                user=user,
                action_url=url_for("admin.edit_operario", user_id=user.id),
                cancel_url=url_for("admin.personal"),
                companies=companies,
            )

       # --- 3. SI PASA LAS VALIDACIONES, ACTUALIZAMOS ---
        try:
            from app.services.plan_service import (
                PlanLimitError,
                cuenta_como_empleado,
                exigir_cambio_cupo,
            )

            nuevo_rol = request.form.get("role") or user.role
            nuevo_active = True if request.form.get("active") == "on" else False
            ocupar_antes = cuenta_como_empleado(user)
            ocupar_despues = cuenta_como_empleado(
                role=nuevo_rol,
                active=nuevo_active,
                is_deleted=user.is_deleted,
            )
            exigir_cambio_cupo(ocupar_antes, ocupar_despues)

            user.name = request.form.get("name")
            user.lastname = request.form.get("lastname")
            user.dni = new_dni
            user.email = new_email
            user.role = nuevo_rol
        
            
            # Gestión del Company ID (mejorado para aceptar vacíos)
            company_id = request.form.get("company_id")
            if company_id and company_id.strip():
                user.company_id = int(company_id)
            else:
                user.company_id = None # Permite dejar al usuario sin empresa si es necesario
            
            # Checkboxes (Tu lógica original)
            user.active = nuevo_active
            user.receive_emails = True if request.form.get("receive_emails") == "on" else False
            
            user.categoria_profesional = request.form.get("categoria_profesional")
            user.especialidad = request.form.get("especialidad")

            # Acceso web (email/contraseña) — independiente del PIN de /mi
            quiere_web = request.form.get("web_access") == "on"
            web_password = (request.form.get("web_password") or "").strip()
            if nuevo_rol == ROLE_OPERARIO:
                if quiere_web:
                    if not user.web_access and len(web_password) < 8:
                        flash(
                            "Para activar el acceso a la plataforma indica una "
                            "contraseña de al menos 8 caracteres.",
                            "danger",
                        )
                        return render_template(
                            "gestion_operario_form.html",
                            edit_mode=True,
                            user=user,
                            action_url=url_for("admin.edit_operario", user_id=user.id),
                            cancel_url=url_for("admin.personal"),
                            companies=companies,
                        )
                    if web_password:
                        if len(web_password) < 8:
                            flash("La contraseña web debe tener al menos 8 caracteres.", "danger")
                            return render_template(
                                "gestion_operario_form.html",
                                edit_mode=True,
                                user=user,
                                action_url=url_for("admin.edit_operario", user_id=user.id),
                                cancel_url=url_for("admin.personal"),
                                companies=companies,
                            )
                        user.password_hash = generate_password_hash(web_password)
                    user.web_access = True
                else:
                    user.web_access = False
            else:
                # Perfiles de oficina siempre tienen login web
                user.web_access = True
            
            db.session.commit()
            flash("Datos del Operario actualizados correctamente", "success")
            return redirect(url_for("admin.personal"))

        except PlanLimitError as e:
            db.session.rollback()
            flash(str(e), "danger")
        except Exception as e:
            db.session.rollback()
            flash(f"Error inesperado al guardar: {str(e)}", "danger")

    # GET Request o si falla algo
    return render_template(
        "gestion_operario_form.html",
        edit_mode=True,
        user=user,
        action_url=url_for("admin.edit_operario", user_id=user.id),
        cancel_url=url_for("admin.personal"),
        companies=companies,
    )




@admin_bp.route("/panel", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN)
def panel():
    from app.services.panel_service import get_admin_panel_context
    from app.services.onboarding_service import necesita_onboarding, estado_onboarding
    ctx = get_admin_panel_context()
    ctx['mostrar_onboarding'] = necesita_onboarding()
    ctx['onboarding'] = estado_onboarding() if ctx['mostrar_onboarding'] else None
    return render_template("admin_panel.html", **ctx)


@admin_bp.route("/panel-laboral", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def panel_laboral():
    """Landing de inicio para perfiles laboral / RRHH."""
    from app.services.panel_service import get_laboral_panel_context
    ctx = get_laboral_panel_context(
        current_user,
        puede_ver_auditoria=user_can(current_user, 'auditoria_fichajes', 'r'),
        horizon_days=14,
    )
    return render_template("admin_panel_laboral.html", **ctx)


@admin_bp.route("/primeros-pasos", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def primeros_pasos():
    """
    Wizard post-alta: obra → trabajador+PIN → fichaje móvil.
    """
    from werkzeug.security import generate_password_hash
    from app.services.onboarding_service import (
        estado_onboarding,
        marcar_onboarding_completo,
        necesita_onboarding,
        tenant_tiene_onboarding,
    )
    from app.services.oficina_obra_service import (
        CONFIG_OBRA_OFICINA,
        sincronizar_obra_oficina,
    )
    from app.services.fichaje_operario_service import CONFIG_FICHAJE_OPERARIO
    from app.services.pin_auth_service import PinAuthError, asignar_pin
    from app.services.config_service import set_tenant_config
    from app.models import Company

    if not tenant_tiene_onboarding():
        return redirect(url_for("admin.panel"))

    if request.method == "POST":
        accion = (request.form.get("accion") or "").strip()
        try:
            if accion == "oficina":
                set_tenant_config(CONFIG_OBRA_OFICINA, "True")
                sincronizar_obra_oficina(True)
                db.session.commit()
                flash("Obra Oficina lista. Ya puedes planificar y fichar ahí.", "success")
            elif accion == "obra":
                nombre = (request.form.get("nombre_obra") or "").strip()
                if len(nombre) < 2:
                    raise ValueError("Indica un nombre de obra.")
                db.session.add(Obra(
                    nombre=nombre,
                    codigo=(request.form.get("codigo_obra") or "").strip() or None,
                    estado="En Curso",
                ))
                db.session.commit()
                flash(f"Obra «{nombre}» creada.", "success")
            elif accion == "operario":
                if not _exige_email_verificado_para_usuarios():
                    return redirect(url_for("admin.primeros_pasos"))
                company = Company.query.filter_by(is_internal=True).first() or Company.query.first()
                name = (request.form.get("name") or "").strip()
                lastname = (request.form.get("lastname") or "").strip()
                dni = (request.form.get("dni") or "").strip().upper()
                pin = request.form.get("pin")
                email = (request.form.get("email") or "").strip().lower()
                if not all([name, lastname, dni, pin]):
                    raise ValueError("Nombre, apellidos, DNI y PIN son obligatorios.")
                if not email:
                    email = f"{dni.lower().replace(' ', '')}@local.signaplan"
                user = User(
                    name=name,
                    lastname=lastname,
                    dni=dni,
                    email=email,
                    role=ROLE_OPERARIO,
                    active=True,
                    email_verified=True,
                    company_id=company.id if company else None,
                    password_hash=generate_password_hash(pin),
                )
                db.session.add(user)
                db.session.flush()
                asignar_pin(user, pin, must_change=False, notify=True, actor=current_user)
                db.session.commit()
                flash(
                    f"{name} dado de alta. Entrará en /mi con DNI {dni} y su PIN.",
                    "success",
                )
            elif accion == "fichaje":
                set_tenant_config(CONFIG_FICHAJE_OPERARIO, "True")
                flash("Fichaje móvil activado. Los operarios ya pueden entrar en /mi.", "success")
            elif accion == "informe":
                from app.services.onboarding_service import marcar_informe_visto
                marcar_informe_visto()
                flash("Paso de informe marcado. Puedes volver al registro de jornada cuando quieras.", "success")
            elif accion == "listo":
                marcar_onboarding_completo()
                flash("Listo. Ya puedes usar el planificador y el registro de jornada.", "success")
                return redirect(url_for("admin.panel"))
            elif accion == "saltar":
                flash("Puedes volver a Primeros pasos desde el panel cuando quieras.", "info")
                return redirect(url_for("admin.panel"))
            elif accion == "demo_generar":
                from app.services.demo_data_service import generar_datos_demo
                qty = generar_datos_demo(actor_user=current_user)
                marcar_onboarding_completo()
                flash(
                    f"Datos de ejemplo listos: {qty['obras']} obras, "
                    f"{qty['empleados']} trabajadores, {qty['vehiculos']} vehículos. "
                    f"Explora el panel; el banner te permite borrarlos cuando quieras.",
                    "success",
                )
                return redirect(url_for("admin.panel"))
            elif accion == "demo_borrar":
                from app.services.demo_data_service import borrar_datos_demo
                from app.services.config_service import set_tenant_config
                from app.services.onboarding_service import CONFIG_ONBOARDING
                borrar_datos_demo()
                destino = (request.form.get("despues") or "panel").strip()
                flash("Datos de ejemplo eliminados.", "success")
                if destino == "wizard":
                    set_tenant_config(CONFIG_ONBOARDING, "False")
                    return redirect(url_for("admin.primeros_pasos"))
                return redirect(url_for("admin.panel"))
            else:
                raise ValueError("Acción no reconocida.")
        except (ValueError, PinAuthError) as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        except Exception as exc:
            db.session.rollback()
            flash(f"No se ha podido completar el paso: {exc}", "danger")

        return redirect(url_for("admin.primeros_pasos"))

    from app.services.demo_data_service import demo_cantidades

    estado = estado_onboarding()
    if estado["completo"] and not necesita_onboarding():
        return redirect(url_for("admin.panel"))

    obra_hecha = any(p['id'] == 'obra' and p['hecho'] for p in estado['pasos'])
    return render_template(
        "admin_primeros_pasos.html",
        onboarding=estado,
        demo_cantidades=demo_cantidades(),
        empresa_vacia=not obra_hecha,
    )


@admin_bp.route("/create_obra", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def create_obra():
    # Cargar listas necesarias
    jefes = User.query.filter(User.role == ROLE_JEFE, User.is_deleted == False).all()
    encargados = User.query.join(Company).filter(
        User.role == ROLE_OPERARIO,
        User.active == True,
        User.is_deleted == False,
        Company.is_internal == True 
    ).order_by(User.name).all()

    if request.method == "POST":
        # Recogemos datos del formulario
        codigo = request.form.get("codigo")
        jefe_obra_id = request.form.get("jefe_obra_id")
        
        # --- 1. VALIDACIÓN: JEFE OBLIGATORIO ---
        if not jefe_obra_id or not jefe_obra_id.strip():
            flash("Error: Debes seleccionar un Jefe de Obra obligatoriamente.", "danger")
            # Devolvemos form_data para no perder lo escrito
            return render_template("create_obra.html", jefes=jefes, encargados=encargados, form_data=request.form)

        # --- 2. VALIDACIÓN: CÓDIGO ÚNICO ---
        if codigo:
            # Importante: Buscamos en BD antes de crear nada
            existe = Obra.query.filter_by(codigo=codigo).first()
            if existe:
                flash(f"Error: El código '{codigo}' ya existe en la obra '{existe.nombre}'.", "danger")
                return render_template("create_obra.html", jefes=jefes, encargados=encargados, form_data=request.form)
        
        # --- 3. CREACIÓN ---
        try:
            nombre = request.form.get("nombre")
            descripcion = request.form.get("descripcion")
            ubicacion = request.form.get("ubicacion")
            fecha_inicio = request.form.get("fecha_inicio")
            fecha_fin = request.form.get("fecha_fin")
            estado = request.form.get("estado")
            limite_trabajadores = request.form.get("limite_trabajadores")
            encargado_id = request.form.get("encargado_id")
            color = request.form.get("color")

            if not color:
                from app.models import generate_random_color
                color = generate_random_color()
                
            nueva_obra = Obra(
                codigo=codigo,
                nombre=nombre,
                descripcion=descripcion,
                ubicacion=ubicacion,
                fecha_inicio=parse_date(fecha_inicio),
                fecha_fin=parse_date(fecha_fin),
                estado=estado,
                limite_trabajadores=int(limite_trabajadores) if limite_trabajadores else 0,
                jefe_obra_id=int(jefe_obra_id),
                encargado_id=int(encargado_id) if encargado_id else None,
                color=color,
            )
            db.session.add(nueva_obra)
            db.session.commit()
            
            from app.utils import register_log
            register_log(
                user_id=current_user.id,
                category='obras',
                action='Crear Obra',
                detail=f"Ha creado la obra '{nombre}' (Código: {codigo})"
            )
            
            flash("Obra creada exitosamente", "success")
            return redirect(url_for("admin.obras_detailed", selected_date=nueva_obra.fecha_inicio.strftime("%Y-%m-%d")))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Error al guardar: {str(e)}", "danger")
            return render_template("create_obra.html", jefes=jefes, encargados=encargados, form_data=request.form)
    
    # GET: Formulario vacío
    return render_template("create_obra.html", jefes=jefes, encargados=encargados, form_data={})


@admin_bp.route("/edit_obra/<int:obra_id>", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def edit_obra(obra_id):
    obra = Obra.query.get_or_404(obra_id)
    jefes = User.query.filter(User.role == ROLE_JEFE, User.is_deleted == False).all()
    encargados = User.query.join(Company).filter(
        User.role == ROLE_OPERARIO,
        User.active == True,
        User.is_deleted == False,
        Company.is_internal == True
    ).order_by(User.name).all()

    if request.method == "POST":
        # --- 1. EXTRACCIÓN DE DATOS ---
        new_codigo = request.form.get("codigo")
        new_jefe_id = request.form.get("jefe_obra_id")
        
        # --- 2. VALIDACIÓN: CÓDIGO ÚNICO (SIN TOCAR EL OBJETO AÚN) ---
        # Esto arregla el "IntegrityError autoflush"
        if new_codigo and new_codigo != obra.codigo:
            existe = Obra.query.filter(Obra.codigo == new_codigo, Obra.id != obra.id).first()
            if existe:
                flash(f"Error: El código '{new_codigo}' ya está en uso en '{existe.nombre}'.", "danger")
                # Renderizamos pasando request.form para que los campos muestren lo que el usuario escribió
                return render_template("edit_obra.html", obra=obra, jefes=jefes, encargados=encargados, form_data=request.form)

        # --- 3. VALIDACIÓN: JEFE OBLIGATORIO ---
        if not new_jefe_id or not new_jefe_id.strip():
            flash("Error: La obra no puede quedarse sin Jefe de Obra.", "danger")
            return render_template("edit_obra.html", obra=obra, jefes=jefes, encargados=encargados, form_data=request.form)

        # --- 4. ASIGNACIÓN SEGURA (Solo llegamos aquí si todo es válido) ---
        obra.codigo = new_codigo
        obra.jefe_obra_id = int(new_jefe_id)
        
        obra.nombre = request.form.get("nombre")
        obra.descripcion = request.form.get("descripcion")
        obra.ubicacion = request.form.get("ubicacion")
        obra.url_prl = request.form.get("url_prl")
        obra.color = request.form.get("color")
        
        # Gestión de estados
        old_estado = obra.estado 
        new_estado = request.form.get("estado")
        obra.estado = new_estado

        # Fechas
        f_inicio = request.form.get("fecha_inicio")
        f_fin = request.form.get("fecha_fin")
        if f_inicio: obra.fecha_inicio = parse_date(f_inicio)
        if f_fin: obra.fecha_fin = parse_date(f_fin)

        limite = request.form.get("limite_trabajadores")
        obra.limite_trabajadores = int(limite) if limite and limite.strip() else 0

        enc_id = request.form.get("encargado_id")
        obra.encargado_id = int(enc_id) if enc_id and enc_id.strip() else None

        today = date.today()
        if new_estado == 'Pendiente' and old_estado != 'Pendiente':
            futuras = Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today).all()
            for asig in futuras:
                CoreAssignmentService.desasignar(
                    asig.user_id, asig.obra_id, asig.fecha, current_user.id,
                    "Pausa de Obra", f"Obra '{obra.nombre}' pausada.",
                    registrar_log=False,
                )
            if futuras:
                from app.utils import register_log
                register_log(
                    user_id=current_user.id,
                    category='planificacion',
                    action='Pausa de Obra',
                    detail=f"Obra '{obra.nombre}' pausada: {len(futuras)} asignaciones futuras eliminadas.",
                )
                flash(f"Obra pausada. {len(futuras)} asignaciones eliminadas.", "warning")
        elif new_estado == 'Finalizada' and old_estado != 'Finalizada':
            obra.fecha_fin = today
            futuras = Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today).all()
            for asig in futuras:
                CoreAssignmentService.desasignar(
                    asig.user_id, asig.obra_id, asig.fecha, current_user.id,
                    "Finalización de Obra", f"Obra '{obra.nombre}' finalizada.",
                    registrar_log=False,
                )
            if futuras:
                from app.utils import register_log
                register_log(
                    user_id=current_user.id,
                    category='planificacion',
                    action='Finalización de Obra',
                    detail=f"Obra '{obra.nombre}' finalizada: {len(futuras)} asignaciones futuras eliminadas.",
                )
            flash(f"Obra finalizada. {len(futuras)} asignaciones eliminadas.", "success")

        try:
            db.session.commit()
            from app.utils import register_log
            register_log(
                user_id=current_user.id,
                category='obras',
                action='Editar Obra',
                detail=f"Ha editado la obra '{obra.nombre}'. Estado actual: {obra.estado}"
            )
            flash("Obra actualizada correctamente", "success")
            return redirect(url_for("admin.obras_detailed", selected_date=str(date.today())))
        except Exception as e:
            db.session.rollback()
            flash(f"Error al actualizar: {str(e)}", "danger")
            return render_template("edit_obra.html", obra=obra, jefes=jefes, encargados=encargados, form_data=request.form)

    # GET Request: form_data vacío (se usarán los datos de 'obra')
    return render_template("edit_obra.html", obra=obra, jefes=jefes, encargados=encargados, form_data={})



@admin_bp.route("/company/<int:company_id>/confirm_delete", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, redirect_to="admin.companies")
def confirm_delete_company(company_id):
    company = Company.query.get_or_404(company_id)
    
    # CORREGIDO: Filtrar por company_id, NO por company_code
    operarios = User.query.filter_by(
        role=ROLE_OPERARIO, 
        company_id=company.id,  # <--- CAMBIO AQUÍ
        is_deleted=False
    ).all()
    
    companies = Company.query.filter(Company.id != company.id).all()
    
    return render_template(
        "confirm_delete_company.html",
        company=company,
        operarios=operarios,
        companies=companies,
    )
    
@admin_bp.route("/company/<int:company_id>/delete", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, redirect_to="admin.companies")
def delete_company(company_id):
    company = Company.query.get_or_404(company_id)
    
    # CORREGIDO: Filtrar por ID
    associated_workers = User.query.filter_by(
        role=ROLE_OPERARIO, 
        company_id=company.id # <--- CAMBIO AQUÍ
    ).all()
    
    action_option = request.form.get("action_option")
    if associated_workers and action_option:
        if action_option == "reassign":
            new_company_id = request.form.get("new_company") # Recibimos ID del form
            if not new_company_id:
                flash("Debe seleccionar una empresa para reasignar", "danger")
                return redirect(url_for("admin.confirm_delete_company", company_id=company_id))
            
            # Convertir a int
            new_company = Company.query.get(int(new_company_id))
            if not new_company:
                 flash("Empresa destino no válida", "danger")
                 return redirect(url_for("admin.confirm_delete_company", company_id=company_id))

            for worker in associated_workers:
                worker.company_id = new_company.id # <--- ASIGNAR ID
                
        elif action_option == "delete":
            for worker in associated_workers:
                worker.soft_delete(actor_id=current_user.id)
                worker.company_id = None

    # --- NUEVO: LIMPIEZA DE INTEGRIDAD REFERENCIAL ---
    from app.models import Asignacion
    
    # 1. Quitamos la empresa de cualquier asignación histórica que la tenga
    Asignacion.query.filter_by(company_id=company.id).update({"company_id": None})
    
    # 2. Por seguridad, si ha quedado algún usuario "fantasma" (incluso inactivo o de otro rol) con esta empresa, se la quitamos
    User.query.filter_by(company_id=company.id).update({"company_id": None})
    
    # Ahora la BD permite el borrado sin lanzar ForeignKeyViolation
    db.session.delete(company)
    db.session.commit()
    
    flash("Empresa eliminada correctamente", "success")
    return redirect(url_for("admin.companies"))



@admin_bp.route("/reset_password/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def reset_password(user_id):
    new_password = request.form.get("new_password")
    user = User.query.get(user_id)
    if user:
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash("Contraseña restablecida", "success")
    else:
        flash("Usuario no encontrado", "danger")
    return redirect(url_for("admin.personal"))


@admin_bp.route("/enviar_acceso_fichaje/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def enviar_acceso_fichaje(user_id):
    """Asigna/regenera PIN y envía enlace para que el trabajador lo defina."""
    from app.services.pin_auth_service import PinAuthError, enviar_acceso_fichaje as _enviar

    user = User.query.get_or_404(user_id)
    pin = (request.form.get('nuevo_pin') or '').strip()
    regenerar = bool(request.form.get('regenerar'))
    try:
        ok, pin_usado = _enviar(
            user,
            pin_plano=pin or None,
            actor=current_user,
            regenerar=regenerar or not pin,
        )
        db.session.commit()
        if ok:
            extra = f' PIN provisional (solo visible aquí): {pin_usado}.' if pin_usado else ''
            flash(
                f'Enlace para definir PIN enviado a {user.email}.{extra}',
                'success',
            )
        else:
            flash(
                f'PIN preparado'
                f'{f" ({pin_usado})" if pin_usado else ""}, '
                f'pero no se pudo enviar el correo. Revisa SMTP o entrégaselo en mano.',
                'warning',
            )
    except PinAuthError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    except Exception as exc:
        db.session.rollback()
        flash(f'No se ha podido enviar el acceso: {exc}', 'danger')

    return redirect(url_for('admin.edit_operario', user_id=user.id))


@admin_bp.route("/reset_pin/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def reset_pin(user_id):
    """
    Asigna o cambia el PIN de fichaje de un trabajador.

    El PIN solo se muestra al guardarlo aquí: después queda hasheado y no se
    puede recuperar, igual que una contraseña. El correo nunca lleva el PIN
    en claro: envía un enlace para definirlo.
    """
    from app.services.pin_auth_service import PinAuthError, asignar_pin, quitar_pin

    user = User.query.get_or_404(user_id)
    accion = (request.form.get('accion') or 'asignar').strip()
    next_url = (request.form.get('next') or '').strip()

    try:
        if accion == 'quitar':
            quitar_pin(user)
            db.session.commit()
            flash(f'PIN de fichaje eliminado para {user.name} {user.lastname}.', 'success')
        elif accion == 'generar':
            from app.services.pin_auth_service import asignar_pin_generado
            _, pin_plano = asignar_pin_generado(
                user, notify=True, actor=current_user
            )
            db.session.commit()
            mail_msg = (
                ' Se ha enviado un enlace por correo para que lo defina.'
                if user.email else ''
            )
            flash(
                f'PIN provisional para {user.name} {user.lastname}: {pin_plano}. '
                f'Debe cambiarlo en el primer acceso a /mi (o con el enlace del correo).'
                f'{mail_msg}',
                'success',
            )
        else:
            from app.services.pin_auth_service import asignar_pin_explicito
            pin = request.form.get('nuevo_pin')
            asignar_pin_explicito(user, pin, notify=True, actor=current_user)
            db.session.commit()
            mail_msg = (
                ' Se ha enviado un enlace por correo para que pueda redefinirlo.'
                if user.email else ''
            )
            flash(
                f'PIN de fichaje actualizado para {user.name} {user.lastname}.'
                f'{mail_msg}',
                'success',
            )
    except PinAuthError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')

    if next_url.startswith('/admin/'):
        return redirect(next_url)
    return redirect(url_for('admin.personal'))


@admin_bp.route("/delete_user/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def delete_user(user_id):
    user = User.query.get(user_id)
    if user:
        user.soft_delete(actor_id=current_user.id)
        db.session.commit()
        flash(
            "Usuario eliminado y archivado. Se han removido asignaciones futuras.",
            "success",
        )
    else:
        flash("Usuario no encontrado", "danger")
    return redirect(url_for("admin.personal"))


@admin_bp.route("/create_user", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def create_user():
    if not _exige_email_verificado_para_usuarios():
        return redirect(url_for("admin.personal"))

    if request.method == "POST":
        # ... (Mantén toda tu lógica POST igual) ...
        email = request.form.get("email")
        password = request.form.get("password")
        role = request.form.get("role")
        name = request.form.get("name")
        lastname = request.form.get("lastname")
        dni = request.form.get("dni")
        company_id = request.form.get("company_id")
        active = True if request.form.get("active") == "on" else False
        categoria = request.form.get("categoria_profesional")
        especialidad = request.form.get("especialidad")
        web_access = True if request.form.get("web_access") == "on" else False
        if role != ROLE_OPERARIO:
            web_access = True

        from app.services.plan_service import PlanLimitError, exigir_alta_empleado
        try:
            exigir_alta_empleado(role=role, active=active)
        except PlanLimitError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("admin.create_user"))
        
        new_user = User(
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            name=name,
            lastname=lastname,
            dni=dni,
            company_id=int(company_id) if company_id else None,
            active=active,
            email_verified=True,
            web_access=web_access,
            categoria_profesional=categoria,
            especialidad=especialidad,
        )
        db.session.add(new_user)
        db.session.flush()

        pin_form = (request.form.get("pin") or "").strip()
        pin_msg = ""
        if role in (ROLE_OPERARIO, ROLE_JEFE, ROLE_ADMIN):
            from app.services.pin_auth_service import (
                PinAuthError,
                asignar_pin_explicito,
                asignar_pin_generado,
            )
            try:
                if pin_form:
                    asignar_pin_explicito(
                        new_user, pin_form, notify=True, actor=current_user
                    )
                    pin_msg = " PIN asignado."
                else:
                    _, pin_plano = asignar_pin_generado(
                        new_user, notify=True, actor=current_user
                    )
                    pin_msg = (
                        f" PIN generado ({pin_plano}): deberá cambiarlo en /mi."
                    )
            except PinAuthError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
                return redirect(url_for("admin.create_user"))

        db.session.commit()
        flash(f"Usuario creado exitosamente.{pin_msg}", "success")
        return redirect(url_for("admin.personal"))

    # --- LOGICA GET (CORREGIDA) ---
    companies = Company.query.all()
    
    # Creamos un usuario vacío para evitar el error 'undefined' en la plantilla
    dummy_user = User() 

    return render_template(
        "gestion_operario_form.html",
        edit_mode=False,
        user=dummy_user,  # <--- ESTA ES LA LÍNEA QUE FALTABA
        action_url=url_for("admin.create_user"),
        cancel_url=url_for("admin.personal"),
        companies=companies,
   )


@admin_bp.route("/approve_operario/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def approve_operario(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == ROLE_OPERARIO:
        from app.services.plan_service import (
            PlanLimitError,
            cuenta_como_empleado,
            exigir_cambio_cupo,
        )
        try:
            exigir_cambio_cupo(
                cuenta_como_empleado(user),
                cuenta_como_empleado(role=user.role, active=True, is_deleted=user.is_deleted),
            )
            user.active = True
            db.session.commit()
            flash("Operario activado", "success")
        except PlanLimitError as exc:
            flash(str(exc), "danger")
    else:
        flash("El usuario no es un operario", "danger")
    return redirect(url_for("admin.personal", tab="operarios"))





@admin_bp.route("/delete_obra/<int:obra_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def delete_obra(obra_id):
    obra = Obra.query.get(obra_id)
    if not obra:
        flash("Obra no encontrada", "danger")
        return redirect(url_for("admin.panel"))

    today = date.today()
    obra.is_deleted = True

    future_asignaciones = [a for a in obra.asignaciones if a.fecha >= today]
    for asign in future_asignaciones:
        CoreAssignmentService.desasignar(
            asign.user_id, asign.obra_id, asign.fecha, current_user.id,
            "Eliminación de Obra", f"Obra '{obra.nombre}' eliminada.",
            registrar_log=False,
        )
    if future_asignaciones:
        from app.utils import register_log
        register_log(
            user_id=current_user.id,
            category='planificacion',
            action='Eliminación de Obra',
            detail=f"Obra '{obra.nombre}' eliminada: {len(future_asignaciones)} asignaciones futuras liberadas.",
        )

    db.session.commit()

    flash(
        "Obra eliminada. Se desasignaron solo las asignaciones futuras.",
        "success",
    )
    return redirect(url_for("admin.panel"))


@admin_bp.route("/import_users", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_users():
    if request.method == "POST":
        if not _exige_email_verificado_para_usuarios():
            return redirect(url_for("admin.import_users"))
        return _handle_import_upload_post("users")
    return _render_import_upload("users")


@admin_bp.route("/import_users/preview", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_users_preview():
    if not _exige_email_verificado_para_usuarios():
        return redirect(url_for("admin.import_users"))
    return _handle_import_preview("users")


@admin_bp.route("/import_users/confirm", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_users_confirm():
    if not _exige_email_verificado_para_usuarios():
        return redirect(url_for("admin.import_users"))
    return _handle_import_confirm("users")


@admin_bp.route("/import_companies", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_companies():
    if request.method == "POST":
        return _handle_import_upload_post("companies")
    return _render_import_upload("companies")


@admin_bp.route("/import_companies/preview", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_companies_preview():
    return _handle_import_preview("companies")


@admin_bp.route("/import_companies/confirm", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_companies_confirm():
    return _handle_import_confirm("companies")


@admin_bp.route("/active_obras", methods=["GET"])
@login_required
def active_obras():
    # >>> roles con constante
    if current_user.role != ROLE_ADMIN:
        return jsonify([]), 403
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    if not start_date_str or not end_date_str:
        return jsonify([]), 400
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except Exception:
        return jsonify([]), 400

    active_obras = Obra.query.filter(
        Obra.fecha_inicio <= end_date,
        Obra.fecha_fin >= start_date,
        Obra.estado != "Finalizada",
    ).all()
    obras_list = [{"id": obra.id, "nombre": obra.nombre} for obra in active_obras]
    return jsonify(obras_list)


# ==============================================================================
# NUEVO MÓDULO: PLANIFICADOR JO (TIMELINE / GANTT)
# ==============================================================================
from flask import request, jsonify, render_template
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from app.models import Obra, User, Asignacion, Company, Solicitud
from app import db
from app.services.assignment_service import process_assignment_action

# 1. FUNCIÓN QUE CARGA EL HTML Y EL DESPLEGABLE
# 1. FUNCIÓN QUE CARGA EL HTML Y EL DESPLEGABLE
@admin_bp.route("/planificador")
@login_required
def planificador_jo():
    if current_user.role not in [ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH]:
        flash("Acceso denegado.", "danger")
        return redirect(url_for('main.dashboard'))
    todas_obras = []
    jefes = []
    
    # --- CAMBIO AQUÍ ---
    # Sacamos la consulta fuera del 'if' para que TODOS (Admins y Jefes)
    # reciban la lista de empresas y puedan usar el filtro.
    empresas = Company.query.order_by(Company.nombre).all()
    
    if current_user.role in [ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH]:
        today = date.today()
        # Filtro blindado: Ni finalizadas, ni borradas lógicamente, ni pasadas de fecha
        todas_obras = Obra.query.filter(
            func.lower(Obra.estado) != 'finalizada',
            Obra.is_deleted != True,
            or_(Obra.fecha_fin == None, Obra.fecha_fin >= today)
        ).order_by(Obra.nombre).all()
        
        # Cargamos los Jefes de Obra para el nuevo desplegable
        if current_user.role == ROLE_ADMIN:
            jefes = User.query.filter(User.role == ROLE_JEFE, User.is_deleted == False).order_by(User.name).all()
        
    return render_template("planificador.html", todas_obras=todas_obras, jefes=jefes, empresas=empresas, ROLE_ADMIN=ROLE_ADMIN)


# 2. FUNCIÓN QUE CARGA LAS FILAS (EJE Y) DEL CALENDARIO
@admin_bp.route("/api/planificador/resources")
@login_required
def api_planificador_resources():
    jefe_id = request.args.get('jefe_id')
    today = date.today()
    
    # Empaquetamos los filtros para que sean idénticos en todas las búsquedas
    base_filters = [
        func.lower(Obra.estado) != 'finalizada',
        Obra.is_deleted != True,
        or_(Obra.fecha_fin == None, Obra.fecha_fin >= today)
    ]
    
    if current_user.role == ROLE_JEFE:
        obras = Obra.query.filter(Obra.jefe_obra_id == current_user.id, *base_filters).all()
    elif current_user.role in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH):
        if jefe_id:
            obras = Obra.query.filter(Obra.jefe_obra_id == jefe_id, *base_filters).all()
        else:
            obras_ids = request.args.getlist('obra_ids[]')
            if not obras_ids:
                obras = Obra.query.filter(*base_filters).all()
            else:
                obras = Obra.query.filter(Obra.id.in_(obras_ids), *base_filters).all()
    else:
        return jsonify([])

    resources = [{
        "id": str(obra.id), 
        "title": obra.nombre, 
        "codigo": obra.codigo or '',
        "fecha_fin": obra.fecha_fin.strftime("%d/%m/%y") if obra.fecha_fin else ""
    } for obra in obras]
    
    return jsonify(resources)


# 3. FUNCIÓN QUE CARGA LOS EVENTOS Y MARCADORES
@admin_bp.route("/api/planificador/events")
@login_required
def api_planificador_events():
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    jefe_id = request.args.get('jefe_id')
    
    company_ids = request.args.getlist('company_ids[]')
    company_ids = [int(cid) for cid in company_ids if cid.lstrip('-').isdigit()]
    
    start_date = datetime.fromisoformat(start_str.replace('Z', '')).date() if start_str else datetime.today().date()
    end_date = datetime.fromisoformat(end_str.replace('Z', '')).date() if end_str else start_date + timedelta(days=30)
    today = date.today()

    base_filters = [
        func.lower(Obra.estado) != 'finalizada',
        Obra.is_deleted != True,
        or_(Obra.fecha_fin == None, Obra.fecha_fin >= today)
    ]
    
    # Recopilamos IDs asegurándonos de aplicar los mismos filtros blindados
    if current_user.role == ROLE_JEFE:
        obras_ids = [o.id for o in Obra.query.filter(Obra.jefe_obra_id == current_user.id, *base_filters).all()]
    elif current_user.role in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH):
        if jefe_id:
            obras_ids = [o.id for o in Obra.query.filter(Obra.jefe_obra_id == jefe_id, *base_filters).all()]
        else:
            req_ids = request.args.getlist('obra_ids[]')
            if not req_ids:
                obras_ids = [o.id for o in Obra.query.filter(*base_filters).all()]
            else:
                obras_ids = [o.id for o in Obra.query.filter(Obra.id.in_(req_ids), *base_filters).all()]
    else:
        return jsonify([])

    asignaciones = Asignacion.query.filter(
        Asignacion.obra_id.in_(obras_ids), Asignacion.fecha >= start_date, Asignacion.fecha <= end_date
    ).all()
    
    events_map = {}
    workers_info = {} 
    
    for a in asignaciones:
        # --- AQUÍ ESTÁ EL ARREGLO: Filtro RÁPIDO y seguro de empresa ---
        if company_ids:
            emp_id_check = a.company_id
            if not emp_id_check:
                worker_check = a.user_obj if hasattr(a, 'user_obj') else User.query.get(a.user_id)
                emp_id_check = worker_check.company_id if worker_check else 0
            
            if emp_id_check not in company_ids:
                continue
        # ---------------------------------------------------------------

        key = f"w_{a.user_id}_o_{a.obra_id}"
        if key not in events_map:
            events_map[key] = []
            worker = a.user_obj if hasattr(a, 'user_obj') else User.query.get(a.user_id)
            color = a.company.color if a.company else (worker.company_rel.color if worker and worker.company_rel else "#3b82f6")
            
            emp_nom = "Sin Empresa"
            emp_id = 0
            if a.company:
                emp_nom = a.company.nombre
                emp_id = a.company.id
            elif worker and worker.company_rel:
                emp_nom = worker.company_rel.nombre
                emp_id = worker.company_rel.id

            nota_media = 0
            if worker and hasattr(worker, 'ratings_received'):
                active_ratings = [r.score for r in worker.ratings_received if r.is_active]
                if active_ratings:
                    nota_media = sum(active_ratings) / len(active_ratings)

            workers_info[key] = {
                "name": f"{worker.name} {worker.lastname}" if worker else f"User {a.user_id}",
                "color": color, 
                "worker_id": a.user_id, 
                "obra_id": a.obra_id,
                "empresa_nombre": emp_nom,
                "empresa_id": emp_id,
                "categoria": worker.categoria_profesional if worker and worker.categoria_profesional else "",
                "especialidad": worker.especialidad if worker and worker.especialidad else "",
                "nota": round(nota_media, 1)
            }
            
        events_map[key].append(a.fecha)
        
    events = []

    from app.services.leave_service import (
        apply_leave_overlay_title,
        build_leaves_by_user,
        leave_covering,
    )
    leaves_idx = build_leaves_by_user(
        {info['worker_id'] for info in workers_info.values()},
        start_date,
        end_date,
    )
    
    def crear_bloque(start_d, end_d, curr_key, curr_info, leave=None):
        base_title = curr_info["name"]
        title, overlay_color, is_overlay = apply_leave_overlay_title(
            base_title, leave, name_first=True
        )
        events.append({
            "id": f"{curr_key}_{start_d}", "resourceId": str(curr_info["obra_id"]),
            "title": title,
            "start": start_d.strftime("%Y-%m-%d"),
            "end": (end_d + timedelta(days=1)).strftime("%Y-%m-%d"),
            "color": overlay_color or curr_info["color"],
            "worker_id": curr_info["worker_id"], "editable": True,
            "empresa_nombre": curr_info["empresa_nombre"],
            "empresa_id": curr_info["empresa_id"],
            "categoria": curr_info["categoria"],
            "especialidad": curr_info["especialidad"],
            "nota": curr_info["nota"],
            "en_ausencia": is_overlay,
            "ausencia_tipo": leave.tipo if leave else None,
        })

    for key, fechas in events_map.items():
        fechas.sort()
        if not fechas: continue
        info = workers_info[key]
        user_leaves = leaves_idx.get(info["worker_id"], [])

        # Partir bloques si cambia continuidad O estado de ausencia
        bloque_start = fechas[0]
        bloque_end = fechas[0]
        bloque_leave = leave_covering(user_leaves, fechas[0])
        bloque_leave_id = bloque_leave.id if bloque_leave else None

        for i in range(1, len(fechas)):
            d = fechas[i]
            leave_d = leave_covering(user_leaves, d)
            leave_id = leave_d.id if leave_d else None
            contiguous = (d - bloque_end).days == 1
            same_leave = leave_id == bloque_leave_id
            if contiguous and same_leave:
                bloque_end = d
            else:
                crear_bloque(bloque_start, bloque_end, key, info, bloque_leave)
                bloque_start = d
                bloque_end = d
                bloque_leave = leave_d
                bloque_leave_id = leave_id
                
        crear_bloque(bloque_start, bloque_end, key, info, bloque_leave)

    # MARCADOR FIN DE OBRA
    obras_objs = Obra.query.filter(Obra.id.in_(obras_ids)).all()
    for o in obras_objs:
        if o.fecha_fin:
            events.append({
                "id": f"fin_obra_marker_{o.id}",
                "resourceId": str(o.id),
                "start": o.fecha_fin.strftime("%Y-%m-%d"),
                "end": (o.fecha_fin + timedelta(days=1)).strftime("%Y-%m-%d"),
                "type": "background",
                "content": "<div class='fin-obra-text'>🚩 FIN OBRA</div>",
                "className": "obra-deadline-line",
                "worker_id": "SYSTEM"
            })

    # =====================================================================
    # --- INYECTAR SOLICITUDES TRASLÚCIDAS EN EL PLANIFICADOR ---
    # =====================================================================
    solicitudes = Solicitud.query.filter(
        Solicitud.obra_id.in_(obras_ids),
        Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO']),
        Solicitud.fecha_inicio <= end_date,
        Solicitud.fecha_fin >= start_date
    ).all()

    for sol in solicitudes:
        accion = getattr(sol, 'accion', 'ASIGNAR')
        is_baja = (accion == 'DESASIGNAR')
        if company_ids:
            if sol.tipo == 'CONCRETA' and sol.empleado:
                sol_comp_id = sol.empleado.company_id or 0
                if sol_comp_id not in company_ids: continue
            elif sol.tipo == 'GENERICA':
                sol_comp_id = sol.perfil_empresa_id or 0
                if sol_comp_id not in company_ids: continue
                
        # 1. Definir Colores (Sólido para el borde y texto, Traslúcido para el fondo)
        if is_baja:
            color_fuerte = "#ef4444" # Rojo
            color_suave = "rgba(239, 68, 68, 0.10)"
        else:
            color_fuerte = "#f59e0b" # Naranja
            color_suave = "rgba(245, 158, 11, 0.10)"

        # 2. Definir Título
        if sol.tipo == 'CONCRETA':
            emp_name = sol.empleado.name if sol.empleado else '?'
            title = f"{'BAJA' if is_baja else 'FALTA'}: {emp_name}"
        else:
            faltan = sol.cantidad_solicitada - sol.cantidad_cubierta
            if faltan <= 0: continue
            title = f"FALTAN: {faltan} ({sol.perfil_categoria or 'Cualquiera'})"

        # 3. Crear el estilo CSS directo para vis.js
        estilo_solicitud = f"background-color: {color_suave} !important; border: 2px dashed {color_fuerte} !important; color: {color_fuerte} !important;"

        events.append({
            "id": f"solicitud_{sol.id}",
            "resourceId": str(sol.obra_id),
            "title": title,
            "start": sol.fecha_inicio.strftime("%Y-%m-%d"),
            "end": (sol.fecha_fin + timedelta(days=1)).strftime("%Y-%m-%d"),
            "style": estilo_solicitud,
            "worker_id": "REQUEST",
            "editable": False, 
            "solicitud_id": sol.id 
        })
        
    # =====================================================================
    # --- INYECTAR FESTIVOS COMO FONDO GLOBAL ---
    # =====================================================================
    from app.models import Festivo
    festivos = Festivo.query.filter(
        Festivo.fecha >= start_date,
        Festivo.fecha <= end_date
    ).all()

    for f in festivos:
        events.append({
            "id": f"festivo_{f.id}",
            "start": f.fecha.strftime("%Y-%m-%d"),
            "end": (f.fecha + timedelta(days=1)).strftime("%Y-%m-%d"),
            "type": "background",
            "content": f"<div style='color:#b91c1c; font-weight:bold; font-size:11px; padding-top:8px; writing-mode:vertical-rl; text-orientation:mixed;'>🌴 {f.descripcion}</div>",
            "color": "rgba(239, 68, 68, 0.15)",
            "worker_id": "SYSTEM"
        })

    return jsonify(events)

@admin_bp.route("/api/planificador/search_workers", methods=['GET'])
@login_required
def search_workers():
    """Buscador Select2 filtrado por texto, excluyendo inactivos."""
    q = request.args.get('q', '').lower()
    plain = request.args.get('plain') in ('1', 'true', 'yes')

    # 1. Opción Genérica (solo solicitudes; no en alta de ausencias)
    results = []
    if not plain:
        results.append({"id": "GENERICO", "text": "👤 CUALQUIERA (Petición Genérica)"})

    # 2. Buscar en BD
    query = User.query.filter(User.active == True, User.is_deleted == False)
    if not plain:
        query = query.filter(User.role == 'operario')
    if q:
        query = query.filter(or_(
            func.lower(User.name).contains(q),
            func.lower(User.lastname).contains(q)
        ))

    workers = query.order_by(User.name, User.lastname).limit(40).all()

    # Agrupar para el Select2
    grouped = {}
    for w in workers:
        comp_name = w.company_rel.nombre if w.company_rel else "Sin Empresa"
        if comp_name not in grouped:
            grouped[comp_name] = []
        grouped[comp_name].append({
            "id": w.id,
            "text": f"{w.name} {w.lastname}"
        })

    for comp_name, children in grouped.items():
        results.append({
            "text": f"🏢 {comp_name}",
            "children": children
        })

    return jsonify({"results": results})

    
    
@admin_bp.route('/configuracion')
@login_required
def configuracion_global():
    if current_user.role != 'admin':
        flash("Acceso denegado. Área exclusiva de administración.", "danger")
        return redirect(url_for('main.dashboard'))
        
    from app.models import Festivo, ConfiguracionGlobal
    from app.services.plan_service import monetizacion_activa
    festivos = Festivo.query.order_by(Festivo.fecha.asc()).all()
    
    # Cargamos TODAS las configuraciones en un diccionario
    todas_configs = ConfiguracionGlobal.query.all()
    configs_dict = {c.clave: c.valor for c in todas_configs}
    
    # Extraemos el límite de custodia (o le damos 15 por defecto)
    limite_custodia = int(configs_dict.get('limite_custodia', 15))
    
    tenant_modulos = getattr(g.current_tenant, 'modulos_activos', {}) or {}

    return render_template(
        'admin_configuracion.html',
        festivos=festivos,
        limite_custodia=limite_custodia,
        configs=configs_dict,
        monetizacion_activa=monetizacion_activa(),
        tenant_has_fichaje_operario=bool(tenant_modulos.get('fichaje_operario')),
    )


@admin_bp.route('/configuracion/update', methods=['POST'])
@login_required
def update_config():
    if current_user.role != 'admin':
        return redirect(url_for('main.dashboard'))

    from app.models import ConfiguracionGlobal

    section = (request.form.get('form_section') or 'all').strip()

    def _upsert(clave, valor):
        conf = ConfiguracionGlobal.query.filter_by(clave=clave).first()
        if not conf:
            db.session.add(ConfiguracionGlobal(clave=clave, valor=str(valor)))
        else:
            conf.valor = str(valor)

    def _upsert_int_cfg(clave, raw, default, min_v=1, max_v=100000):
        try:
            val = int(float(str(raw).strip().replace(',', '.'))) if raw not in (None, '') else int(default)
        except (TypeError, ValueError):
            val = int(default)
        val = max(min_v, min(max_v, val))
        _upsert(clave, val)

    # Compat: formularios antiguos sin form_section
    if section == 'all':
        section_keys = {'horario', 'fichajes', 'ausencias', 'laboral', 'vehiculos', 'emails'}
    else:
        section_keys = {section}

    if 'horario' in section_keys:
        zona = (request.form.get('zona_horaria') or '').strip()
        if zona:
            _upsert('zona_horaria', zona)
            from app.utils.timezone_utils import invalidate_app_timezone_cache
            invalidate_app_timezone_cache()

        hora_limite = request.form.get('hora_limite_entrada')
        if hora_limite:
            _upsert('hora_limite_entrada', hora_limite)

        limite = request.form.get('limite_custodia')
        if limite and str(limite).isdigit():
            _upsert('limite_custodia', limite)

    if 'fichajes' in section_keys:
        primer_fichaje_val = 'True' if request.form.get('aceptar_primer_fichaje') else 'False'
        _upsert('aceptar_primer_fichaje', primer_fichaje_val)

        from app.services.fichaje_operario_service import (
            CONFIG_FICHAJE_GEO,
            CONFIG_FICHAJE_OPERARIO,
            GEO_DESACTIVADA,
            GEO_OPCIONES,
            tenant_tiene_fichaje_operario_module,
        )

        # Activar esto abre el login a los operarios, que hasta ahora no
        # entraban. Se avisa en la plantilla porque tiene consecuencias.
        from app.services.plan_service import PlanLimitError, exigir_geolocalizacion
        if tenant_tiene_fichaje_operario_module():
            operario_activo = 'True' if request.form.get('fichaje_operario_activo') else 'False'
            _upsert(CONFIG_FICHAJE_OPERARIO, operario_activo)

            modo_geo = (request.form.get('fichaje_geolocalizacion') or '').strip()
            if modo_geo not in GEO_OPCIONES:
                modo_geo = GEO_DESACTIVADA
            if modo_geo != GEO_DESACTIVADA:
                try:
                    exigir_geolocalizacion()
                except PlanLimitError as exc:
                    flash(str(exc), 'danger')
                    modo_geo = GEO_DESACTIVADA
            _upsert(CONFIG_FICHAJE_GEO, modo_geo)

            from app.services.oficina_obra_service import (
                CONFIG_OBRA_OFICINA,
                sincronizar_obra_oficina,
            )
            oficina_on = bool(request.form.get('obra_oficina_activa'))
            _upsert(CONFIG_OBRA_OFICINA, 'True' if oficina_on else 'False')
            sincronizar_obra_oficina(oficina_on)

    if 'ausencias' in section_keys:
        jefe_resuelve = 'True' if request.form.get('ausencias_jefe_puede_resolver') else 'False'
        _upsert('ausencias_jefe_puede_resolver', jefe_resuelve)

        auto_res = request.form.get('ausencias_auto_resolucion') or 'overlay'
        if auto_res not in ('overlay', 'none', 'prefer_leave', 'prefer_assignment'):
            auto_res = 'overlay'
        _upsert('ausencias_auto_resolucion', auto_res)

    if 'laboral' in section_keys:
        laboral_resuelve = 'True' if request.form.get('laboral_puede_resolver_fichajes') else 'False'
        _upsert('laboral_puede_resolver_fichajes', laboral_resuelve)

    if 'vehiculos' in section_keys:
        from app.services.vehicle_anomaly_service import (
            DEFAULT_DESVIO_MAX_PCT,
            DEFAULT_DESVIO_MIN_PCT,
            DEFAULT_THRESHOLDS,
        )
        _upsert_int_cfg(
            'vehiculo_salto_km_dia',
            request.form.get('vehiculo_salto_km_dia'),
            DEFAULT_THRESHOLDS['vehiculo_salto_km_dia'],
            min_v=50, max_v=5000,
        )
        _upsert_int_cfg(
            'vehiculo_desvio_max_pct',
            request.form.get('vehiculo_desvio_max_pct'),
            DEFAULT_DESVIO_MAX_PCT,
            min_v=1, max_v=500,
        )
        _upsert_int_cfg(
            'vehiculo_desvio_min_pct',
            request.form.get('vehiculo_desvio_min_pct'),
            DEFAULT_DESVIO_MIN_PCT,
            min_v=1, max_v=500,
        )

    if 'emails' in section_keys:
        eventos_email = [
            'email_sol_generica', 'email_sol_concreta', 'email_sol_vehiculo',
            'email_sol_resuelta',
            'email_asignacion', 'email_desasignacion', 'email_traslado',
        ]
        for evento in eventos_email:
            valores_marcados = request.form.getlist(evento)
            _upsert(evento, ",".join(valores_marcados))

    odoo_url = request.form.get('odoo_url')
    if odoo_url:
        _upsert('odoo_url', odoo_url)

    flash_msgs = {
        'horario': 'Horario y planificación guardados.',
        'fichajes': 'Configuración de fichajes guardada.',
        'ausencias': 'Configuración de ausencias guardada.',
        'laboral': 'Permisos de Laboral guardados.',
        'vehiculos': 'Alertas de vehículos guardadas.',
        'emails': 'Notificaciones por correo guardadas.',
        'all': 'Configuración global actualizada correctamente.',
    }

    try:
        db.session.commit()
        flash(flash_msgs.get(section, flash_msgs['all']), 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al guardar la configuración: {str(e)}', 'danger')

    anchor = {
        'horario': 'cfg-horario',
        'fichajes': 'cfg-fichajes',
        'ausencias': 'cfg-ausencias',
        'laboral': 'cfg-laboral',
        'vehiculos': 'cfg-vehiculos',
        'emails': 'cfg-emails',
    }.get(section)
    if anchor:
        return redirect(url_for('admin.configuracion_global') + f'#{anchor}')
    return redirect(url_for('admin.configuracion_global'))

@admin_bp.route('/configuracion/festivos/add', methods=['POST'])
@login_required
def add_festivo():
    if current_user.role != 'admin':
        return redirect(url_for('main.dashboard'))
        
    from app.models import Festivo
    fecha_str = request.form.get('fecha')
    descripcion = request.form.get('descripcion')
    
    if fecha_str:
        try:
            fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            # Comprobar si ya existe
            existe = Festivo.query.filter_by(fecha=fecha_obj).first()
            if existe:
                flash(f"El día {fecha_str} ya está marcado como festivo.", "warning")
            else:
                nuevo_festivo = Festivo(fecha=fecha_obj, descripcion=descripcion)
                db.session.add(nuevo_festivo)
                db.session.commit()
                flash(f"Día {fecha_str} añadido al calendario de festivos.", "success")
        except Exception as e:
            flash(f"Error al añadir festivo: {str(e)}", "danger")
            db.session.rollback()
            
    return redirect(url_for('admin.configuracion_global'))


@admin_bp.route('/configuracion/festivos/delete/<int:id>')
@login_required
def delete_festivo(id):
    if current_user.role != 'admin':
        return redirect(url_for('main.dashboard'))
        
    from app.models import Festivo
    f = Festivo.query.get_or_404(id)
    db.session.delete(f)
    db.session.commit()
    flash("Día festivo eliminado del sistema.", "info")
    return redirect(url_for('admin.configuracion_global'))

@admin_bp.route("/api/obras/batch_status", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def batch_update_obras_status():
    """Cambia el estado de múltiples obras a la vez y limpia asignaciones si es necesario."""
    data = request.get_json()
    obra_ids = data.get('obra_ids', [])
    new_estado = data.get('new_status')

    if not obra_ids or not new_estado:
        return jsonify({'success': False, 'message': 'Datos incompletos.'}), 400

    # AQUÍ ESTABA EL ERROR: Cambiamos 'Ejecucion' por 'En Curso'
    valid_estados = ['Pendiente', 'En Curso', 'Finalizada'] 
    
    if new_estado not in valid_estados:
        return jsonify({'success': False, 'message': 'Estado no válido.'}), 400

    try:
        obras = Obra.query.filter(Obra.id.in_(obra_ids)).all()
        today = date.today()
        total_deleted = 0

        for obra in obras:
            old_estado = obra.estado
            obra.estado = new_estado

            if new_estado == 'Pendiente' and old_estado != 'Pendiente':
                futuras = Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today).all()
                for asig in futuras:
                    CoreAssignmentService.desasignar(
                        asig.user_id, asig.obra_id, asig.fecha, current_user.id,
                        "Pausa de Obra (Masiva)", f"Obra '{obra.nombre}' pausada.",
                        registrar_log=False,
                    )
                total_deleted += len(futuras)
            elif new_estado == 'Finalizada' and old_estado != 'Finalizada':
                obra.fecha_fin = today
                futuras = Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today).all()
                for asig in futuras:
                    CoreAssignmentService.desasignar(
                        asig.user_id, asig.obra_id, asig.fecha, current_user.id,
                        "Finalización de Obra (Masiva)", f"Obra '{obra.nombre}' finalizada.",
                        registrar_log=False,
                    )
                total_deleted += len(futuras)

        if total_deleted > 0:
            from app.utils import register_log
            register_log(
                user_id=current_user.id,
                category='planificacion',
                action=f'Cambio masivo a {new_estado}',
                detail=f"{len(obras)} obra(s) → '{new_estado}': {total_deleted} jornadas futuras liberadas.",
            )

        db.session.commit()
        
        msg = f"Estado actualizado a '{new_estado}' en {len(obras)} obras."
        if total_deleted > 0:
            msg += f" Se han liberado {total_deleted} jornadas asignadas a futuro."
            
        return jsonify({'success': True, 'message': msg})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route("/api/users/batch_delete", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def batch_delete_users():
    data = request.get_json() or {}
    user_ids = data.get("user_ids", [])
    if not user_ids:
        return jsonify({"success": False, "message": "No se seleccionaron usuarios."}), 400

    deleted = 0
    for uid in user_ids:
        user = User.query.get(int(uid))
        if user and not user.is_deleted:
            user.soft_delete(actor_id=current_user.id)
            deleted += 1
    db.session.commit()
    return jsonify({"success": True, "message": f"{deleted} usuario(s) eliminado(s)."})


@admin_bp.route("/api/users/batch_deactivate", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def batch_deactivate_users():
    data = request.get_json() or {}
    user_ids = data.get("user_ids", [])
    if not user_ids:
        return jsonify({"success": False, "message": "No se seleccionaron usuarios."}), 400

    updated = 0
    for uid in user_ids:
        user = User.query.get(int(uid))
        if user and user.role == ROLE_OPERARIO and user.active:
            user.active = False
            updated += 1
    db.session.commit()
    return jsonify({"success": True, "message": f"{updated} operario(s) desactivado(s)."})


@admin_bp.route("/api/companies/batch_delete", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def batch_delete_companies():
    from app.models import Asignacion

    data = request.get_json() or {}
    company_ids = data.get("company_ids", [])
    if not company_ids:
        return jsonify({"success": False, "message": "No se seleccionaron empresas."}), 400

    deleted = 0
    for cid in company_ids:
        company = Company.query.get(int(cid))
        if not company:
            continue

        associated_workers = User.query.filter_by(
            role=ROLE_OPERARIO, company_id=company.id
        ).all()
        for worker in associated_workers:
            worker.soft_delete(actor_id=current_user.id)
            worker.company_id = None

        Asignacion.query.filter_by(company_id=company.id).update({"company_id": None})
        User.query.filter_by(company_id=company.id).update({"company_id": None})
        db.session.delete(company)
        deleted += 1

    db.session.commit()
    return jsonify({"success": True, "message": f"{deleted} empresa(s) eliminada(s)."})


@admin_bp.route("/sso/odoo_contactos")
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def sso_odoo_contactos():
    """SSO firmado hacia la app externa Alta Odoo (/sso_login)."""
    from app.utils.timezone_utils import utc_now

    sso_secret = current_app.config.get('SSO_SECRET_KEY')
    if not sso_secret:
        flash('SSO no configurado (SSO_SECRET_KEY).', 'danger')
        return redirect(url_for('admin.panel'))

    alta_url = (current_app.config.get('ODOO_ALTA_APP_URL') or '').strip().rstrip('/')
    if not alta_url:
        dominio_base = request.host.split(':')[0]
        alta_url = f"{request.scheme}://{dominio_base}:5002"

    u_name = current_user.name if current_user.name and str(current_user.name).lower() != 'none' else ''
    u_last = current_user.lastname if current_user.lastname and str(current_user.lastname).lower() != 'none' else ''
    full_name = f'{u_name} {u_last}'.strip() or current_user.email

    external_ids = getattr(current_user, 'external_ids', None) or {}
    odoo_id = external_ids.get('odoo') if isinstance(external_ids, dict) else None

    serializer = URLSafeTimedSerializer(sso_secret)
    token = serializer.dumps({
        'user_id': current_user.id,
        'odoo_id': odoo_id,
        'name': full_name,
        'email': current_user.email,
        'role': current_user.role,
        'iat': utc_now().timestamp(),
    })
    return redirect(f'{alta_url}/sso_login?token={token}')


# --- NUEVO MÓDULO DE LOGS Y AUDITORÍA ---
@admin_bp.route("/logs", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def system_logs():
    from app.models import SystemLog, LogPreference
    from app.services.log_notification_service import (
        get_unread_logs_by_category,
        get_unread_laboral_logs_by_category,
        get_laboral_acknowledged_ids,
        LABORAL_LOG_CATEGORIES,
        LABORAL_EXCLUDED_ACTIONS,
    )
    from datetime import timedelta

    allowed_categories = laboral_log_categories(current_user)
    if is_laboral(current_user):
        default_category = allowed_categories[0] if allowed_categories else 'solicitud'
    else:
        default_category = 'accesos'
    category = request.args.get('category', default_category)
    if category not in allowed_categories:
        category = default_category
    from app.utils.timezone_utils import utc_now, today_local

    logs = []
    laboral_acked_ids = set()
    if category != 'persona_obra':
        logs = SystemLog.query.filter_by(category=category).order_by(SystemLog.timestamp.desc()).limit(300).all()

        if current_user.role == ROLE_ADMIN:
            pref = LogPreference.query.filter_by(user_id=current_user.id, category=category).first()
            if pref and pref.is_active:
                pref.last_read_at = utc_now()
                db.session.commit()

        if category in LABORAL_LOG_CATEGORIES:
            laboral_acked_ids = get_laboral_acknowledged_ids(
                current_user.id, [log.id for log in logs]
            )

    active_prefs = []
    if current_user.role == ROLE_ADMIN:
        all_prefs = LogPreference.query.filter_by(user_id=current_user.id).all()
        active_prefs = [p.category for p in all_prefs if p.is_active]

    today = today_local()
    return render_template(
        "admin_logs.html",
        logs=logs,
        current_category=category,
        active_prefs=active_prefs,
        log_unread_by_category=(
            get_unread_laboral_logs_by_category(current_user.id)
            if is_laboral(current_user)
            else get_unread_logs_by_category(current_user.id, active_only=True)
        ),
        laboral_acked_ids=laboral_acked_ids,
        laboral_excluded_actions=LABORAL_EXCLUDED_ACTIONS,
        default_date=today.strftime('%Y-%m-%d'),
        default_date_from=(today - timedelta(days=7)).strftime('%Y-%m-%d'),
        default_date_to=today.strftime('%Y-%m-%d'),
        can_manage_log_prefs=(current_user.role == ROLE_ADMIN),
        log_tabs=allowed_categories,
    )


@admin_bp.route("/logs/<int:log_id>/acknowledge", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def acknowledge_system_log(log_id):
    from app.services.log_notification_service import acknowledge_log
    acknowledge_log(current_user.id, log_id)
    return jsonify({'ok': True})


@admin_bp.route("/logs/<int:log_id>/unacknowledge", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def unacknowledge_system_log(log_id):
    from app.services.log_notification_service import unacknowledge_log
    unacknowledge_log(current_user.id, log_id)
    return jsonify({'ok': True})


@admin_bp.route("/logs/acknowledge-all-laboral", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def acknowledge_all_laboral_system_logs():
    """Admin: marca como leídos TODOS los avisos laborales para todos los usuarios."""
    from app.services.log_notification_service import acknowledge_all_laboral_logs_global
    remaining = acknowledge_all_laboral_logs_global()
    return jsonify({'ok': True, 'remaining': remaining})


@admin_bp.route("/logs/preferencias", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def save_log_preferences():
    from app.models import LogPreference
    categorias = ['accesos', 'valoraciones', 'planificacion', 'obras', 'fichajes', 'solicitud']
    
    for cat in categorias:
        pref = LogPreference.query.filter_by(user_id=current_user.id, category=cat).first()
        if not pref:
            pref = LogPreference(user_id=current_user.id, category=cat)
            db.session.add(pref)
            
        # Si el checkbox está marcado viene 'on', si no, False
        pref.is_active = True if request.form.get(f'pref_{cat}') == 'on' else False
        
    db.session.commit()
    flash("Preferencias de notificaciones actualizadas.", "success")
    return redirect(url_for('admin.system_logs', category=request.form.get('current_category', 'accesos')))


# ==========================================
# AUSENCIAS PLANIFICADAS
# ==========================================

@admin_bp.route('/ausencias')
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH)
def ausencias_list():
    from datetime import date as date_cls
    from app.services.leave_service import (
        jefe_puede_resolver_ausencias,
        get_pending_conflicts,
        get_pending_manual_leaves,
        get_upcoming_leaves,
        get_leaves_scoped,
        obras_for_leave,
        auto_resolucion_ausencias,
        heal_odoo_pending_leaves,
    )

    # Vacaciones de Odoo no pasan por validación local.
    heal_odoo_pending_leaves()

    estado = request.args.get('estado') or ''
    puede_resolver = current_user.role in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH) or (
        current_user.role == ROLE_JEFE and jefe_puede_resolver_ausencias()
    )
    obra_ids = None
    if current_user.role == ROLE_JEFE:
        obra_ids = [o.id for o in Obra.query.filter_by(jefe_obra_id=current_user.id, is_deleted=False).all()]

    auto_mode = auto_resolucion_ausencias()
    conflictos = []
    if auto_mode == 'none' and puede_resolver:
        conflictos = get_pending_conflicts(obra_ids=obra_ids)

    def _rows(leaves):
        return [{'leave': leave, 'obras': obras_for_leave(leave)} for leave in leaves]

    en_curso_rows = _rows(get_upcoming_leaves(
        current_user, horizon_days=45, limit=40, only_active=True
    ))
    proximas_rows = _rows(get_upcoming_leaves(
        current_user, horizon_days=45, limit=40, only_future=True
    ))
    ausencias = get_leaves_scoped(current_user, estado=estado or None, limit=200)
    pendientes = []
    if current_user.role in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH):
        pendientes = get_pending_manual_leaves(current_user, limit=100)
    elif current_user.role == ROLE_JEFE:
        pendientes = get_pending_manual_leaves(current_user, limit=100)

    return render_template(
        'admin_ausencias.html',
        ausencias=ausencias,
        pendientes=pendientes,
        en_curso_rows=en_curso_rows,
        proximas_rows=proximas_rows,
        conflictos=conflictos,
        puede_resolver=puede_resolver,
        puede_validar_pendientes=current_user.role in (ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH),
        puede_alta_manual=current_user.role in (ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH),
        filtro_estado=estado,
        auto_mode=auto_mode,
        today=date_cls.today(),
        horizon_days=45,
    )


@admin_bp.route('/ausencias/sync', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def ausencias_sync():
    modulos = getattr(getattr(g, 'current_tenant', None), 'modulos_activos', {}) or {}
    if not modulos.get('odoo'):
        return redirect(url_for('admin.ausencias_list'))
    from app.services.leave_service import sync_leaves_from_erp
    try:
        stats = sync_leaves_from_erp()
        flash(
            f"Sync ausencias: {stats['nuevos']} nuevas, {stats['actualizados']} actualizadas, "
            f"{stats['omitidos']} omitidas, {stats['errores']} errores.",
            'success' if stats['errores'] == 0 else 'warning',
        )
    except Exception as exc:
        flash(f'Error sincronizando ausencias: {exc}', 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/crear', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH)
def ausencias_crear():
    from app.services.leave_service import (
        create_manual_leave,
        estado_alta_por_rol,
    )

    user_id = request.form.get('user_id', type=int)
    fecha_inicio = request.form.get('fecha_inicio')
    fecha_fin = request.form.get('fecha_fin')
    tipo = (request.form.get('tipo') or 'Vacaciones').strip()
    estado = estado_alta_por_rol(current_user, request.form.get('estado'))
    descripcion = request.form.get('descripcion') or None

    if not user_id or not fecha_inicio or not fecha_fin:
        flash('Faltan empleado o fechas.', 'danger')
        return redirect(url_for('admin.ausencias_list'))

    try:
        leave = create_manual_leave(
            user_id=user_id,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            tipo=tipo,
            estado=estado,
            descripcion=descripcion,
            created_by_id=current_user.id,
        )
        if leave.estado == 'pendiente':
            flash('Solicitud de ausencia enviada. Pendiente de validación.', 'info')
        else:
            flash('Ausencia creada.', 'success')
    except Exception as exc:
        flash(f'Error al crear ausencia: {exc}', 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/<int:leave_id>/aprobar', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH)
def ausencias_aprobar(leave_id):
    from app.models import LEAVE_STATUS_APROBADA
    from app.services.leave_service import set_leave_estado
    try:
        set_leave_estado(leave_id, LEAVE_STATUS_APROBADA, resolved_by_id=current_user.id)
        flash('Ausencia aprobada.', 'success')
    except Exception as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/<int:leave_id>/rechazar', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH)
def ausencias_rechazar(leave_id):
    from app.models import LEAVE_STATUS_RECHAZADA
    from app.services.leave_service import set_leave_estado
    try:
        set_leave_estado(leave_id, LEAVE_STATUS_RECHAZADA, resolved_by_id=current_user.id)
        flash('Ausencia rechazada.', 'info')
    except Exception as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/<int:leave_id>/editar', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH)
def ausencias_editar(leave_id):
    from app.services.leave_service import update_manual_leave
    try:
        leave = update_manual_leave(
            leave_id,
            current_user,
            fecha_inicio=request.form.get('fecha_inicio') or None,
            fecha_fin=request.form.get('fecha_fin') or None,
            tipo=request.form.get('tipo'),
            descripcion=request.form.get('descripcion'),
        )
        if leave.estado == 'pendiente':
            flash('Ausencia actualizada y pendiente de validación.', 'info')
        else:
            flash('Ausencia actualizada.', 'success')
    except Exception as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/<int:leave_id>/borrar', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH)
def ausencias_borrar(leave_id):
    from app.services.leave_service import delete_manual_leave
    try:
        delete_manual_leave(leave_id, current_user)
        flash('Ausencia eliminada.', 'success')
    except Exception as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/conflictos/<int:conflict_id>/resolver', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def ausencias_resolver_conflicto(conflict_id):
    from app.models import AusenciaConflicto, CONFLICT_KEEP_LEAVE, CONFLICT_KEEP_ASSIGNMENT
    from app.services.leave_service import (
        jefe_puede_resolver_ausencias,
        resolve_conflict,
    )

    if current_user.role == ROLE_JEFE and not jefe_puede_resolver_ausencias():
        flash('No tienes permiso para resolver conflictos de ausencias.', 'danger')
        return redirect(url_for('admin.ausencias_list'))
    if is_laboral(current_user) and not user_can(current_user, 'ausencias', 'x'):
        flash('No tienes permiso para resolver conflictos de ausencias.', 'danger')
        return redirect(url_for('admin.ausencias_list'))

    decision = request.form.get('decision')
    if decision not in (CONFLICT_KEEP_LEAVE, CONFLICT_KEEP_ASSIGNMENT):
        flash('Decisión no válida.', 'danger')
        return redirect(url_for('admin.ausencias_list'))

    conflict = AusenciaConflicto.query.get_or_404(conflict_id)
    if current_user.role == ROLE_JEFE:
        obra = Obra.query.get(conflict.obra_id)
        if not obra or obra.jefe_obra_id != current_user.id:
            flash('Solo puedes resolver conflictos de tus obras.', 'danger')
            return redirect(url_for('admin.ausencias_list'))
    # laboral: like admin, no obra scope

    try:
        ok = resolve_conflict(conflict_id, decision, resolved_by_id=current_user.id)
        db.session.commit()
        flash('Conflicto resuelto.' if ok else 'El conflicto ya estaba resuelto.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Error al resolver: {exc}', 'danger')
    return redirect(url_for('admin.ausencias_list'))


# ---------------------------------------------------------------------------
# Registro de jornada (informe para la Inspección)
# ---------------------------------------------------------------------------

def _parametros_informe():
    from app.services.fichaje_informe_service import (
        FichajeInformeError,
        generar_informe,
        periodo_por_defecto,
    )

    desde_def, hasta_def = periodo_por_defecto()
    desde = request.args.get('desde') or desde_def.isoformat()
    hasta = request.args.get('hasta') or hasta_def.isoformat()
    user_id = request.args.get('user_id') or None
    company_id = request.args.get('company_id') or None

    if user_id in ('', '0'):
        user_id = None
    if company_id in ('', '0'):
        company_id = None

    tenant_nombre = g.current_tenant.nombre if getattr(g, 'current_tenant', None) else None
    try:
        return generar_informe(
            desde=desde,
            hasta=hasta,
            user_id=user_id,
            company_id=company_id,
            tenant_nombre=tenant_nombre,
        )
    except FichajeInformeError as exc:
        flash(str(exc), 'warning')
        return None


@admin_bp.route('/registro-jornada')
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def registro_jornada():
    """
    Pantalla de consulta y descarga del registro de jornada.

    Es lo que se enseña a la Inspección: detalle por trabajador y verificación
    de que el libro de eventos no ha sido manipulado.
    """
    from app.services.fichaje_informe_service import (
        formatear_horas,
        listar_empresas_para_filtro,
        listar_trabajadores_para_filtro,
        periodo_por_defecto,
    )
    from app.services.onboarding_service import tenant_tiene_registro_jornada

    if not tenant_tiene_registro_jornada():
        return redirect(url_for('admin.panel'))

    desde_def, hasta_def = periodo_por_defecto()
    hay_filtros = any(
        request.args.get(k) for k in ('desde', 'hasta', 'user_id', 'company_id')
    )
    informe = _parametros_informe() if hay_filtros or request.args.get('generar') else None

    if informe is not None:
        from app.services.onboarding_service import marcar_informe_visto
        try:
            marcar_informe_visto()
        except Exception:
            pass

    url_fichaje_mi = None
    try:
        from app.services.signup_service import url_acceso_tenant
        if getattr(g, 'current_tenant', None):
            url_fichaje_mi = url_acceso_tenant(g.current_tenant, path='/mi')
    except Exception:
        url_fichaje_mi = None

    return render_template(
        'admin_registro_jornada.html',
        informe=informe,
        trabajadores=listar_trabajadores_para_filtro(),
        empresas=listar_empresas_para_filtro(),
        desde=request.args.get('desde') or desde_def.isoformat(),
        hasta=request.args.get('hasta') or hasta_def.isoformat(),
        user_id=request.args.get('user_id') or '',
        company_id=request.args.get('company_id') or '',
        formatear_horas=formatear_horas,
        desde_onboarding=bool(request.args.get('desde_onboarding')),
        url_fichaje_mi=url_fichaje_mi,
    )


@admin_bp.route('/registro-jornada/imprimir')
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def registro_jornada_imprimir():
    from app.services.fichaje_informe_service import etiquetar_tipo, formatear_horas
    from app.services.onboarding_service import tenant_tiene_registro_jornada

    if not tenant_tiene_registro_jornada():
        return redirect(url_for('admin.panel'))

    informe = _parametros_informe()
    if informe is None:
        return redirect(url_for('admin.registro_jornada'))

    return render_template(
        'admin_registro_jornada_print.html',
        informe=informe,
        formatear_horas=formatear_horas,
        etiquetar_tipo=etiquetar_tipo,
    )


@admin_bp.route('/registro-jornada.csv')
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def registro_jornada_csv():
    from flask import Response
    from app.services.fichaje_informe_service import informe_a_csv
    from app.services.onboarding_service import tenant_tiene_registro_jornada

    if not tenant_tiene_registro_jornada():
        return redirect(url_for('admin.panel'))

    informe = _parametros_informe()
    if informe is None:
        return redirect(url_for('admin.registro_jornada'))

    archivo = (
        f"registro_jornada_{informe['desde']}_{informe['hasta']}.csv"
    )
    return Response(
        informe_a_csv(informe),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{archivo}"'},
    )


@admin_bp.route('/registro-jornada.pdf')
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def registro_jornada_pdf():
    """
    PDF generado con wkhtmltopdf a partir de la misma plantilla de impresión.

    Si el binario no está disponible, se redirige a la vista imprimible: el
    navegador puede guardar como PDF sin perder el contenido.
    """
    from flask import make_response
    from app.services.fichaje_informe_service import etiquetar_tipo, formatear_horas
    from app.services.onboarding_service import tenant_tiene_registro_jornada

    if not tenant_tiene_registro_jornada():
        return redirect(url_for('admin.panel'))

    informe = _parametros_informe()
    if informe is None:
        return redirect(url_for('admin.registro_jornada'))

    html = render_template(
        'admin_registro_jornada_print.html',
        informe=informe,
        formatear_horas=formatear_horas,
        etiquetar_tipo=etiquetar_tipo,
        para_pdf=True,
    )

    try:
        import pdfkit
        pdf = pdfkit.from_string(
            html,
            False,
            options={
                'page-size': 'A4',
                'encoding': 'UTF-8',
                'margin-top': '12mm',
                'margin-bottom': '14mm',
                'margin-left': '12mm',
                'margin-right': '12mm',
                'print-media-type': None,
                'quiet': '',
            },
        )
    except Exception as exc:
        current_app.logger.warning('No se pudo generar el PDF del registro: %s', exc)
        flash(
            'No se ha podido generar el PDF en el servidor. '
            'Usa «Versión para imprimir» y guárdalo como PDF desde el navegador.',
            'warning',
        )
        return redirect(url_for(
            'admin.registro_jornada_imprimir',
            desde=request.args.get('desde'),
            hasta=request.args.get('hasta'),
            user_id=request.args.get('user_id') or '',
            company_id=request.args.get('company_id') or '',
        ))

    archivo = f"registro_jornada_{informe['desde']}_{informe['hasta']}.pdf"
    respuesta = make_response(pdf)
    respuesta.headers['Content-Type'] = 'application/pdf'
    respuesta.headers['Content-Disposition'] = f'attachment; filename="{archivo}"'
    return respuesta

