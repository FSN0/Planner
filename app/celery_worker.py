# app/celery_worker.py
from celery import Celery
from celery.schedules import crontab
from app import create_app, mail, db
from app.models import Obra, User, Company, SyncLog
import logging
from flask_mail import Message
from datetime import datetime
from werkzeug.security import generate_password_hash

app = create_app()
celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

with app.app_context():
    from app.utils.timezone_utils import get_app_timezone
    celery.conf.timezone = get_app_timezone()


def _cleanup_db_session():
    """Devuelve la conexión al pool limpia tras cada tarea Celery."""
    try:
        db.session.rollback()
    except Exception:
        pass
    db.session.remove()


# --- CONFIGURACIÓN DE TAREAS PROGRAMADAS AUTOMÁTICAS ---
celery.conf.beat_schedule = {
    'sync-odoo-nocturno': {
        'task': 'app.celery_worker.auto_sync_odoo',
        'schedule': crontab(hour=3, minute=0),
    },
    'sync-fichajes-vivo': {
        'task': 'app.celery_worker.fichajes_en_vivo',
        'schedule': crontab(minute='0,30', hour='7-19'),
    },
    # >>> NUEVA TAREA: Verificador dinámico de la hora de corte
    # >>> NUEVA TAREA: Verificador dinámico de la hora de corte
    'verificador-corte-dinamico': {
        'task': 'app.celery_worker.verificar_hora_corte',
        # Desfasamos 2 minutos para evitar la colisión de las en punto y las medias
        'schedule': crontab(minute='2,7,12,17,22,27,32,37,42,47,52,57', hour='6-12'), 
    }
}

@celery.task
def send_async_email(subject, recipients, body, html):
    with app.app_context():
        sender = app.config.get("MAIL_DEFAULT_SENDER")
        msg = Message(subject, recipients=recipients, body=body, html=html, sender=sender)
        app.logger.info("Preparando envío de correo: subject='%s', sender='%s', recipients=%s", subject, sender, recipients)
        try:
            mail.send(msg)
            app.logger.info("Correo enviado correctamente.")
        except Exception as e:
            app.logger.error("Error enviando correo: %s", e)
        finally:
            _cleanup_db_session()

# >>> NUEVA TAREA QUE EJECUTA EL CORTE Y EL REPORTE
@celery.task
def verificar_hora_corte():
    with app.app_context():
        from app.models import ConfiguracionGlobal
        from datetime import datetime
        from app.utils.timezone_utils import now_local, today_local
        
        conf_hora = ConfiguracionGlobal.query.filter_by(clave='hora_limite_entrada').first()
        hora_str = conf_hora.valor if conf_hora else "08:30"
        hora_corte = datetime.strptime(hora_str, "%H:%M").time()
        
        ahora_local = now_local()
        
        try:
            if ahora_local.time() >= hora_corte:
                hoy_str = today_local().strftime('%Y-%m-%d')
                
                # 3. Comprobar si ya hemos pasado el reporte hoy
                conf_ultimo = ConfiguracionGlobal.query.filter_by(clave='ultimo_reporte_enviado').first()
                
                if not conf_ultimo or conf_ultimo.valor != hoy_str:
                    app.logger.info(f">>> HORA DE CORTE ALCANZADA ({hora_str}). MARCANDO AUSENCIAS Y ENVIANDO REPORTE.")
                    
                    from app.services.sync_service import OdooSyncService
                    from app.services.email_service import enviar_super_reporte_diario
                    
                    service = OdooSyncService()
                    
                    # A) Bajamos últimos fichajes. (Esta función ya hace la auto-evaluación y marca ausencias)
                    service.sync_fichajes_diarios()
                    
                    # B) Enviamos el correo combinado
                    enviar_super_reporte_diario()
                    
                    # Registramos que ya se envió hoy
                    if not conf_ultimo:
                        db.session.add(ConfiguracionGlobal(clave='ultimo_reporte_enviado', valor=hoy_str))
                    else:
                        conf_ultimo.valor = hoy_str
                    db.session.commit()
        finally:
            _cleanup_db_session()

@celery.task
def fichajes_en_vivo():
    with app.app_context():
        from app.services.sync_service import OdooSyncService
        app.logger.info(">>> INICIANDO SYNC DE FICHAJES EN VIVO (AUTOMÁTICO)")
        try:
            service = OdooSyncService()
            service.sync_fichajes_diarios() # Coge por defecto el día de hoy
            app.logger.info(">>> Sincronización en vivo cruzada correctamente.")
        except Exception as e:
            app.logger.error(f"!!! Error cruzando fichajes en vivo: {e}")
        finally:
            _cleanup_db_session()


            
@celery.task
def auto_sync_odoo():
    with app.app_context():
        from app.services.sync_service import OdooSyncService
        app.logger.info(">>> INICIANDO SYNC NOCTURNA DE OBRAS Y EMPLEADOS (AUTOMÁTICO)")
        try:
            service = OdooSyncService()
            from app.utils.timezone_utils import utc_now
            ahora = utc_now()
            
            # 1. PROCESAR OBRAS
            diff_obras = service.get_diff_obras()
            nuevas_limpias = [o for o in diff_obras['nuevas'] if not o.get('warn_jefe') and not o.get('warn_encargado')]
            act_limpias = [o for o in diff_obras['actualizadas'] if not o.get('warn_jefe') and not o.get('warn_encargado')]
            errores_obras = (len(diff_obras['nuevas']) - len(nuevas_limpias)) + (len(diff_obras['actualizadas']) - len(act_limpias))
            
            for obj in nuevas_limpias:
                f_inicio = datetime.strptime(obj['fecha_inicio'], "%Y-%m-%d").date() if obj.get('fecha_inicio') else None
                n_obra = Obra(
                    odoo_id=obj['odoo_id'], codigo=obj['codigo'], nombre=obj['nombre'],
                    descripcion=obj.get('cliente', ''), fecha_inicio=f_inicio, estado='Pendiente',
                    jefe_obra_id=obj.get('jefe_obra_id'), encargado_id=obj.get('encargado_id'),
                    fecha_importacion=ahora
                )
                db.session.add(n_obra)
                
            for obj in act_limpias:
                obra = Obra.query.get(obj['local_id'])
                if obra:
                    obra.odoo_id = obj['odoo_id']
                    obra.codigo = obj['codigo']
                    obra.nombre = obj['nombre']
                    obra.descripcion = obj.get('cliente', '')
                    obra.fecha_importacion = ahora
                    if obj.get('fecha_inicio'): obra.fecha_inicio = datetime.strptime(obj['fecha_inicio'], "%Y-%m-%d").date()
                    if obj.get('jefe_obra_id'): obra.jefe_obra_id = obj['jefe_obra_id']
                    if obj.get('encargado_id'): obra.encargado_id = obj['encargado_id']
                    
            for obj in diff_obras['finalizadas']:
                obra = Obra.query.get(obj['local_id'])
                if obra:
                    obra.estado = 'Finalizada'
                    obra.fecha_fin = ahora.date()
                    obra.fecha_importacion = ahora

            db.session.add(SyncLog(
                fecha=ahora, tipo='Obras', modo='Automático',
                nuevos=len(nuevas_limpias), actualizados=len(act_limpias),
                finalizados=len(diff_obras['finalizadas']), errores=errores_obras,
                detalles="Sincronización nocturna automática."
            ))

            # 2. PROCESAR EMPLEADOS
            diff_emp = service.get_diff_empleados()
            emp_nuevos = diff_emp['nuevos']
            emp_act_limpios = [e for e in diff_emp['actualizados'] if not e.get('conflicto')]
            errores_emp = len(diff_emp['actualizados']) - len(emp_act_limpios)
            default_company = Company.query.first()
            default_company_id = default_company.id if default_company else None

            for obj in emp_nuevos:
                n_user = User(
                    odoo_id=obj['odoo_id'], name=obj['name'], lastname=obj['lastname'],
                    dni=obj['dni'], email=obj['email'], role=obj['role'],
                    categoria_profesional=obj.get('categoria_profesional', 'Sin definir'), 
                    company_id=default_company_id, active=True,
                    password_hash=generate_password_hash("123456")
                )
                db.session.add(n_user)
            
            for obj in emp_act_limpios:
                user = User.query.get(obj['local_id'])
                if user:
                    user.odoo_id = obj['odoo_id']
                    user.name = obj['name']
                    user.lastname = obj['lastname']
                    user.role = obj['role']
                    user.categoria_profesional = obj.get('categoria_profesional', user.categoria_profesional) 

            db.session.add(SyncLog(
                fecha=ahora, tipo='Empleados', modo='Automático',
                nuevos=len(emp_nuevos), actualizados=len(emp_act_limpios),
                finalizados=0, errores=errores_emp,
                detalles="Sincronización nocturna automática."
            ))

            # 3. PROCESAR SUBCONTRATAS
            diff_sub = service.get_diff_subcontratas()
            mapa_empresas = {} 
            
            for obj in diff_sub['empresas']['actualizadas']:
                comp = Company.query.get(obj['local_id'])
                if comp:
                    comp.odoo_id = obj['odoo_id']
                    comp.nombre = obj['nombre']
                    mapa_empresas[obj['odoo_id']] = comp.id
                    
            for obj in diff_sub['empresas']['nuevas']:
                nueva_comp = Company(odoo_id=obj['odoo_id'], nombre=obj['nombre'])
                db.session.add(nueva_comp)
                db.session.flush() 
                mapa_empresas[obj['odoo_id']] = nueva_comp.id

            # ... (la parte de las empresas déjala igual) ...

            for obj in diff_sub['empleados']['actualizados']:
                user = User.query.get(obj['local_id'])
                if user:
                    user.odoo_id = obj['odoo_id']
                    user.name = obj['name']
                    user.lastname = obj['lastname']
                    if obj['dni'] and not 'SINDNI' in obj['dni']: user.dni = obj['dni']
                    user.categoria_profesional = obj.get('categoria_profesional')
                    
                    # --- CORRECCIÓN: Búsqueda dinámica de la empresa ---
                    odoo_c_id = obj.get('odoo_company_id')
                    if odoo_c_id:
                        if odoo_c_id not in mapa_empresas:
                            # Si no está en el diccionario temporal, vamos a buscarla a la BD
                            comp_existente = Company.query.filter_by(odoo_id=odoo_c_id).first()
                            if comp_existente:
                                mapa_empresas[odoo_c_id] = comp_existente.id
                        
                        if odoo_c_id in mapa_empresas:
                            user.company_id = mapa_empresas[odoo_c_id]
                    # ---------------------------------------------------

            for obj in diff_sub['empleados']['nuevos']:
                # --- CORRECCIÓN: Búsqueda dinámica de la empresa ---
                odoo_c_id = obj.get('odoo_company_id')
                local_comp_id = mapa_empresas.get(odoo_c_id)
                
                if not local_comp_id and odoo_c_id:
                    comp_existente = Company.query.filter_by(odoo_id=odoo_c_id).first()
                    if comp_existente:
                        local_comp_id = comp_existente.id
                        mapa_empresas[odoo_c_id] = local_comp_id
                # ---------------------------------------------------
                
                n_user_sub = User(
                    odoo_id=obj['odoo_id'], name=obj['name'], lastname=obj['lastname'], 
                    dni=obj['dni'], email=obj['email'], role=obj['role'], 
                    categoria_profesional=obj.get('categoria_profesional'), 
                    company_id=local_comp_id, active=True, 
                    password_hash=generate_password_hash("123456")
                )
                db.session.add(n_user_sub)

            tot_n_sub = len(diff_sub['empresas']['nuevas']) + len(diff_sub['empleados']['nuevos'])
            tot_a_sub = len(diff_sub['empresas']['actualizadas']) + len(diff_sub['empleados']['actualizados'])
            db.session.add(SyncLog(
                fecha=ahora, tipo='Subcontratas', modo='Automático', 
                nuevos=tot_n_sub, actualizados=tot_a_sub, finalizados=0, errores=0, 
                detalles="Sincronización nocturna automática."
            ))

            db.session.commit()
            app.logger.info(">>> Sincronización nocturna finalizada con éxito.")
        except Exception as e:
            app.logger.error(f"!!! Error crítico en sync nocturna: {e}")
        finally:
            _cleanup_db_session()