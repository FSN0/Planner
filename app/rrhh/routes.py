# app/rrhh/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import login_required
from app.models import User, ROLE_RRHH, ROLE_OPERARIO
from app import db
import os, zipfile, io

from app.decorators import roles_required

rrhh_bp = Blueprint('rrhh', __name__, url_prefix='/rrhh')

@rrhh_bp.route('/panel')
@login_required
@roles_required(ROLE_RRHH)
def panel():
    active_count = User.query.filter_by(role=ROLE_OPERARIO, active=True, is_deleted=False).count()
    pending_count = User.query.filter_by(role=ROLE_OPERARIO, active=False, is_deleted=False).count()
    return render_template('rrhh_panel.html', active_count=active_count, pending_count=pending_count)

@rrhh_bp.route('/approve/<int:user_id>', methods=['POST'])
@login_required
@roles_required(ROLE_RRHH)
def approve(user_id):
    user = User.query.get(user_id)
    if user and user.role == ROLE_OPERARIO:
        user.active = True
        db.session.commit()
        flash("Trabajador aprobado y activado", "success")
    else:
        flash("Usuario no encontrado o rol inválido", "danger")
    return redirect(request.referrer or url_for('admin.personal'))

@rrhh_bp.route('/deactivate/<int:user_id>', methods=['POST'])
@login_required
@roles_required(ROLE_RRHH)
def deactivate(user_id):
    user = User.query.get(user_id)
    if user and user.role == ROLE_OPERARIO:
        user.active = False
        db.session.commit()
        flash("Trabajador desactivado", "success")
    else:
        flash("Usuario no encontrado o rol inválido", "danger")
    return redirect(request.referrer or url_for('admin.personal'))



@rrhh_bp.route('/gestion_personal', methods=['GET'])
@login_required
@roles_required(ROLE_RRHH)
def gestion_personal():
    return redirect(url_for('admin.personal', **request.args))
