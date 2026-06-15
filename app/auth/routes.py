# app/auth/routes.py

from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

from app import db, limiter
from app.models import User, ROLE_OPERARIO, ROLE_RRHH, Company
from app.services.tenant_domain_service import is_marketing_host, normalize_host

auth_bp = Blueprint('auth', __name__)

LOGIN_BLOCKED_ROLES = (ROLE_OPERARIO, ROLE_RRHH)


def _login_page_context():
    from app.services.hub_sso_service import hub_sso_enabled_for_tenant, hub_url
    tenant = g.current_tenant
    return {
        'tenant_name': tenant.nombre,
        'hub_sso_enabled': hub_sso_enabled_for_tenant(tenant),
        'hub_url': hub_url(),
    }


def _redirect_authenticated_user():
    if current_user.role == 'admin':
        return redirect(url_for('admin.panel'))
    if current_user.role == 'jefe_obra':
        return redirect(url_for('jefe.obras_detailed', selected_date=date.today()))
    logout_user()
    flash('Tu perfil no tiene acceso a la aplicación.', 'warning')
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 50 per hour', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return _redirect_authenticated_user()

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        host = normalize_host(request.host)
        if is_marketing_host(host):
            flash('Accede desde la URL de tu empresa, por ejemplo tuempresa.signaplan.com', 'info')
            return redirect(url_for('main.dashboard'))
        if host == 'localhost':
            return redirect(url_for('superadmin.dashboard'))
        flash('Por favor, accede desde la URL específica de tu empresa.', 'warning')
        return redirect(url_for('main.dashboard'))

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
                    detail=(
                        f"Intento de login con rol sin acceso ({user.role}). "
                        f"IP: {request.remote_addr or 'Desconocida'}"
                    ),
                )
                flash(
                    'Tu perfil no tiene acceso a la aplicación. Contacta con administración.',
                    'warning',
                )
                return render_template('login.html', **_login_page_context())

            if not user.is_active:
                flash('Tu cuenta aún no está activa. Espera la aprobación de RRHH.', 'warning')
                return render_template('login.html', **_login_page_context())

            login_user(user, remember=remember)
            session['tenant_id'] = g.current_tenant.id
            from app.utils import register_log
            register_log(
                user_id=user.id,
                category='accesos',
                action='Inicio de Sesión',
                detail=f"Login exitoso desde IP: {request.remote_addr or 'Desconocida'}",
            )
            flash('Inicio de sesión exitoso', 'success')

            if user.role == 'admin':
                return redirect(url_for('admin.panel'))
            if user.role == 'jefe_obra':
                return redirect(url_for('jefe.obras_detailed', selected_date=date.today()))

            logout_user()
            flash('Tu perfil no tiene acceso a la aplicación.', 'warning')
            return render_template('login.html', **_login_page_context())

        if user:
            from app.utils import register_log
            register_log(
                user_id=user.id,
                category='accesos',
                action='Intento fallido de login',
                detail=f"Contraseña incorrecta. IP: {request.remote_addr or 'Desconocida'}",
            )
        flash('Credenciales inválidas', 'danger')

    return render_template('login.html', **_login_page_context())


@auth_bp.route('/logout')
@login_required
def logout():
    from app.services.hub_sso_service import (
        clear_hub_authentik_uid,
        hub_sso_enabled_for_tenant,
        mark_hub_sso_skip_auto,
    )

    tenant = getattr(g, 'current_tenant', None)
    if tenant and hub_sso_enabled_for_tenant(tenant):
        mark_hub_sso_skip_auto()
        clear_hub_authentik_uid()

    logout_user()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('auth.login', local=1))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash('Accede desde la URL de tu empresa para registrarte.', 'warning')
        return redirect('http://localhost/superadmin/')

    if request.method == 'POST':
        name = request.form.get('name')
        lastname = request.form.get('lastname')
        dni = request.form.get('dni')
        email = request.form.get('email')
        password = request.form.get('password')
        company_code_input = request.form.get('company_code')

        company = Company.query.filter_by(code=company_code_input).first()
        if not company:
            flash('El código de empresa (subcontrata) no es válido.', 'danger')
            return redirect(url_for('auth.register'))

        new_user = User(
            email=email,
            password_hash=generate_password_hash(password),
            role=ROLE_OPERARIO,
            name=name,
            lastname=lastname,
            dni=dni,
            company_id=company.id,
            active=False,
        )
        db.session.add(new_user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Ya existe un usuario con ese email o DNI.', 'danger')
            return redirect(url_for('auth.register'))

        flash('Registro exitoso, espera aprobación de RRHH', 'success')
        return redirect(url_for('auth.login'))

    return render_template('register.html', tenant_name=g.current_tenant.nombre)
