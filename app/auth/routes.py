# app/auth/routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, g,session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, ROLE_OPERARIO, Company
from app import db
from sqlalchemy.exc import IntegrityError
from datetime import date

# ¡AQUÍ ESTÁ LA CLAVE! Se define aquí, no se importa de fuera.
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # 1. Si el usuario ya está autenticado, redirige a su panel
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin.panel'))
        elif current_user.role == 'jefe_obra':
            return redirect(url_for('jefe.obras_detailed', selected_date=date.today()))
        elif current_user.role == 'rrhh':
            return redirect(url_for('rrhh.panel'))
        else:
            return redirect(url_for('operarios.panel')) 
            
    # 2. SEGURIDAD SAAS: Si no hay tenant en la URL, lo bloqueamos
    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash("Por favor, accede desde la URL específica de tu empresa.", "warning")
        return redirect('/superadmin/')
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') == 'on' else False

        # 3. Busca al usuario SOLO dentro de la base de datos de esta empresa (Tenant)
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
            session['tenant_id'] = g.current_tenant.id
            from app.utils import register_log
            register_log(
                user_id=user.id,
                category='accesos',
                action='Inicio de Sesión',
                detail=f"Login exitoso desde IP: {request.remote_addr or 'Desconocida'}"
            )
            flash("Inicio de sesión exitoso", "success")
            
            # Redirección inteligente según rol
            if user.role == 'admin':
                return redirect(url_for('admin.panel'))
            elif user.role == 'jefe_obra':
                # CAMBIO AQUÍ TAMBIÉN
                return redirect(url_for('jefe.obras_detailed', selected_date=date.today()))
            elif user.role == 'rrhh':
                return redirect(url_for('rrhh.panel'))
            else:
                return redirect(url_for('operarios.panel'))
        else:
            if user: # Solo grabamos log si el email existe pero la contraseña falló
                from app.utils import register_log
                register_log(
                    user_id=user.id,
                    category='accesos',
                    action='Intento fallido de login',
                    detail=f"Contraseña incorrecta. IP: {request.remote_addr or 'Desconocida'}"
                )
            # --------------------------------------------
            flash("Credenciales inválidas", "danger")
            
    return render_template('login.html', tenant_name=g.current_tenant.nombre)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada", "info")
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # SEGURIDAD SAAS: No pueden registrarse sin estar en el subdominio de una empresa
    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash("Accede desde la URL de tu empresa para registrarte.", "warning")
        return redirect('http://localhost:5000/superadmin/')

    if request.method == 'POST':
        name = request.form.get('name')
        lastname = request.form.get('lastname')
        dni = request.form.get('dni')
        email = request.form.get('email')
        password = request.form.get('password')
        company_code_input = request.form.get('company_code')
        
        # Verificar que el código de empresa exista dentro del esquema de ESTE tenant
        company = Company.query.filter_by(code=company_code_input).first()
        if not company:
            flash("El código de empresa (subcontrata) no es válido.", "danger")
            return redirect(url_for('auth.register'))
            
        new_user = User(
            email=email,
            password_hash=generate_password_hash(password),
            role=ROLE_OPERARIO,
            name=name,
            lastname=lastname,
            dni=dni,
            company_id=company.id,
            active=False
        )
        db.session.add(new_user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Ya existe un usuario con ese email o DNI.", "danger")
            return redirect(url_for('auth.register'))
            
        flash("Registro exitoso, espera aprobación de RRHH", "success")
        return redirect(url_for('auth.login'))
        
    return render_template('register.html', tenant_name=g.current_tenant.nombre)