from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, g
from flask_login import login_required, current_user
from app import db
from datetime import datetime
import json
from sqlalchemy import or_, and_
from app.models import Nota, Obra, User, nota_obra, nota_user, Asignacion
from app.services.permission_service import user_can
from app.services.panel_scope_service import (
    PANEL_PLANIFICADOR,
    apply_obra_scope_filter,
    obra_in_planning_custody,
    planning_acts_as_office,
)

notas_bp = Blueprint('notas', __name__, url_prefix='/notas')


def _can_write_reuniones():
    return user_can(current_user, 'reuniones', 'w')


def _can_delete_reuniones():
    return user_can(current_user, 'reuniones', 'w')


def _puede_eliminar_nota(nota):
    if _can_delete_reuniones() and planning_acts_as_office(current_user):
        return True
    return nota.autor_id == current_user.id and _can_write_reuniones()


def _vision_oficina_notas():
    """Oficina = alcance planificación «todos»."""
    return planning_acts_as_office(current_user)


def _obras_visibles_notas_query():
    return apply_obra_scope_filter(
        Obra.query.filter_by(is_deleted=False),
        current_user,
        PANEL_PLANIFICADOR,
    )


def _puede_ver_nota(nota):
    if nota.autor_id == current_user.id:
        return True
    if nota.es_privada:
        return False
    if current_user in nota.usuarios_implicados:
        return True
    if not nota.obras:
        return False
    if _vision_oficina_notas():
        return True
    if any(obra_in_planning_custody(current_user, o) for o in nota.obras):
        return True
    return any(
        Asignacion.query.filter_by(user_id=current_user.id, obra_id=o.id).first()
        for o in nota.obras
    )


@notas_bp.before_request
def _enforce_notas_module_permissions():
    from app.services.permission_guard import enforce_notas_permissions
    return enforce_notas_permissions()

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
    
    # 3. Condición: La nota es pública y está vinculada a una obra de mi alcance
    if _vision_oficina_notas():
        cond_obra = and_(Nota.es_privada == False, Nota.obras.any())
    else:
        obras_q = _obras_visibles_notas_query()
        obra_ids = [o.id for o in obras_q.all()]
        if obra_ids:
            cond_obra = and_(
                Nota.es_privada == False,
                Nota.obras.any(Obra.id.in_(obra_ids)),
            )
        else:
            # Sin obras en alcance: solo asignaciones propias (lectura)
            obras_asignadas_subquery = (
                db.session.query(Asignacion.obra_id)
                .filter(Asignacion.user_id == current_user.id)
                .subquery()
            )
            cond_obra = and_(
                Nota.es_privada == False,
                Nota.obras.any(Obra.id.in_(obras_asignadas_subquery)),
            )

    # Aplicamos el filtro: Te la muestro si cumples AL MENOS UNA de las 3 condiciones
    notas = Nota.query.filter(
        or_(cond_autor, cond_implicado, cond_obra)
    ).order_by(Nota.fecha.desc()).all()

    obras = _obras_visibles_notas_query().order_by(Obra.nombre).all()
    usuarios = User.query.filter_by(is_deleted=False).order_by(User.name).all()
    
    return render_template('notas/centro_mando.html', notas=notas, obras=obras, usuarios=usuarios)

@notas_bp.route('/crear', methods=['POST'])
@login_required
def crear_nota():
    if not _can_write_reuniones():
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

    if not _puede_ver_nota(nota):
        return jsonify({'success': False, 'message': 'Acceso denegado'}), 403

    sugerencias = {'obras': [], 'personas': []}
    try:
        from app.models import NotaAudioJob
        job = (
            NotaAudioJob.query
            .filter_by(nota_id=nota.id, estado=NotaAudioJob.ESTADO_COMPLETADO)
            .order_by(NotaAudioJob.id.desc())
            .first()
        )
        if job and job.meta_json:
            meta = json.loads(job.meta_json)
            if isinstance(meta, dict):
                raw = meta.get('sugerencias') or {}
                if isinstance(raw, dict):
                    sugerencias = {
                        'obras': raw.get('obras') or [],
                        'personas': raw.get('personas') or [],
                    }
    except Exception:
        pass

    return jsonify({
        'success': True,
        'id': nota.id,
        'titulo': nota.titulo,
        'fecha': nota.fecha.strftime('%Y-%m-%d'),
        'contenido': nota.contenido,
        'es_privada': nota.es_privada,
        'obras_ids': [o.id for o in nota.obras],
        'users_ids': [u.id for u in nota.usuarios_implicados],
        'sugerencias': sugerencias,
    })

@notas_bp.route('/<int:nota_id>/editar', methods=['POST'])
@login_required
def editar_nota(nota_id):
    nota = Nota.query.get_or_404(nota_id)
    
    if not _can_write_reuniones():
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    if not _puede_ver_nota(nota):
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
    from app.models import NotaAudioJob

    nota = Nota.query.get_or_404(nota_id)

    if not _puede_eliminar_nota(nota):
        return jsonify({'success': False, 'message': 'No autorizado para eliminar esta nota'}), 403

    try:
        # Desvincula jobs de audio (por si la FK aún no tiene ON DELETE SET NULL)
        NotaAudioJob.query.filter_by(nota_id=nota.id).update(
            {NotaAudioJob.nota_id: None}, synchronize_session=False,
        )
        db.session.delete(nota)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Nota eliminada correctamente.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@notas_bp.route('/audio/subir', methods=['POST'])
@login_required
def subir_audio_nota():
    if not _can_write_reuniones():
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    archivo = request.files.get('audio')
    if not archivo or not archivo.filename:
        return jsonify({'success': False, 'message': 'No se recibió ningún archivo de audio.'}), 400

    try:
        from app.services.nota_audio_service import (
            save_audio_upload,
            attach_celery_task_id,
            set_user_summary_prompt,
            get_user_summary_prompt,
            set_user_include_transcript,
        )
        from app.celery_worker import process_nota_audio_task

        summary_prompt = (request.form.get('summary_prompt') or '').strip()
        save_default = (request.form.get('save_prompt_default') or '').lower() in (
            '1', 'true', 'yes', 'on',
        )
        include_raw = (request.form.get('include_transcript') or '1').lower()
        include_transcript = include_raw in ('1', 'true', 'yes', 'on')
        if not summary_prompt:
            summary_prompt = get_user_summary_prompt(current_user)
        if save_default:
            set_user_summary_prompt(current_user, summary_prompt)
            set_user_include_transcript(current_user, include_transcript)

        job = save_audio_upload(
            archivo,
            current_user.id,
            summary_prompt=summary_prompt,
            include_transcript=include_transcript,
        )
        tenant = getattr(g, 'current_tenant', None)
        schema_name = getattr(tenant, 'schema_name', None) or 'public'
        async_result = process_nota_audio_task.delay(schema_name, job.id)
        try:
            attach_celery_task_id(job.id, async_result.id)
        except Exception:
            pass

        return jsonify({
            'success': True,
            'job_id': job.id,
            'duracion_segundos': job.duracion_segundos,
            'archivo_nombre': job.archivo_nombre,
            'message': 'Audio recibido. Procesando transcripción…',
        })
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@notas_bp.route('/audio/<int:job_id>/estado', methods=['GET'])
@login_required
def estado_audio_nota(job_id):
    from app.models import NotaAudioJob
    from app.services.nota_audio_service import job_to_status_dict

    job = NotaAudioJob.query.get_or_404(job_id)
    if job.autor_id != current_user.id and not _can_write_reuniones():
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    return jsonify({'success': True, **job_to_status_dict(job)})


@notas_bp.route('/audio/<int:job_id>/cancelar', methods=['POST'])
@login_required
def cancelar_audio_nota(job_id):
    from app.models import NotaAudioJob
    from app.services.nota_audio_service import cancel_audio_job, job_to_status_dict

    job = NotaAudioJob.query.get_or_404(job_id)
    if not _can_write_reuniones():
        return jsonify({'success': False, 'message': 'No autorizado'}), 403
    if job.autor_id != current_user.id and not _can_delete_reuniones():
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    if job.estado in (NotaAudioJob.ESTADO_COMPLETADO,):
        return jsonify({
            'success': False,
            'message': 'La nota ya se creó; no se puede cancelar.',
        }), 400

    try:
        cancel_audio_job(job)
        return jsonify({
            'success': True,
            'message': 'Procesamiento cancelado.',
            **job_to_status_dict(job),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@notas_bp.route('/audio/prompt', methods=['GET', 'POST'])
@login_required
def audio_summary_prompt():
    if not _can_write_reuniones():
        return jsonify({'success': False, 'message': 'No autorizado'}), 403

    from app.services.nota_audio_service import (
        get_default_summary_prompt,
        get_user_summary_prompt,
        set_user_summary_prompt,
        get_user_include_transcript,
        set_user_include_transcript,
        USER_PREF_SUMMARY_PROMPT,
    )

    default_prompt = get_default_summary_prompt()
    if request.method == 'GET':
        prompt = get_user_summary_prompt(current_user)
        prefs = getattr(current_user, 'sidebar_prefs', None) or {}
        is_custom = bool(
            isinstance(prefs, dict) and (prefs.get(USER_PREF_SUMMARY_PROMPT) or '').strip()
        )
        return jsonify({
            'success': True,
            'prompt': prompt,
            'default_prompt': default_prompt,
            'is_custom': is_custom,
            'include_transcript': get_user_include_transcript(current_user),
        })

    data = request.get_json(silent=True) or {}
    reset = bool(data.get('reset'))
    try:
        if reset:
            prompt = set_user_summary_prompt(current_user, None)
            is_custom = False
            include_transcript = get_user_include_transcript(current_user)
            if 'include_transcript' in data:
                include_transcript = set_user_include_transcript(
                    current_user, bool(data.get('include_transcript')),
                )
        else:
            prompt = set_user_summary_prompt(
                current_user, (data.get('prompt') or '').strip() or None,
            )
            prefs = getattr(current_user, 'sidebar_prefs', None) or {}
            is_custom = bool(
                isinstance(prefs, dict) and (prefs.get(USER_PREF_SUMMARY_PROMPT) or '').strip()
            )
            if 'include_transcript' in data:
                include_transcript = set_user_include_transcript(
                    current_user, bool(data.get('include_transcript')),
                )
            else:
                include_transcript = get_user_include_transcript(current_user)
        return jsonify({
            'success': True,
            'prompt': prompt,
            'default_prompt': default_prompt,
            'is_custom': is_custom,
            'include_transcript': include_transcript,
            'message': 'Prompt guardado.',
        })
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@notas_bp.route('/audio/activos', methods=['GET'])
@login_required
def audio_jobs_activos():
    """Jobs de audio del usuario aún en cola o procesando (para retomar al volver)."""
    from app.models import NotaAudioJob
    from app.services.nota_audio_service import job_to_status_dict, sweep_stale_audio_jobs

    if not _can_write_reuniones():
        return jsonify({'success': True, 'jobs': []})

    # Limpia zombies (p.ej. worker caído ayer) para que no bloqueen la UI.
    try:
        sweep_stale_audio_jobs(current_user.id)
    except Exception:
        db.session.rollback()

    jobs = (
        NotaAudioJob.query
        .filter(
            NotaAudioJob.autor_id == current_user.id,
            NotaAudioJob.estado.in_([
                NotaAudioJob.ESTADO_PENDIENTE,
                NotaAudioJob.ESTADO_PROCESANDO,
            ]),
        )
        .order_by(NotaAudioJob.id.desc())
        .limit(10)
        .all()
    )
    return jsonify({
        'success': True,
        'jobs': [job_to_status_dict(j) for j in jobs],
    })
