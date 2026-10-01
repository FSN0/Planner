# app/jefe_obra/routes.py

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
)
from sqlalchemy import or_, and_
import json # Asegúrate de importar json arriba
from flask_login import login_required, current_user
from datetime import datetime, timedelta, date

from app import db
from app.models import (
    Obra,
    ROLE_JEFE,
    ROLE_ADMIN,
    User,
    Solicitud,
    Asignacion
)
from app.decorators import roles_required
from app.services.assignment_service import process_assignment_action
from app.services.email_service import notificar_nueva_solicitud

# --- IMPORTACIÓN DEL CEREBRO CENTRAL ---
# Esto sustituye a todas las utilidades sueltas anteriores
from app.services.dashboard_service import get_dashboard_data, parse_date

jefe_bp = Blueprint('jefe', __name__, url_prefix='/jefe')


@jefe_bp.before_request
def _enforce_jefe_module_permissions():
    from app.services.permission_guard import enforce_jefe_permissions
    return enforce_jefe_permissions()


@jefe_bp.route('/panel', methods=['GET'])
@login_required
def panel():
    from app.services.permission_service import user_can, can_resolve_fichajes
    from app.services.user_home_service import resolve_inicio_panel_url
    if not user_can(current_user, 'inicio', 'r'):
        flash("Acceso no autorizado", "danger")
        return redirect(url_for('main.dashboard'))

    dest = resolve_inicio_panel_url(current_user)
    jefe_url = url_for('jefe.panel')
    if dest and dest != jefe_url:
        return redirect(dest)

    from app.services.panel_service import get_jefe_panel_context
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes
    ctx = get_jefe_panel_context(current_user)
    ctx['puede_resolver_auditoria'] = (
        can_resolve_fichajes(current_user) and tenant_muestra_auditoria_fichajes()
    )
    return render_template('jefe_panel.html', **ctx)


@jefe_bp.route('/api/panel/kpi_detail', methods=['GET'])
@login_required
def api_panel_kpi_detail():
    from app.services.permission_service import user_can
    if not user_can(current_user, 'inicio', 'r'):
        return jsonify({'success': False, 'message': 'No autorizado'}), 403
    from app.services.panel_service import get_panel_kpi_detail, _obra_ids_del_jefe
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes
    from app.services.panel_scope_service import (
        PANEL_TABLERO,
        apply_obra_scope_filter,
        planning_acts_as_office,
    )

    kind = (request.args.get('kind') or '').strip().lower()
    fecha = (request.args.get('fecha') or '').strip() or None
    if kind in ('fichajes', 'auditoria') and not tenant_muestra_auditoria_fichajes():
        return jsonify({'success': False, 'message': 'No disponible'}), 403

    if planning_acts_as_office(current_user):
        obra_ids = None
    else:
        from app.models import Obra
        obra_ids = [
            o.id for o in apply_obra_scope_filter(
                Obra.query.filter_by(is_deleted=False),
                current_user,
                PANEL_TABLERO,
            ).all()
        ]
        if not obra_ids:
            obra_ids = _obra_ids_del_jefe(current_user.id)

    try:
        data = get_panel_kpi_detail(
            kind,
            fecha,
            obra_ids=obra_ids,
        )
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    return jsonify({'success': True, **data})


@jefe_bp.route('/obras_detailed', methods=['GET'], endpoint="obras_detailed")
@login_required
def obras_detailed():
    # 1. Obtener parámetros de la URL
    date_str = request.args.get('selected_date')
    view_mode = request.args.get('view', 'mis')
    
    # 2. LLAMADA AL SERVICIO CENTRALIZADO
    # Esta función ya hace las queries, filtros de seguridad, cálculos de fechas,
    # contadores de libres/ocupados y lógica de timeline.
    context = get_dashboard_data(current_user, date_str, view_mode)
    
    # 3. Añadir configuración específica de la vista de JEFE
    # Sobrescribimos las URLs de navegación para que apunten a este blueprint
    context['prev_month_url'] = url_for('jefe.obras_detailed', selected_date=context['prev_date_str'])
    context['next_month_url'] = url_for('jefe.obras_detailed', selected_date=context['next_date_str'])
    context['view_mode'] = 'jefe' # Para que el HTML oculte botones de Admin
    from app.services.permission_service import can_resolve_fichajes
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes
    context['puede_resolver_auditoria'] = (
        can_resolve_fichajes(current_user) and tenant_muestra_auditoria_fichajes()
    )
    
    # 4. Renderizar pasando todo el diccionario del contexto
    return render_template('obras_detailed_unificado.html', **context)



    

