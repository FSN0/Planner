from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import Nota, Obra, User, ROLE_ADMIN, ROLE_JEFE
from app import db
from datetime import datetime
from sqlalchemy import or_

notas_bp = Blueprint('notas', __name__, url_prefix='/notas')

@notas_bp.route('/', methods=['GET'])
@login_required
def centro_mando():
    if current_user.role not in [ROLE_ADMIN, ROLE_JEFE]:
        flash("Acceso denegado.", "danger")
        return redirect(url_for('main.dashboard'))

    # Lógica de Privacidad: Vemos las públicas + las privadas donde YO soy el autor
    query = Nota.query.filter(
        or_(
            Nota.es_privada == False,
            Nota.autor_id == current_user.id
        )
    ).order_by(Nota.fecha.desc(), Nota.created_at.desc())
    
    notas = query.all()
    
    # Listas para el modal de nueva nota
    todas_obras = Obra.query.filter_by(is_deleted=False).order_by(Obra.nombre).all()
    todos_usuarios = User.query.filter_by(is_deleted=False).order_by(User.name).all()

    return render_template('notas/centro_mando.html', 
                           notas=notas, 
                           obras=todas_obras, 
                           usuarios=todos_usuarios)

@notas_bp.route('/crear', methods=['POST'])
@login_required
def crear_nota():
    if current_user.role not in [ROLE_ADMIN, ROLE_JEFE]:
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    try:
        titulo = request.form.get('titulo')
        contenido = request.form.get('contenido')
        fecha_str = request.form.get('fecha')
        es_privada = True if request.form.get('es_privada') == 'true' else False
        
        # Arrays desde select2 múltiple
        obras_ids = request.form.getlist('obras_ids[]')
        users_ids = request.form.getlist('users_ids[]')

        fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date() if fecha_str else datetime.today().date()

        nueva_nota = Nota(
            titulo=titulo,
            contenido=contenido,
            fecha=fecha_obj,
            es_privada=es_privada,
            autor_id=current_user.id
        )

        if obras_ids:
            obras_rel = Obra.query.filter(Obra.id.in_(obras_ids)).all()
            nueva_nota.obras.extend(obras_rel)
            
        if users_ids:
            users_rel = User.query.filter(User.id.in_(users_ids)).all()
            nueva_nota.usuarios_implicados.extend(users_rel)

        db.session.add(nueva_nota)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Nota guardada correctamente.'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
@notas_bp.route('/<int:nota_id>/datos', methods=['GET'])
@login_required
def obtener_nota(nota_id):
    nota = Nota.query.get_or_404(nota_id)
    
    # Seguridad: Si es privada y no es suya, bloqueo
    if nota.es_privada and nota.autor_id != current_user.id:
        return jsonify({'success': False, 'message': 'Acceso denegado'}), 403

    return jsonify({
        'success': True,
        'id': nota.id,
        'titulo': nota.titulo,
        'fecha': nota.fecha.strftime('%Y-%m-%d'),
        'contenido': nota.contenido,
        'es_privada': nota.es_privada,
        'obras_ids': [o.id for o in nota.obras],
        'users_ids': [u.id for u in nota.usuarios_implicados]
    })

@notas_bp.route('/<int:nota_id>/editar', methods=['POST'])
@login_required
def editar_nota(nota_id):
    nota = Nota.query.get_or_404(nota_id)
    
    if current_user.role not in [ROLE_ADMIN, ROLE_JEFE] or (nota.es_privada and nota.autor_id != current_user.id):
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    try:
        nota.titulo = request.form.get('titulo')
        nota.contenido = request.form.get('contenido')
        fecha_str = request.form.get('fecha')
        nota.es_privada = True if request.form.get('es_privada') == 'true' else False
        
        if fecha_str:
            nota.fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()

        # Actualizar relaciones (limpiar las viejas y poner las nuevas)
        obras_ids = request.form.getlist('obras_ids[]')
        users_ids = request.form.getlist('users_ids[]')

        nota.obras = Obra.query.filter(Obra.id.in_(obras_ids)).all() if obras_ids else []
        nota.usuarios_implicados = User.query.filter(User.id.in_(users_ids)).all() if users_ids else []

        db.session.commit()
        return jsonify({'success': True, 'message': 'Nota actualizada correctamente.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500