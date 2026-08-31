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
    if current_user.role not in [ROLE_JEFE, ROLE_ADMIN]:
        flash("Acceso no autorizado", "danger")
        return redirect(url_for('main.dashboard'))

    from app.services.panel_service import get_jefe_panel_context
    from app.services.permission_service import can_resolve_fichajes
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes
    ctx = get_jefe_panel_context(current_user)
    ctx['puede_resolver_auditoria'] = (
        can_resolve_fichajes(current_user) and tenant_muestra_auditoria_fichajes()
    )
    return render_template('jefe_panel.html', **ctx)


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



    

