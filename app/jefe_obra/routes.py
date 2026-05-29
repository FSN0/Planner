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


@jefe_bp.route('/panel', methods=['GET'])
@login_required
def panel():
    if current_user.role not in [ROLE_JEFE, ROLE_ADMIN]:
        flash("Acceso no autorizado", "danger")
        return redirect(url_for('main.dashboard'))

    obras = Obra.query.filter_by(jefe_obra_id=current_user.id).all()
    return render_template('jefe_panel.html', obras=obras)


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
    
    # 4. Renderizar pasando todo el diccionario del contexto
    return render_template('obras_detailed_unificado.html', **context)



    

