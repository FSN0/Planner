from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from datetime import datetime
from app import db
from app.models import Obra, User, Company, SyncLog, Asignacion, RegistroFichaje, ROLE_ADMIN
from app.services.sync_service import OdooSyncService
from app.services.core_assignment_service import CoreAssignmentService
from app.services.sync_dashboard_service import get_sync_panel_context, test_odoo_connection
from app.services.sync_config_service import SyncConfigService
from app.decorators import roles_required
from sqlalchemy import or_

sync_bp = Blueprint('sync', __name__, url_prefix='/sync')

@sync_bp.route('/')
@login_required
@roles_required(ROLE_ADMIN)
def panel():
    ctx = get_sync_panel_context()
    return render_template('sync/panel.html', **ctx)


@sync_bp.route('/api/test-connection', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def api_test_connection():
    return jsonify(test_odoo_connection())


@sync_bp.route('/api/config', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def api_save_config():
    data = request.get_json() or {}
    try:
        SyncConfigService.save_config(data)
        return jsonify({'success': True, 'message': 'Configuración guardada.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@sync_bp.route('/api/run/<task_name>', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def api_run_sync(task_name):
    labels = {
        'obras': 'obras',
        'empleados': 'empleados internos',
        'subcontratas': 'subcontratas',
        'fichajes': 'fichajes del día',
        'fichajes-retro': 'fichajes retrospectivos',
    }
    if task_name not in labels:
        return jsonify({'success': False, 'message': 'Módulo desconocido'}), 400
    try:
        from app.celery_worker import (
            auto_sync_obras, auto_sync_empleados, auto_sync_subcontratas,
            fichajes_en_vivo, fichajes_retroactivos,
        )
        tasks = {
            'obras': auto_sync_obras,
            'empleados': auto_sync_empleados,
            'subcontratas': auto_sync_subcontratas,
            'fichajes': fichajes_en_vivo,
            'fichajes-retro': fichajes_retroactivos,
        }
        tasks[task_name].delay()
        return jsonify({
            'success': True,
            'message': f'Sincronización automática de {labels[task_name]} lanzada en segundo plano.',
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@sync_bp.route('/resolve_conflict_empleado', methods=['POST'])
@login_required
def resolve_conflict_empleado():
    data = request.json
    emp_data = data['emp']
    action = data['action'] 
    
    try:
        actual_user = User.query.get(emp_data['conflicto']['actual']['id'])
        blocker_user = User.query.get(emp_data['conflicto']['bloqueador']['id'])
        
        # Función auxiliar para retirar al perdedor
        def retirar_usuario(u):
            u.active = False
            u.is_deleted = True
            u.dni = f"DEL-{u.id}"
            if u.email: 
                u.email = f"del-{u.id}@borrado.local"
            # OJO: Quitamos también el odoo_id por si acaso estaba pisado
            u.odoo_id = None 
            
        if action == 'keep_actual':
            retirar_usuario(blocker_user)
            db.session.flush() # <--- ESTA ES LA CLAVE: Fuerza a la BD a liberar el DNI/Email ahora mismo
            
            actual_user.odoo_id = emp_data['odoo_id']
            actual_user.name = emp_data['name']
            actual_user.lastname = emp_data['lastname']
            actual_user.dni = emp_data['dni']
            actual_user.email = emp_data['email']
            actual_user.role = emp_data['role']
            
        elif action == 'keep_blocker':
            retirar_usuario(actual_user)
            db.session.flush() # <--- Y AQUÍ TAMBIÉN
            
            blocker_user.odoo_id = emp_data['odoo_id']
            blocker_user.name = emp_data['name']
            blocker_user.lastname = emp_data['lastname']
            blocker_user.dni = emp_data['dni']
            blocker_user.email = emp_data['email']
            blocker_user.role = emp_data['role']
            
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@sync_bp.route('/preview_obras', methods=['GET'])
@login_required
@roles_required(ROLE_ADMIN)
def preview_obras():
    try:
        from app.services.sync_preview_service import analyze_obras_preview
        service = OdooSyncService()
        diff = service.get_diff_obras()
        preview = analyze_obras_preview(diff)
        jefes_locales = User.query.filter(User.role.in_(['jefe_obra', 'admin'])).all()
        encargados_locales = User.query.filter_by(active=True).all()
        return render_template(
            'sync/preview_obras.html',
            diff=diff, preview=preview,
            jefes=jefes_locales, encargados=encargados_locales,
        )
    except Exception as e:
        flash(f"Error Odoo: {str(e)}", "danger")
        return redirect(url_for('sync.panel'))

@sync_bp.route('/commit_obras', methods=['POST'])
@login_required
def commit_obras():
    data = request.json
    from app.utils.timezone_utils import utc_now
    ahora = utc_now()
    
    try:
        # 1. Procesar Nuevas
        for obj in data.get('nuevas', []):
            fecha = datetime.strptime(obj['fecha_inicio'], "%Y-%m-%d").date() if obj.get('fecha_inicio') else None
            
            nueva_obra = Obra(
                odoo_id=obj['odoo_id'],
                codigo=obj['codigo'],
                nombre=obj['nombre'],
                descripcion=obj.get('cliente', ''),
                fecha_inicio=fecha,
                estado='Pendiente', 
                jefe_obra_id=obj.get('jefe_obra_id'),
                encargado_id=obj.get('encargado_id'),
                fecha_importacion=ahora  # <--- GUARDAMOS LA FECHA AQUÍ
            )
            db.session.add(nueva_obra)
            from app.utils import register_log
            register_log(
                user_id=current_user.id,
                category='obras',
                action='Crear Obra (Sincronización)',
                detail=f"Obra importada desde Odoo: '{obj['nombre']}' (Código: {obj['codigo']})"
            )
            
        # 2. Procesar Actualizadas
        for obj in data.get('actualizadas', []):
            obra = Obra.query.get(obj['local_id'])
            if obra:
                obra.odoo_id = obj['odoo_id']
                obra.codigo = obj['codigo']
                obra.nombre = obj['nombre']
                obra.descripcion = obj.get('cliente', '')
                obra.fecha_importacion = ahora  # <--- ACTUALIZAMOS LA FECHA AQUÍ
                if obj.get('fecha_inicio'):
                    obra.fecha_inicio = datetime.strptime(obj['fecha_inicio'], "%Y-%m-%d").date()
                if obj.get('jefe_obra_id'):
                    obra.jefe_obra_id = obj['jefe_obra_id']
                if obj.get('encargado_id'):
                    obra.encargado_id = obj['encargado_id']
                    
        # 3. Procesar Finalizadas automáticamente
        for obj in data.get('finalizadas', []):
            obra = Obra.query.get(obj['local_id'])
            if obra:
                obra.estado = 'Finalizada'
                obra.fecha_fin = ahora.date() 
                obra.fecha_importacion = ahora  # <--- ACTUALIZAMOS LA FECHA AQUÍ
                
        # --- AÑADIR REGISTRO DE HISTORIAL ---
        db.session.add(SyncLog(
            fecha=ahora,
            tipo='Obras',
            modo='Manual',
            nuevos=len(data.get('nuevas', [])),
            actualizados=len(data.get('actualizadas', [])),
            finalizados=len(data.get('finalizadas', [])),
            errores=data.get('errores', 0),
            detalles="Sincronización manual de obras completada."
        ))
        # ------------------------------------
        from app.utils import register_log
        register_log(
            user_id=current_user.id,
            category='obras',
            action='Finalizar Obra (Sincronización)',
            detail=f"Obra marcada como Finalizada automáticamente por Odoo: '{obra.nombre}'"
        )
                
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@sync_bp.route('/preview_empleados', methods=['GET'])
@login_required
@roles_required(ROLE_ADMIN)
def preview_empleados():
    try:
        from app.services.sync_preview_service import analyze_empleados_preview
        service = OdooSyncService()
        diff = service.get_diff_empleados()
        preview = analyze_empleados_preview(diff)
        return render_template('sync/preview_empleados.html', diff=diff, preview=preview)
    except Exception as e:
        flash(f"Error Odoo: {str(e)}", "danger")
        return redirect(url_for('sync.panel'))

@sync_bp.route('/preview_subcontratas', methods=['GET'])
@login_required
@roles_required(ROLE_ADMIN)
def preview_subcontratas():
    try:
        from app.services.sync_preview_service import analyze_subcontratas_preview
        service = OdooSyncService()
        diff = service.get_diff_subcontratas()
        preview = analyze_subcontratas_preview(diff)
        return render_template('sync/preview_subcontratas.html', diff=diff, preview=preview)
    except Exception as e:
        flash(f"Error Odoo: {str(e)}", "danger")
        return redirect(url_for('sync.panel'))

@sync_bp.route('/commit_subcontratas', methods=['POST'])
@login_required
def commit_subcontratas():
    data = request.json
    from app.utils.timezone_utils import utc_now
    ahora = utc_now()
    
    try:
        mapa_empresas = {} 
        
        # 1. ACTUALIZAR O CREAR EMPRESAS
        for obj in data.get('empresas', {}).get('actualizadas', []):
            comp = Company.query.get(obj['local_id'])
            if comp:
                comp.odoo_id = obj['odoo_id']
                comp.nombre = obj['nombre']
                mapa_empresas[obj['odoo_id']] = comp.id
                
        for obj in data.get('empresas', {}).get('nuevas', []):
            nueva_comp = Company(
                odoo_id=obj['odoo_id'],
                nombre=obj['nombre']
            )
            db.session.add(nueva_comp)
            db.session.flush() 
            mapa_empresas[obj['odoo_id']] = nueva_comp.id

        # 2. ACTUALIZAR EMPLEADOS (Seguro Anti-Colisiones DNI)
        for obj in data.get('empleados', {}).get('actualizados', []):
            user = User.query.get(obj['local_id'])
            if user:
                user.odoo_id = obj['odoo_id']
                user.name = obj['name']
                user.lastname = obj['lastname']
                user.categoria_profesional = obj.get('categoria_profesional')
                
                if obj['dni'] and not 'SINDNI' in obj['dni']:
                    # Comprobamos si otro usuario distinto ya tiene ese DNI
                    choque = User.query.filter(User.dni == obj['dni'], User.id != user.id).first()
                    if choque:
                        user.dni = f"{obj['dni']}-EXT{obj['odoo_id']}"
                    else:
                        user.dni = obj['dni']
                
                # --- CORRECCIÓN: Búsqueda dinámica de la empresa ---
                odoo_c_id = obj.get('odoo_company_id')
                if odoo_c_id:
                    if odoo_c_id not in mapa_empresas:
                        comp_existente = Company.query.filter_by(odoo_id=odoo_c_id).first()
                        if comp_existente:
                            mapa_empresas[odoo_c_id] = comp_existente.id
                    
                    if odoo_c_id in mapa_empresas:
                        user.company_id = mapa_empresas[odoo_c_id]
                # ---------------------------------------------------

        # 3. NUEVOS EMPLEADOS (Seguro Anti-Colisiones DNI + Memoria de Transacción)
        dnis_en_transaccion = set() # Memoria temporal por si en el mismo guardado vienen varios repetidos

        for obj in data.get('empleados', {}).get('nuevos', []):
            # --- CORRECCIÓN: Búsqueda dinámica de la empresa ---
            odoo_c_id = obj.get('odoo_company_id')
            local_comp_id = mapa_empresas.get(odoo_c_id)
            
            if not local_comp_id and odoo_c_id:
                comp_existente = Company.query.filter_by(odoo_id=odoo_c_id).first()
                if comp_existente:
                    local_comp_id = comp_existente.id
                    mapa_empresas[odoo_c_id] = local_comp_id
            # ---------------------------------------------------
            
            dni_limpio = obj['dni']
            
            # Revisar si existe en la BD o si ya lo hemos procesado en este mismo bucle
            existe_en_bd = User.query.filter_by(dni=dni_limpio).first()
            if existe_en_bd or dni_limpio in dnis_en_transaccion:
                dni_limpio = f"{dni_limpio}-EXT{obj['odoo_id']}"
                
            dnis_en_transaccion.add(dni_limpio)
            
            nuevo_user = User(
                odoo_id=obj['odoo_id'],
                name=obj['name'],
                lastname=obj['lastname'],
                dni=dni_limpio,
                email=obj['email'],
                role=obj['role'],
                categoria_profesional=obj.get('categoria_profesional'),
                company_id=local_comp_id, 
                active=True,
                password_hash=generate_password_hash("123456")
            )
            db.session.add(nuevo_user)

        total_nuevos = len(data.get('empresas', {}).get('nuevas', [])) + len(data.get('empleados', {}).get('nuevos', []))
        total_act = len(data.get('empresas', {}).get('actualizadas', [])) + len(data.get('empleados', {}).get('actualizados', []))
        
        db.session.add(SyncLog(
            fecha=ahora, tipo='Subcontratas', modo='Manual',
            nuevos=total_nuevos, actualizados=total_act,
            finalizados=0, errores=0, detalles="Sincronización de subcontratas y externos."
        ))

        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@sync_bp.route('/commit_empleados', methods=['POST'])
@login_required
def commit_empleados():
    data = request.json
    from app.utils.timezone_utils import utc_now
    ahora = utc_now()
    try:
        # Buscamos la primera empresa local para asignarla y que no sean "fantasmas"
        default_company = Company.query.first()
        default_company_id = default_company.id if default_company else None

        for obj in data.get('actualizados', []):
            user = User.query.get(obj['local_id'])
            if user:
                choque_dni = User.query.filter(User.dni == obj['dni'], User.id != user.id).first()
                choque_email = User.query.filter(User.email == obj['email'], User.id != user.id).first()
                
                user.odoo_id = obj['odoo_id']
                user.name = obj['name']
                user.lastname = obj['lastname']
                user.role = obj['role']
                user.categoria_profesional = obj.get('categoria_profesional', user.categoria_profesional)
                
                if not choque_dni: user.dni = obj['dni']
                if not choque_email: user.email = obj['email']
                
                # --- NUEVA LÓGICA PARA INTERNALIZACIONES ---
                # 1. Asignamos siempre la empresa interna ya que estamos sincronizando desde hr.employee
                user.company_id = default_company_id 
                # 2. Reactivamos al usuario por si venía de un borrado lógico o inactividad
                user.active = True
                user.is_deleted = False
                from app.utils import register_log
                register_log(
                    user_id=current_user.id,
                    category='rrhh_sync',
                    action="Empleado Actualizado desde Odoo",
                    detail=f"Datos modificados para: {user.name} {user.lastname}",
                    target_user_id=user.id
                )

        # 2. Procesar Nuevos (Con asignación de empresa)
        for obj in data.get('nuevos', []):
            existe = User.query.filter((User.dni == obj['dni']) | (User.email == obj['email'])).first()
            if not existe:
                nuevo_user = User(
                    odoo_id=obj['odoo_id'],
                    name=obj['name'],
                    lastname=obj['lastname'],
                    dni=obj['dni'],
                    email=obj['email'],
                    role=obj['role'],
                    categoria_profesional=obj.get('categoria_profesional', 'Sin definir'), # <--- AÑADIR ESTO
                    active=True,
                    company_id=default_company_id,
                    password_hash=generate_password_hash(obj['dni'])
                )
                db.session.add(nuevo_user)
                
        # --- AÑADIR REGISTRO DE HISTORIAL ---
        db.session.add(SyncLog(
            fecha=ahora,
            tipo='Empleados',
            modo='Manual',
            nuevos=len(data.get('nuevos', [])),
            actualizados=len(data.get('actualizadas', [])),
            finalizados=0,
            errores=data.get('errores', 0),
            detalles="Sincronización manual de empleados completada."
        ))
        # ------------------------------------

        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@sync_bp.route('/auditoria')
@login_required
def auditoria_fichajes():
    if current_user.role not in ['admin', 'jefe_obra']:
        flash("Acceso denegado. Solo Admin o Jefes de Obra pueden auditar fichajes.", "danger")
        return redirect(url_for('main.index'))
    
    # 1. FILTROS BASE MÚLTIPLES
    filtros_pendientes = [RegistroFichaje.estado.in_(['Conflicto', 'Paracaidista', 'Ausencia'])]
    filtros_historial = [~RegistroFichaje.estado.in_(['Conflicto', 'Paracaidista', 'Ausencia', 'Sin_Registro', 'Sobreescrito_RRHH'])]
    filtros_correcciones = [RegistroFichaje.estado == 'Sobreescrito_RRHH'] # NUEVO

    # 2. SI ES JEFE DE OBRA, AÑADIMOS RESTRICCIONES
    if current_user.role == 'jefe_obra':
        obras_jefe = Obra.query.filter_by(jefe_obra_id=current_user.id).all()
        obras_jefe_ids = [obra.id for obra in obras_jefe]
        
        filtro_jefe = or_(
            RegistroFichaje.obra_planificada_id.in_(obras_jefe_ids),
            RegistroFichaje.obra_real_id.in_(obras_jefe_ids)
        )
        filtros_pendientes.append(filtro_jefe)
        filtros_historial.append(filtro_jefe)
        filtros_correcciones.append(filtro_jefe)

    # 3. EJECUTAR QUERYS
    pendientes = RegistroFichaje.query.filter(*filtros_pendientes).order_by(RegistroFichaje.fecha.desc()).all()
    historial = RegistroFichaje.query.filter(*filtros_historial).order_by(RegistroFichaje.fecha.desc(), RegistroFichaje.fecha_auditoria.desc()).limit(1500).all()
    correcciones = RegistroFichaje.query.filter(*filtros_correcciones).order_by(RegistroFichaje.fecha.desc()).limit(500).all()
    
    return render_template('sync/auditoria.html', 
                           pendientes=pendientes, 
                           historial=historial,
                           correcciones=correcciones) # Pasamos la nueva variable

ACCION_RESOLUCION_TITULOS = {
    'ignorar': 'Ignorar',
    'mover': 'Mover',
    'anadir': 'Añadir',
    'borrar_planificacion': 'Borrar Planificación',
    'confirmar_ausencia': 'Confirmar Ausencia',
}


def _obra_label_resolucion(obra_id):
    if not obra_id:
        return None
    return CoreAssignmentService.format_obra_label(Obra.query.get(obra_id))


def _detalle_resolucion_fichaje(registro, accion, estado_anterior=None):
    obra_real = _obra_label_resolucion(registro.obra_real_id)
    obra_plan = _obra_label_resolucion(registro.obra_planificada_id)

    if accion == 'ignorar':
        if obra_real and obra_plan and obra_real != obra_plan:
            return (
                f"Se ignora el fichaje en '{obra_real}' "
                f"(estaba planificado en '{obra_plan}')."
            )
        if obra_real:
            return f"Se ignora el fichaje en '{obra_real}'."
        if obra_plan:
            return f"Se ignora la incidencia en '{obra_plan}'."
        return "Incidencia ignorada."

    if accion == 'mover':
        if obra_plan and obra_real:
            return f"Cuadrante actualizado: de '{obra_plan}' a '{obra_real}'."
        if obra_real:
            return f"Reasignado a '{obra_real}'."
        return "Reasignado a la obra real."

    if accion == 'anadir':
        if estado_anterior == 'Paracaidista' and obra_real:
            return f"Se acepta el fichaje sin planificar en '{obra_real}'."
        if obra_real:
            return f"Añadida asignación en '{obra_real}' (pluriempleo)."
        return "Añadida multi-asignación (pluriempleo)."

    if accion == 'borrar_planificacion':
        if obra_plan:
            return (
                f"Se elimina la planificación en '{obra_plan}' "
                f"(el operario no fichó en esa obra)."
            )
        return "Planificación eliminada."

    if accion == 'confirmar_ausencia':
        if obra_plan:
            return f"Ausencia confirmada: no acudió a '{obra_plan}'."
        return "Ausencia confirmada manualmente."

    return "Ajuste manual del cuadrante/fichaje."


@sync_bp.route('/auditoria/resolver', methods=['POST'])
@login_required
def resolver_fichaje():
    # BLINDAJE: Forzamos las importaciones dentro de la función para 
    # asegurar que Python no se confunda con variables locales o errores tipográficos.
    from app import db
    from app.models import RegistroFichaje, Asignacion, Obra
    from datetime import datetime
    
    if current_user.role not in ['admin', 'jefe_obra']:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
        
    data = request.json
    registro_id = data.get('registro_id')
    accion = data.get('accion')
    
    registro = RegistroFichaje.query.get(registro_id)
    if not registro:
        return jsonify({'success': False, 'error': 'Registro no encontrado'}), 404
        
    # Seguridad Backend: Evitar que un jefe resuelva un registro de otra obra
    if current_user.role == 'jefe_obra':
        obras_del_jefe = [o.id for o in Obra.query.filter_by(jefe_obra_id=current_user.id).all()]
        if registro.obra_planificada_id not in obras_del_jefe and registro.obra_real_id not in obras_del_jefe:
            return jsonify({'success': False, 'error': 'No tienes permisos sobre este registro.'}), 403

    try:
        registro.resuelto_por_id = current_user.id
        from app.utils.timezone_utils import utc_now
        registro.fecha_auditoria = utc_now()
        
        estado_anterior = None

        if accion == 'ignorar':
            registro.estado = 'Resuelto_Ignorado'

        elif accion == 'mover':
            # 1. Borrar de la obra donde estaba planificado y NO fue
            asignaciones_viejas = Asignacion.query.filter_by(
                user_id=registro.user_id, 
                fecha=registro.fecha, 
                obra_id=registro.obra_planificada_id
            ).all()
            for asig in asignaciones_viejas:
                CoreAssignmentService.desasignar(
                    asig.user_id, asig.obra_id, asig.fecha, current_user.id,
                    "Resolución de Fichaje: Mover"
                )
            
            # 2. Añadir a la obra donde SÍ ha ido (si no existe ya)
            if registro.obra_real_id:
                existe = Asignacion.query.filter_by(
                    user_id=registro.user_id, 
                    fecha=registro.fecha, 
                    obra_id=registro.obra_real_id
                ).first()
                if not existe:
                    CoreAssignmentService.asignar(
                        registro.user_id, registro.obra_real_id, registro.fecha,
                        current_user.id, "Resolución de Fichaje: Mover"
                    )
                
            registro.estado = 'Resuelto_Movido'

        elif accion == 'anadir':
            estado_anterior = registro.estado

            if registro.obra_real_id:
                existe = Asignacion.query.filter_by(
                    user_id=registro.user_id, 
                    fecha=registro.fecha, 
                    obra_id=registro.obra_real_id
                ).first()
                if not existe:
                    CoreAssignmentService.asignar(
                        registro.user_id, registro.obra_real_id, registro.fecha,
                        None, "Actualización de Cuadrante (Auto)"
                    )
            
            if estado_anterior == 'Paracaidista':
                registro.estado = 'Resuelto_Asignado'
            else:
                registro.estado = 'Resuelto_Dividido'

        elif accion == 'borrar_planificacion':
            asignaciones_viejas = Asignacion.query.filter_by(
                user_id=registro.user_id, 
                fecha=registro.fecha, 
                obra_id=registro.obra_planificada_id
            ).all()
            for asig in asignaciones_viejas:
                CoreAssignmentService.desasignar(
                    asig.user_id, asig.obra_id, asig.fecha, current_user.id,
                    "Borrar Planificación",
                )

            registro.estado = 'Resuelto_Falta'

        elif accion == 'confirmar_ausencia':
            registro.estado = 'Resuelto_Ausencia'

        registro.notas_resolucion = _detalle_resolucion_fichaje(
            registro, accion, estado_anterior=estado_anterior
        )

        from app.utils import register_log
        accion_titulo = ACCION_RESOLUCION_TITULOS.get(
            accion, accion.replace('_', ' ').title()
        )

        register_log(
            user_id=current_user.id,
            category='fichajes',
            action=f"Resolución de Fichaje: {accion_titulo}",
            detail=registro.notas_resolucion,
            target_user_id=registro.user_id,
            target_date=registro.fecha
        )
        # Al no reventar aquí, el commit funcionará y dejará el histórico
        db.session.commit()
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
    
@sync_bp.route('/fichajes_manual', methods=['POST'])
@login_required
def sync_fichajes_manual():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
        
    try:
        data = request.get_json() or {}
        dias_atras = int(data.get('dias', 7))
        dias_atras = max(0, min(365, dias_atras))

        from app.services.sync_runner_service import run_fichajes_retro_sync
        run_fichajes_retro_sync(days=dias_atras, modo='Manual')

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
    
    
@sync_bp.route('/timeline_dia/<int:user_id>/<string:fecha_str>', methods=['GET'])
@login_required
def get_timeline_dia(user_id, fecha_str):
    """Compatibilidad con auditoría de fichajes. Delega en el servicio compartido."""
    from app.services.person_day_timeline_service import build_person_day_timeline

    if current_user.role not in ['admin', 'jefe_obra']:
        return jsonify({'success': False, 'error': 'Acceso denegado'}), 403

    data = build_person_day_timeline(user_id, fecha_str)
    if not data:
        return jsonify({'success': False, 'error': 'Operario no encontrado'}), 404
    return jsonify(data)