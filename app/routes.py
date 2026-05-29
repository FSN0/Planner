# app/routes.py
from flask import Blueprint, render_template
from flask_login import login_required, current_user
from flask import render_template, redirect, url_for
from flask import Blueprint, request, jsonify, current_app
from app import db

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def dashboard():
    # Dashboard general que redirige a vistas específicas según el rol del usuario.
    if current_user.role == 'currante':
        return render_template('currante_dashboard.html')
    elif current_user.role == 'jefe_obra':
        return redirect(url_for('jefe.obras_detailed', selected_date=""))
    elif current_user.role == 'admin':
        # Redirige a la ruta que calcula y envía los conteos correctos
        return redirect(url_for('admin.panel'))
    elif current_user.role == 'rrhh':
        return render_template('rrhh_panel.html')
    else:
        return render_template('login.html')

