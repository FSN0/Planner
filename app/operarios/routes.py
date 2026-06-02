from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from app.models import Document, ROLE_OPERARIO, Asignacion, Obra
from app import db
import os
from datetime import timedelta, datetime
from app.decorators import roles_required

operarios_bp = Blueprint('operarios', __name__, url_prefix='/operario')

@operarios_bp.route('/panel', methods=['GET'])
@login_required
@roles_required(ROLE_OPERARIO)
def panel():
    # Solo renderizamos el dashboard, sin lógica de documentos
    return render_template('operario_dashboard.html')

@operarios_bp.route('/calendar')
@login_required
def calendar():
    # El HTML ya se encarga de llamar por JS a la API Universal
    selected_date = request.args.get('selected_date', datetime.today().strftime('%Y-%m-%d'))
    return render_template('operario_calendar.html', worker=current_user, selected_date=selected_date)