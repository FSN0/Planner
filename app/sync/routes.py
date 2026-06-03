from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user # <--- OJO: AÑADE current_user AQUÍ
from werkzeug.security import generate_password_hash
from datetime import datetime
from app import db
from app.models import Obra, User, Company, SyncLog, Asignacion, RegistroFichaje 
from app.sync.dispatcher import get_sync_adapter
from sqlalchemy import or_
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, g
import xmlrpc.client
from app.services.config_service import set_tenant_config, get_tenant_config

sync_bp = Blueprint('sync', __name__, url_prefix='/sync')
@sync_bp.route('/')
@login_required
def panel():
    """El ESCAPARATE DE MÓDULOS. Lee el JSON del tenant para saber qué pintar."""
    modulos_activos = getattr(g.current_tenant, 'modulos_activos', {})
    if not modulos_activos:
        modulos_activos = {}
        
    return render_template('sync/panel.html', modulos_activos=modulos_activos)


@sync_bp.route('/odoo')
@login_required
def odoo_panel():
    """EL PANEL AISLADO DE ODOO (Configuración + Operaciones)"""
    modulos_activos = getattr(g.current_tenant, 'modulos_activos', {})
    
    # CAMBIO AQUÍ: Buscamos 'odoo', no 'odoo_soltec'
    if not modulos_activos.get('odoo'):
        flash("Tu empresa no tiene habilitado el módulo de Odoo.", "danger")
        return redirect(url_for('sync.panel'))
        
    # Extraemos la config actual (desencriptando el pass) para mostrarla en los inputs
    config = {
        'url': get_tenant_config('odoo_url', default=''),
        'db': get_tenant_config('odoo_db', default=''),
        'user': get_tenant_config('odoo_user', default=''),
        'password': get_tenant_config('odoo_password', desencriptar=True, default='')
    }
    
    logs = SyncLog.query.order_by(SyncLog.fecha.desc()).limit(15).all()
    return render_template('sync/odoo_panel.html', config=config, logs=logs)


@sync_bp.route('/odoo/save_config', methods=['POST'])
@login_required
def odoo_save_config():
    """Ruta puramente técnica para guardar credenciales. Solo Admin."""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
        
    try:
        set_tenant_config('odoo_url', request.form.get('url', '').strip())
        set_tenant_config('odoo_db', request.form.get('db', '').strip())
        set_tenant_config('odoo_user', request.form.get('user', '').strip())
        # OJO: La contraseña se encripta
        set_tenant_config('odoo_password', request.form.get('password', '').strip(), encriptar=True)
        
        flash("Credenciales de Odoo guardadas de forma segura.", "success")
        return redirect(url_for('sync.odoo_panel'))
    except Exception as e:
        flash(f"Error al guardar credenciales: {str(e)}", "danger")
        return redirect(url_for('sync.odoo_panel'))


@sync_bp.route('/odoo/test_connection', methods=['POST'])
@login_required
def odoo_test_connection():
    """Intenta hacer un login contra Odoo al vuelo con las credenciales actuales."""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 403
        
    url = get_tenant_config('odoo_url', default='')
    db_name = get_tenant_config('odoo_db', default='')
    user = get_tenant_config('odoo_user', default='')
    pwd = get_tenant_config('odoo_password', desencriptar=True, default='')
    
    if not url or not pwd:
        return jsonify({'success': False, 'error': 'Faltan credenciales por configurar.'})
        
    try:
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        uid = common.authenticate(db_name, user, pwd, {})
        if uid:
            return jsonify({'success': True, 'message': '¡Conexión establecida correctamente con Odoo!'})
        else:
            return jsonify({'success': False, 'error': 'Usuario, contraseña o base de datos incorrectos.'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error de red o servidor: {str(e)}'})

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
def preview_obras():
    try:
        service = get_sync_adapter()
        diff = service.get_diff_obras()
        jefes_locales = User.query.filter(User.role.in_(['jefe_obra', 'admin'])).all()
        encargados_locales = User.query.filter_by(active=True).all()
        return render_template('sync/preview_obras.html', diff=diff, jefes=jefes_locales, encargados=encargados_locales)
    except Exception as e:
        flash(f"Error Odoo: {str(e)}", "danger")
        return redirect(url_for('sync.panel'))

@sync_bp.route('/commit_obras', methods=['POST'])
@login_required
def commit_obras():
    data = request.json
    ahora = datetime.now() # Capturamos la hora de la importación
    
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
def preview_empleados():
    try:
        service = get_sync_adapter()
        diff = service.get_diff_empleados()
        return render_template('sync/preview_empleados.html', diff=diff)
    except Exception as e:
        flash(f"Error Odoo: {str(e)}", "danger")
        return redirect(url_for('sync.panel'))

@sync_bp.route('/preview_subcontratas', methods=['GET'])
@login_required
def preview_subcontratas():
    try:
        service = get_sync_adapter()
        diff = service.get_diff_subcontratas()
        # Puedes crear un HTML similar al de preview_empleados.html adaptado
        return render_template('sync/preview_subcontratas.html', diff=diff)
    except Exception as e:
        flash(f"Error Odoo: {str(e)}", "danger")
        return redirect(url_for('sync.panel'))

@sync_bp.route('/commit_subcontratas', methods=['POST'])
@login_required
def commit_subcontratas():
    data = request.json
    ahora = datetime.now()
    
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
    ahora = datetime.now() 
    try:
        # --- 1. SOLUCIÓN EMPRESAS: Buscar explícitamente la empresa INTERNA ---
        default_company = Company.query.filter_by(is_internal=True).first()
        if not default_company:
            # Fallback de emergencia
            default_company = Company.query.first()
        default_company_id = default_company.id if default_company else None

        # --- 2. SOLUCIÓN COLISIONES: Memoria de transacción ---
        dnis_en_transaccion = set()
        emails_en_transaccion = set()

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
                
                # Reasignamos a la empresa correcta por si estaban perdidos
                user.company_id = default_company_id 
                user.active = True
                user.is_deleted = False

                dnis_en_transaccion.add(user.dni)
                emails_en_transaccion.add(user.email)

        # Procesar Nuevos 
        for obj in data.get('nuevos', []):
            dni_limpio = obj['dni']
            email_limpio = obj['email']

            # Comprobamos tanto en la BD física como en la memoria de la transacción actual
            existe_bd = User.query.filter((User.dni == dni_limpio) | (User.email == email_limpio)).first()
            
            if existe_bd or dni_limpio in dnis_en_transaccion or email_limpio in emails_en_transaccion:
                # Si hay colisión, le inyectamos un identificador único para que no rompa el commit
                dni_limpio = f"{dni_limpio}-Odoo{obj['odoo_id']}"
                email_limpio = f"colision_{obj['odoo_id']}@local.tuappsaas.com"
                
            dnis_en_transaccion.add(dni_limpio)
            emails_en_transaccion.add(email_limpio)

            nuevo_user = User(
                odoo_id=obj['odoo_id'],
                name=obj['name'],
                lastname=obj['lastname'],
                dni=dni_limpio,
                email=email_limpio,
                role=obj['role'],
                categoria_profesional=obj.get('categoria_profesional', 'Sin definir'), 
                active=True,
                company_id=default_company_id,
                password_hash=generate_password_hash(dni_limpio)
            )
            db.session.add(nuevo_user)
                
        db.session.add(SyncLog(
            fecha=ahora,
            tipo='Empleados',
            modo='Manual',
            nuevos=len(data.get('nuevos', [])),
            actualizados=len(data.get('actualizados', [])),
            finalizados=0,
            errores=0,
            detalles="Sincronización manual completada (Corrección Multi-Tenant)."
        ))

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
        registro.fecha_auditoria = datetime.utcnow()
        
        if accion == 'ignorar':
            registro.estado = 'Resuelto_Ignorado'
            registro.notas_resolucion = "Ignorado"
            
        elif accion == 'mover':
            # 1. Borrar de la obra donde estaba planificado y NO fue
            asignaciones_viejas = Asignacion.query.filter_by(
                user_id=registro.user_id, 
                fecha=registro.fecha, 
                obra_id=registro.obra_planificada_id
            ).all()
            for asig in asignaciones_viejas:
                db.session.delete(asig)
            
            # 2. Añadir a la obra donde SÍ ha ido (si no existe ya)
            if registro.obra_real_id:
                existe = Asignacion.query.filter_by(
                    user_id=registro.user_id, 
                    fecha=registro.fecha, 
                    obra_id=registro.obra_real_id
                ).first()
                if not existe:
                    db.session.add(Asignacion(
                        obra_id=registro.obra_real_id, 
                        user_id=registro.user_id, 
                        fecha=registro.fecha
                    ))
                
            registro.estado = 'Resuelto_Movido'
            registro.notas_resolucion = "Reasignado a la obra real"
            
        elif accion == 'anadir':
            estado_anterior = registro.estado 
            
            if registro.obra_real_id:
                existe = Asignacion.query.filter_by(
                    user_id=registro.user_id, 
                    fecha=registro.fecha, 
                    obra_id=registro.obra_real_id
                ).first()
                if not existe:
                    db.session.add(Asignacion(
                        obra_id=registro.obra_real_id, 
                        user_id=registro.user_id, 
                        fecha=registro.fecha
                    ))
            
            if estado_anterior == 'Paracaidista':
                registro.estado = 'Resuelto_Asignado'
                registro.notas_resolucion = "Asignado oficialmente a la obra (No tenía plan)."
            else:
                registro.estado = 'Resuelto_Dividido'
                registro.notas_resolucion = "Añadida multi-asignación (Pluriempleo)."

        # >>> OPCIÓN 1: ERROR AL PLANIFICAR (Borra la planificación)
        elif accion == 'borrar_planificacion':
            asignaciones_viejas = Asignacion.query.filter_by(
                user_id=registro.user_id, 
                fecha=registro.fecha, 
                obra_id=registro.obra_planificada_id
            ).all()
            for asig in asignaciones_viejas:
                db.session.delete(asig)
                
            registro.estado = 'Resuelto_Falta'
            registro.notas_resolucion = "Planificación eliminada (Error al planificar)."

        # >>> OPCIÓN 2: AUSENCIA REAL (Mantiene la planificación)
        elif accion == 'confirmar_ausencia':
            registro.estado = 'Resuelto_Ausencia'
            registro.notas_resolucion = "Ausencia confirmada manualmente."
        
        from app.utils import register_log
        operario = User.query.get(registro.user_id)
        nombre_op = f"{operario.name} {operario.lastname}" if operario else f"ID {registro.user_id}"
        accion_limpia = accion.replace('_', ' ').title()
        register_log(
            user_id=current_user.id,
            category='fichajes',
            action=f"Resolución de Fichaje",
            detail=f"Ha resuelto un conflicto de {nombre_op} del {registro.fecha.strftime('%d/%m/%Y')}. Acción tomada: {accion_limpia}"
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
        from datetime import date, timedelta
        
        # Capturamos los días que el usuario ha seleccionado en el desplegable (por defecto 7)
        data = request.get_json() or {}
        dias_atras = int(data.get('dias', 7))
        
        from app.services.sync_service import procesar_fichajes_diarios
        procesar_fichajes_diarios(fecha_str=fecha_revision)
        service = get_sync_adapter()                
        
        # BUCLE: Sincroniza hoy y retrocede "dias_atras"
        for i in range(dias_atras + 1):
            fecha_revision = (date.today() - timedelta(days=i)).strftime('%Y-%m-%d')
            service.sync_fichajes_diarios(fecha_str=fecha_revision)
        
        # Guardamos en el log cuántos días hemos revisado
        texto_log = f"Sincronización manual de fichajes (Revisión de Hoy + últimos {dias_atras} días)."
        ahora = datetime.utcnow()
        db.session.add(SyncLog(
            fecha=ahora, tipo='Fichajes (Auditoría)', modo='Manual',
            nuevos=0, actualizados=0, finalizados=0, errores=0, 
            detalles=texto_log
        ))
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500