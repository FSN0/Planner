# app/auth/routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, ROLE_OPERARIO, ROLE_RRHH
from datetime import date

auth_bp = Blueprint('auth', __name__)

LOGIN_BLOCKED_ROLES = (ROLE_OPERARIO, ROLE_RRHH)


def _redirect_authenticated_user():
    if current_user.role == 'admin':
        return redirect(url_for('admin.panel'))
    if current_user.role == 'jefe_obra':
        return redirect(url_for('jefe.obras_detailed', selected_date=date.today()))
    logout_user()
    flash('Tu perfil no tiene acceso a la aplicación.', 'warning')
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return _redirect_authenticated_user()

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') == 'on' else False

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            if user.role in LOGIN_BLOCKED_ROLES:
                from app.utils import register_log
                register_log(
                    user_id=user.id,
                    category='accesos',
                    action='Acceso denegado',
                    detail=f"Intento de login con rol sin acceso ({user.role}). IP: {request.remote_addr or 'Desconocida'}"
                )
                flash('Tu perfil no tiene acceso a la aplicación. Contacta con administración.', 'warning')
                return render_template('login.html')

            login_user(user, remember=remember)
            from app.utils import register_log
            register_log(
                user_id=user.id,
                category='accesos',
                action='Inicio de Sesión',
                detail=f"Login exitoso desde IP: {request.remote_addr or 'Desconocida'}"
            )
            flash("Inicio de sesión exitoso", "success")

            if user.role == 'admin':
                return redirect(url_for('admin.panel'))
            if user.role == 'jefe_obra':
                return redirect(url_for('jefe.obras_detailed', selected_date=date.today()))

            logout_user()
            flash('Tu perfil no tiene acceso a la aplicación.', 'warning')
            return render_template('login.html')

        if user:
            from app.utils import register_log
            register_log(
                user_id=user.id,
                category='accesos',
                action='Intento fallido de login',
                detail=f"Contraseña incorrecta. IP: {request.remote_addr or 'Desconocida'}"
            )
        flash("Credenciales inválidas", "danger")

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada", "info")
    return redirect(url_for('auth.login'))
