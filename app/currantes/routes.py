from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from app.models import Document, ROLE_CURRANTE, Asignacion, Obra
from app import db
import os
from datetime import timedelta, datetime
from app.decorators import roles_required

currantes_bp = Blueprint('currantes', __name__, url_prefix='/currante')

@currantes_bp.route('/panel', methods=['GET'])
@login_required
@roles_required(ROLE_CURRANTE)
def panel():
    # Solo renderizamos el dashboard, sin lógica de documentos
    return render_template('currante_dashboard.html')

@currantes_bp.route('/calendar')
@login_required
def calendar():
    # El HTML ya se encarga de llamar por JS a la API Universal
    selected_date = request.args.get('selected_date', datetime.today().strftime('%Y-%m-%d'))
    return render_template('currante_calendar.html', worker=current_user, selected_date=selected_date)