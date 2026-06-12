# app/routes.py
from flask import Blueprint, redirect, url_for, request, flash, g
from flask_login import login_required, current_user, logout_user
from app import db
from app.models import ROLE_OPERARIO, ROLE_RRHH
from app.utils.timezone_utils import is_valid_timezone, get_app_timezone, timezone_label
from app.services.tenant_domain_service import is_marketing_host, normalize_host
from app.marketing.routes import render_landing

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def dashboard():
    if is_marketing_host(normalize_host(request.host)):
        return render_landing()

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        return redirect(url_for('superadmin.dashboard'))

    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))

    if current_user.role == 'jefe_obra':
        return redirect(url_for('jefe.panel'))
    if current_user.role == 'admin':
        return redirect(url_for('admin.panel'))
    if current_user.role in (ROLE_OPERARIO, ROLE_RRHH):
        logout_user()
        flash('Tu perfil no tiene acceso a la aplicación.', 'warning')
        return redirect(url_for('auth.login'))
    return redirect(url_for('auth.login'))


@main_bp.route('/preferencias/zona-horaria', methods=['POST'])
@login_required
def update_user_timezone():
    tz = (request.form.get('timezone') or '').strip()
    if not tz or not is_valid_timezone(tz):
        flash('Zona horaria no válida.', 'danger')
        return redirect(request.referrer or url_for('main.dashboard'))

    current_user.timezone = tz
    db.session.commit()
    flash(f'Zona horaria actualizada: {timezone_label(tz)}', 'success')
    return redirect(request.referrer or url_for('main.dashboard'))
