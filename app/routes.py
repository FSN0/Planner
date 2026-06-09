# app/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.utils.timezone_utils import is_valid_timezone, get_app_timezone, timezone_label

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def dashboard():
    # Dashboard general que redirige a vistas específicas según el rol del usuario.
    if current_user.role == 'operario':
        return render_template('operario_dashboard.html')
    elif current_user.role == 'jefe_obra':
        return redirect(url_for('jefe.obras_detailed', selected_date=""))
    elif current_user.role == 'admin':
        # Redirige a la ruta que calcula y envía los conteos correctos
        return redirect(url_for('admin.panel'))
    elif current_user.role == 'rrhh':
        return render_template('rrhh_panel.html')
    else:
        return render_template('login.html')


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

