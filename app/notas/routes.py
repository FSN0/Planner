from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from datetime import datetime
from sqlalchemy import or_, and_
from app.models import Nota, Obra, User, nota_obra, nota_user, Asignacion, ROLE_ADMIN, ROLE_JEFE

notas_bp = Blueprint('notas', __name__, url_prefix='/notas')

@notas_bp.route('/', methods=['GET'])
@login_required
def centro_mando():
    # 1. Condición base: Siempre veo las notas donde yo soy el autor
    cond_autor = Nota.autor_id == current_user.id
    
    # 2. Condición: La nota es pública y me han etiquetado explícitamente a mí
    cond_implicado = and_(
        Nota.es_privada == False,
        Nota.usuarios_implicados.any(User.id == current_user.id)
    )
    
    # 3. Condición: La nota es pública y está vinculada a una obra a la que pertenezco
    if current_user.role == ROLE_ADMIN:
        # Los admins gestionan todo: ven las notas de todas las obras
        # (Pero si la nota NO tiene obras ni implicados, .any() es False -> privada a efectos prácticos)
        cond_obra = and_(Nota.es_privada == False, Nota.obras.any())
        
    elif current_user.role == ROLE_JEFE:
        # Los jefes solo ven las notas de las obras de las que son responsables
        cond_obra = and_(
            Nota.es_privada == False,
            Nota.obras.any(or_(Obra.jefe_obra_id == current_user.id, Obra.encargado_id == current_user.id))
        )
    else:
        # Operarios y RRHH ven las notas de las obras donde han sido asignados alguna vez
        obras_asignadas_subquery = db.session.query(Asignacion.obra_id).filter(Asignacion.user_id == current_user.id).subquery()
        cond_obra = and_(
            Nota.es_privada == False,
            Nota.obras.any(Obra.id.in_(obras_asignadas_subquery))
        )

    # Aplicamos el filtro: Te la muestro si cumples AL MENOS UNA de las 3 condiciones
    notas = Nota.query.filter(
        or_(cond_autor, cond_implicado, cond_obra)
    ).order_by(Nota.fecha.desc()).all()

    obras = Obra.query.filter_by(is_deleted=False).order_by(Obra.nombre).all()
    usuarios = User.query.filter_by(is_deleted=False).order_by(User.name).all()

    return render_template('notas/centro_mando.html', notas=notas, obras=obras, usuarios=usuarios)

@notas_bp.route('/crear', methods=['POST'])
@login_required
def crear_nota():
    if current_user.role not in [ROLE_ADMIN, ROLE_JEFE]:
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    try:
        titulo = request.form.get('titulo')
        contenido = request.form.get('contenido')
        fecha_str = request.form.get('fecha')
        
        # Validación robusta de privacidad
        val_privacidad = str(request.form.get('es_privada')).lower()
        es_privada = val_privacidad in ['true', 'on', '1', 'yes']
        
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
    
    # --- LÓGICA DE ACCESO RESTRINGIDO (Aplica las mismas reglas que el panel) ---
    tiene_acceso = False
    
    if nota.autor_id == current_user.id:
        tiene_acceso = True
    elif not nota.es_privada:
        if current_user in nota.usuarios_implicados:
            tiene_acceso = True
        elif nota.obras:
            if current_user.role == ROLE_ADMIN:
                tiene_acceso = True
            elif current_user.role == ROLE_JEFE:
                for obra in nota.obras:
                    if obra.jefe_obra_id == current_user.id or obra.encargado_id == current_user.id:
                        tiene_acceso = True
                        break
            else:
                for obra in nota.obras:
                    if Asignacion.query.filter_by(user_id=current_user.id, obra_id=obra.id).first():
                        tiene_acceso = True
                        break
                        
    if not tiene_acceso:
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
    
    if current_user.role not in [ROLE_ADMIN, ROLE_JEFE]:
        return jsonify({'success': False, 'message': 'No autorizado'}), 403
        
    # --- BLOQUEO DE EDICIÓN CON LAS MISMAS REGLAS DE PRIVACIDAD ---
    tiene_acceso = False
    if nota.autor_id == current_user.id:
        tiene_acceso = True
    elif not nota.es_privada:
        if current_user in nota.usuarios_implicados:
            tiene_acceso = True
        elif nota.obras:
            if current_user.role == ROLE_ADMIN:
                tiene_acceso = True
            elif current_user.role == ROLE_JEFE:
                for obra in nota.obras:
                    if obra.jefe_obra_id == current_user.id or obra.encargado_id == current_user.id:
                        tiene_acceso = True
                        break
                        
    if not tiene_acceso:
        return jsonify({'success': False, 'message': 'No autorizado para editar esta nota'}), 403

    try:
        nota.titulo = request.form.get('titulo')
        nota.contenido = request.form.get('contenido')
        fecha_str = request.form.get('fecha')
        
        # Validación robusta de privacidad al editar (arregla el error silencioso)
        val_privacidad = str(request.form.get('es_privada')).lower()
        nota.es_privada = val_privacidad in ['true', 'on', '1', 'yes']
        
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
    
    
@notas_bp.route('/<int:nota_id>/eliminar', methods=['POST'])
@login_required
def eliminar_nota(nota_id):
    nota = Nota.query.get_or_404(nota_id)
    
    # Seguridad: Solo puede borrar la nota quien la creó (o un admin supremo)
    if nota.autor_id != current_user.id and current_user.role != ROLE_ADMIN:
        return jsonify({'success': False, 'message': 'No autorizado para eliminar esta nota'}), 403

    try:
        db.session.delete(nota)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Nota eliminada correctamente.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500