# app/auth/routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, ROLE_OPERARIO, Company
from app import db
from sqlalchemy.exc import IntegrityError
from datetime import date

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Si el usuario ya está autenticado, redirige a su panel
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin.panel'))
        elif current_user.role == 'jefe_obra':
            # CAMBIO AQUÍ: Redirigir a obras_detailed con fecha
            return redirect(url_for('jefe.obras_detailed', selected_date=date.today()))
        elif current_user.role == 'rrhh':
            return redirect(url_for('rrhh.panel'))
        else:
            return redirect(url_for('operarios.panel')) 
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') == 'on' else False

        user = User.query.filter_by(email=email).first()
        
        # Nota: Asumo que usas check_password_hash porque así estaba en tu snippet
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
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
            flash("Credenciales inválidas", "danger")
            
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada", "info")
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        lastname = request.form.get('lastname')
        dni = request.form.get('dni')
        email = request.form.get('email')
        password = request.form.get('password')
        company_code_input = request.form.get('company_code')
        
        # Verificar que el código de empresa exista
        company = Company.query.filter_by(code=company_code_input).first()
        if not company:
            flash("El código de empresa no es válido.", "danger")
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
    return render_template('register.html')