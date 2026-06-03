# app/admin/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, and_
from app.models import (
    User,
    Obra,
    Asignacion,
    ROLE_ADMIN,
    ROLE_JEFE,
    ROLE_RRHH,
    ROLE_OPERARIO,
    Company,
    Solicitud,
)
from app import db
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta, date


from app.services.solicitud_service import update_solicitudes_for_assignment
from app.services.assignment_service import process_assignment_action

from app.decorators import roles_required
from itsdangerous import URLSafeTimedSerializer
import os
# Añadir en la zona de imports de app/admin/routes.py
from app.services.import_service import process_obras_import, process_users_import
from app.models import Rating


from app.services.dashboard_service import get_dashboard_data, parse_date

from app.services.email_service import notificar_resolucion_solicitud, notificar_movimiento_admin_a_jo
# Definición del blueprint de admin
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
ALLOWED_EXTENSIONS = {"xlsx"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@admin_bp.route("/import_obras", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_obras():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not allowed_file(file.filename):
            flash("Por favor, sube un archivo .xlsx válido.", "danger")
            return redirect(request.url)

        # Llamada al servicio
        success, message, count = process_obras_import(file)

        if success:
            flash(message, "success")
            return redirect(url_for("admin.obras_detailed"))
        else:
            flash(message, "danger")
            return redirect(request.url)

    return render_template("import_obras.html")

@admin_bp.route('/solicitudes')
@login_required
def solicitudes_list():
    estado = request.args.get('estado', 'todas')
    tipo = request.args.get('tipo', 'todas')
    obra_id = request.args.get('obra_id')
    date_filter_str = request.args.get('date_filter')
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

    target_date = None
    if date_filter_str:
        target_date = parse_date(date_filter_str)
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

    estados_posibles = ['todas', 'PENDIENTE', 'EN_PROCESO', 'CUMPLIDA', 'CERRADA_PARCIAL', 'DENEGADA']
    tipos_posibles = ['todas', 'generica', 'concreta']
    obra_seleccionada = Obra.query.get(int(obra_id)) if obra_id and obra_id.isdigit() else None

    return render_template(
        'admin_solicitudes_list.html',
        solicitudes=solicitudes,
        stats=stats, 
        estado_filtro=estado,
        tipo_filtro=tipo,
        date_filtro=target_date,
        obra_filtro=obra_seleccionada,
        estados_posibles=estados_posibles,
        tipos_posibles=tipos_posibles,
    )
    
@admin_bp.route("/worker_panel/<int:user_id>", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_RRHH)
def worker_panel(user_id):
    """
    Ficha del trabajador con calendario de sus asignaciones Y SOLICITUDES.
    (El calendario carga por API V6)
    """
    worker = User.query.get_or_404(user_id)
    return render_template("admin_worker_panel.html", worker=worker)


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
    
    return render_template("admin_company_panel.html", company=company)

   
    
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

        # Calcular duración total de la solicitud (en días)
        total_days_req = (fecha_fin - fecha_inicio).days + 1

        # Buscar TODAS las asignaciones en este rango para los candidatos
        # (Incluimos la propia obra para que salgan como ocupados si ya están asignados aquí)
        all_assignments = Asignacion.query.filter(
            Asignacion.fecha >= fecha_inicio,
            Asignacion.fecha <= fecha_fin,
            Asignacion.user_id.in_([u.id for u in profile_candidates])
        ).all()
        
        # Agrupar asignaciones por usuario para contar días ocupados
        busy_counts = {} # {user_id: set(fechas_ocupadas)}
        for a in all_assignments:
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
@roles_required(ROLE_ADMIN, ROLE_RRHH)
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
@roles_required(ROLE_ADMIN, ROLE_JEFE)
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
    
    return render_template(
        "admin_obra_panel.html",
        obra=obra,
        jefes=jefes,
        today=date.today()
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
        color = request.form.get("color") or "#ffffff"
        
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

    return render_template("admin_create_company.html")


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
@roles_required(ROLE_ADMIN, ROLE_RRHH)
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
    context['view_mode'] = 'admin' 
    
    # 5. Renderizar desempaquetando el contexto (header_days, timeline_data, free_workers, etc.)
    return render_template("obras_detailed_unificado.html", **context)



@admin_bp.route("/personal", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_RRHH)
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
        next_url=request.path
    )


@admin_bp.route("/deactivate_operario/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_RRHH)
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
@roles_required(ROLE_ADMIN, ROLE_RRHH)
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
            user.name = request.form.get("name")
            user.lastname = request.form.get("lastname")
            user.dni = new_dni
            user.email = new_email
            
            # AÑADE ESTO PARA QUE SE GUARDE EL ROL:
            nuevo_rol = request.form.get("role")
            if nuevo_rol:
                user.role = nuevo_rol
        
            
            # Gestión del Company ID (mejorado para aceptar vacíos)
            company_id = request.form.get("company_id")
            if company_id and company_id.strip():
                user.company_id = int(company_id)
            else:
                user.company_id = None # Permite dejar al usuario sin empresa si es necesario
            
            # Checkboxes (Tu lógica original)
            user.active = True if request.form.get("active") == "on" else False
            user.receive_emails = True if request.form.get("receive_emails") == "on" else False
            
            user.categoria_profesional = request.form.get("categoria_profesional")
            user.especialidad = request.form.get("especialidad")
            
            db.session.commit()
            flash("Datos del Operario actualizados correctamente", "success")
            return redirect(url_for("admin.personal"))

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
    # --- Estadísticas Generales ---
    total_operarios = User.query.filter_by(role=ROLE_OPERARIO, is_deleted=False).count()
    total_obras = Obra.query.filter(Obra.is_deleted != True).count()
    
    total_jefes = User.query.filter(
        User.role == ROLE_JEFE, 
        User.is_deleted == False
    ).count()
    
    total_rrhh = User.query.filter_by(role=ROLE_RRHH, is_deleted=False).count()

    recent_obras = (
        Obra.query.filter(Obra.is_deleted != True)
        .order_by(Obra.id.desc())
        .limit(5)
        .all()
    )

    # --- CORRECCIÓN CRÍTICA: Usar relación SQL en lugar de company_code ---
    
    # 1. Internos: Operarios asociados a una empresa con flag is_internal=True
    total_internos = (
        User.query
        .join(Company) # Hacemos Join con la tabla de empresas
        .filter(
            User.role == ROLE_OPERARIO,
            User.is_deleted == False,
            Company.is_internal == True # Filtramos por la propiedad de la empresa
        ).count()
    )

    # 2. Externos: Operarios asociados a una empresa con flag is_internal=False
    total_externos = (
        User.query
        .join(Company)
        .filter(
            User.role == ROLE_OPERARIO,
            User.is_deleted == False,
            Company.is_internal == False
        ).count()
    )

    total_companies = Company.query.count()

    return render_template(
        "admin_panel.html",
        total_operarios=total_operarios,
        total_obras=total_obras,
        total_jefes=total_jefes,
        total_rrhh=total_rrhh,
        total_internos=total_internos,
        total_externos=total_externos,
        total_companies=total_companies,
        recent_obras=recent_obras,
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

        # Lógica de impacto (Pausar/Finalizar)
        today = date.today()
        if new_estado == 'Pendiente' and old_estado != 'Pendiente':
            deleted_count = Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today).delete(synchronize_session=False)
            if deleted_count > 0: flash(f"Obra pausada. {deleted_count} asignaciones eliminadas.", "warning")
        elif new_estado == 'Finalizada' and old_estado != 'Finalizada':
            obra.fecha_fin = today
            deleted_count = Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today).delete(synchronize_session=False)
            flash(f"Obra finalizada. {deleted_count} asignaciones eliminadas.", "success")

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
                worker.soft_delete()
                worker.company_id = None # <--- IMPORTANTE: Desvincular para poder borrar

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
@roles_required(ROLE_ADMIN, ROLE_RRHH)
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


@admin_bp.route("/delete_user/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_RRHH)
def delete_user(user_id):
    user = User.query.get(user_id)
    if user:
        user.soft_delete()
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
@roles_required(ROLE_ADMIN, ROLE_RRHH)
def create_user():
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
        
        new_user = User(
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            name=name,
            lastname=lastname,
            dni=dni,
            company_id=int(company_id) if company_id else None,
            active=active,
            categoria_profesional=categoria,
            especialidad=especialidad,
        )
        db.session.add(new_user)
        db.session.commit()
        flash("Usuario creado exitosamente", "success")
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
@roles_required(ROLE_ADMIN, ROLE_RRHH)
def approve_operario(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == ROLE_OPERARIO:
        user.active = True
        db.session.commit()
        flash("Operario activado", "success")
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
        db.session.delete(asign)


    db.session.commit()

    flash(
        "Obra eliminada. Se desasignaron solo las asignaciones futuras.",
        "success",
    )
    return redirect(url_for("admin.panel"))


@admin_bp.route("/import_users", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_RRHH)
def import_users():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename.lower().endswith(".xlsx"):
            flash("Por favor, seleccione un archivo Excel (.xlsx) válido.", "danger")
            return redirect(url_for("admin.import_users"))
        
        # Llamada al servicio
        success, message, data = process_users_import(file)

        if success:
            return render_template(
                "admin_import_results.html",
                imported=data.get('imported', []),
                created_companies=data.get('created_companies', [])
            )
        else:
            flash(message, "danger")
            return redirect(url_for("admin.import_users"))

    return render_template("admin_import_users.html")

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
    todas_obras = []
    jefes = []
    
    # --- CAMBIO AQUÍ ---
    # Sacamos la consulta fuera del 'if' para que TODOS (Admins y Jefes)
    # reciban la lista de empresas y puedan usar el filtro.
    empresas = Company.query.order_by(Company.nombre).all()
    
    if current_user.role == ROLE_ADMIN:
        today = date.today()
        # Filtro blindado: Ni finalizadas, ni borradas lógicamente, ni pasadas de fecha
        todas_obras = Obra.query.filter(
            func.lower(Obra.estado) != 'finalizada',
            Obra.is_deleted != True,
            or_(Obra.fecha_fin == None, Obra.fecha_fin >= today)
        ).order_by(Obra.nombre).all()
        
        # Cargamos los Jefes de Obra para el nuevo desplegable
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
    elif current_user.role == ROLE_ADMIN:
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
    elif current_user.role == ROLE_ADMIN:
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
    
    def crear_bloque(start_d, end_d, curr_key, curr_info):
        events.append({
            "id": f"{curr_key}_{start_d}", "resourceId": str(curr_info["obra_id"]),
            "title": curr_info["name"], "start": start_d.strftime("%Y-%m-%d"),
            "end": (end_d + timedelta(days=1)).strftime("%Y-%m-%d"),
            "color": curr_info["color"], "worker_id": curr_info["worker_id"], "editable": True,
            "empresa_nombre": curr_info["empresa_nombre"],
            "empresa_id": curr_info["empresa_id"],
            "categoria": curr_info["categoria"],
            "especialidad": curr_info["especialidad"],
            "nota": curr_info["nota"]
        })

    for key, fechas in events_map.items():
        fechas.sort()
        if not fechas: continue
        info = workers_info[key]
        bloque_start = fechas[0]
        bloque_end = fechas[0]
        
        for i in range(1, len(fechas)):
            if (fechas[i] - bloque_end).days == 1:
                bloque_end = fechas[i]
            else:
                crear_bloque(bloque_start, bloque_end, key, info)
                bloque_start = fechas[i]
                bloque_end = fechas[i]
                
        crear_bloque(bloque_start, bloque_end, key, info)

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
    
    # 1. Opción Genérica
    results = [{"id": "GENERICO", "text": "👤 CUALQUIERA (Petición Genérica)"}]
    
    # 2. Buscar en BD
    query = User.query.filter(User.role == 'operario', User.active == True, User.is_deleted == False)
    if q:
        query = query.filter(or_(
            func.lower(User.name).contains(q),
            func.lower(User.lastname).contains(q)
        ))
        
    workers = query.limit(30).all()
    
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
    festivos = Festivo.query.order_by(Festivo.fecha.asc()).all()
    
    # Cargamos TODAS las configuraciones en un diccionario
    todas_configs = ConfiguracionGlobal.query.all()
    configs_dict = {c.clave: c.valor for c in todas_configs}
    
    # Extraemos el límite de custodia (o le damos 15 por defecto)
    limite_custodia = int(configs_dict.get('limite_custodia', 15))
    
    return render_template('admin_configuracion.html', festivos=festivos, limite_custodia=limite_custodia, configs=configs_dict)


@admin_bp.route('/configuracion/update', methods=['POST'])
@login_required
def update_config():
    if current_user.role != 'admin':
        return redirect(url_for('main.dashboard'))
        
    from app.models import ConfiguracionGlobal
    
    # 1. Guardar Límite de Custodia
    limite = request.form.get('limite_custodia')
    if limite and limite.isdigit():
        conf = ConfiguracionGlobal.query.filter_by(clave='limite_custodia').first()
        if not conf: db.session.add(ConfiguracionGlobal(clave='limite_custodia', valor=limite))
        else: conf.valor = limite
    
    hora_limite = request.form.get('hora_limite_entrada')
    if hora_limite:
        conf_hora = ConfiguracionGlobal.query.filter_by(clave='hora_limite_entrada').first()
        if not conf_hora:
            db.session.add(ConfiguracionGlobal(clave='hora_limite_entrada', valor=hora_limite))
        else:
            conf_hora.valor = hora_limite
            
    # 2. Guardar Matriz de Emails (Convertimos la lista de checkboxes en un string separado por comas: "admin,jefe,trabajador")
    eventos_email = ['email_sol_generica', 'email_sol_concreta', 'email_sol_resuelta', 'email_asignacion', 'email_desasignacion', 'email_traslado']
    
    for evento in eventos_email:
        # request.form.getlist te da los values marcados, ej: ['admin', 'trabajador']
        valores_marcados = request.form.getlist(evento)
        valor_str = ",".join(valores_marcados) 
        
        conf = ConfiguracionGlobal.query.filter_by(clave=evento).first()
        if not conf:
            db.session.add(ConfiguracionGlobal(clave=evento, valor=valor_str))
        else:
            conf.valor = valor_str
    
    # --- AÑADIR ESTE BLOQUE ---
    # 3. Guardar Configuración del Primer Fichaje (Inercia)
    # Si el checkbox está marcado en el formulario, llega como 'on', si no, llega None
    primer_fichaje_val = 'True' if request.form.get('aceptar_primer_fichaje') else 'False'
        
    conf_primer = ConfiguracionGlobal.query.filter_by(clave='aceptar_primer_fichaje').first()
    if not conf_primer:
        db.session.add(ConfiguracionGlobal(clave='aceptar_primer_fichaje', valor=primer_fichaje_val))
    else:
        conf_primer.valor = primer_fichaje_val

    odoo_url = request.form.get('odoo_url')
    if odoo_url:
        conf_odoo = ConfiguracionGlobal.query.filter_by(clave='odoo_url').first()
        if not conf_odoo:
            db.session.add(ConfiguracionGlobal(clave='odoo_url', valor=odoo_url))
        else:
            conf_odoo.valor = odoo_url
            
    try:
            db.session.commit()
            flash('Configuración global actualizada correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al guardar la configuración: {str(e)}', 'danger')
        
    
            
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

            # Si se pausa o finaliza, borramos las asignaciones del futuro para liberar a la gente
            if new_estado == 'Pendiente' and old_estado != 'Pendiente':
                deleted = Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today).delete(synchronize_session=False)
                total_deleted += deleted
            elif new_estado == 'Finalizada' and old_estado != 'Finalizada':
                obra.fecha_fin = today
                deleted = Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today).delete(synchronize_session=False)
                total_deleted += deleted

        db.session.commit()
        
        msg = f"Estado actualizado a '{new_estado}' en {len(obras)} obras."
        if total_deleted > 0:
            msg += f" Se han liberado {total_deleted} jornadas asignadas a futuro."
            
        return jsonify({'success': True, 'message': msg})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
@admin_bp.route("/sso/odoo_contactos")
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def sso_odoo_contactos():
    from app.models import ConfiguracionGlobal
    from itsdangerous import URLSafeTimedSerializer
    import datetime

    sso_secret = current_app.config.get('SSO_SECRET_KEY', 'default_dev_secret_key')
    
    # 1. Buscar si el cliente tiene una instancia de Odoo configurada
    conf_odoo = ConfiguracionGlobal.query.filter_by(clave='odoo_url').first()
    
    if conf_odoo and conf_odoo.valor:
        odoo_url = conf_odoo.valor.rstrip('/') # Quitamos barra final para evitar errores
    else:
        # Fallback por defecto (puerto 5002) si no ha configurado nada
        dominio_base = request.host.split(':')[0]
        odoo_url = f"{request.scheme}://{dominio_base}:5002"

    # Limpieza de nombre
    u_name = current_user.name if current_user.name and str(current_user.name).lower() != 'none' else ""
    u_last = current_user.lastname if current_user.lastname and str(current_user.lastname).lower() != 'none' else ""
    full_name = f"{u_name} {u_last}".strip() or current_user.username

    serializer = URLSafeTimedSerializer(sso_secret)
    payload = {
        'user_id': current_user.id,
        'odoo_id': current_user.odoo_id,
        'name': full_name,
        'iat': datetime.datetime.utcnow().timestamp()
    }
    token = serializer.dumps(payload)
    
    return redirect(f"{odoo_url}/sso_login?token={token}")

# --- NUEVO MÓDULO DE LOGS Y AUDITORÍA ---
@admin_bp.route("/logs", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN)
def system_logs():
    from app.models import SystemLog, LogPreference
    from datetime import datetime
    
    category = request.args.get('category', 'accesos')
    
    # 1. Traer los logs de la categoría seleccionada
    logs = SystemLog.query.filter_by(category=category).order_by(SystemLog.timestamp.desc()).limit(300).all()
    
    # 2. Resetear el contador de notificaciones para esta pestaña al entrar
    pref = LogPreference.query.filter_by(user_id=current_user.id, category=category).first()
    if pref and pref.is_active:
        pref.last_read_at = datetime.utcnow()
        db.session.commit()
        
    # 3. Traer qué preferencias tiene activas para marcar los checkboxes
    all_prefs = LogPreference.query.filter_by(user_id=current_user.id).all()
    active_prefs = [p.category for p in all_prefs if p.is_active]
    
    return render_template("admin_logs.html", logs=logs, current_category=category, active_prefs=active_prefs)

@admin_bp.route("/logs/preferencias", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def save_log_preferences():
    from app.models import LogPreference
    categorias = ['accesos', 'valoraciones', 'planificacion', 'obras', 'fichajes']
    
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