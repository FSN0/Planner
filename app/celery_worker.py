# app/celery_worker.py
import os
import secrets
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
# /app puede ser solo lectura (bind mount en dev); Beat necesita escribir su estado.
celery.conf.beat_schedule_filename = os.environ.get(
    'CELERY_BEAT_SCHEDULE_FILE', '/tmp/celerybeat-schedule'
)

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


def _set_search_path(schema='public'):
    """Cambia el search_path de la sesión actual del worker."""
    from sqlalchemy import text
    db.session.execute(text(f'SET search_path TO {schema}'))


def _load_active_tenants():
    """Lee tenants desde public con conexión aislada (seguro entre workers)."""
    from sqlalchemy import text

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                'SELECT id, schema_name, subdominio, nombre '
                'FROM public.tenants WHERE is_active = true'
            )
        ).fetchall()

    return [
        {
            'id': row[0],
            'schema_name': row[1],
            'subdominio': row[2],
            'nombre': row[3],
        }
        for row in rows
    ]


def _bind_tenant_context(tenant_data):
    from flask import g
    from app.models import Tenant

    tenant = Tenant(
        id=tenant_data['id'],
        schema_name=tenant_data['schema_name'],
        subdominio=tenant_data['subdominio'],
        nombre=tenant_data.get('nombre', ''),
    )
    g.current_tenant = tenant
    return tenant


# --- CONFIGURACIÓN DE TAREAS PROGRAMADAS AUTOMÁTICAS ---
celery.conf.beat_schedule = {
    'sync-scheduler': {
        'task': 'app.celery_worker.sync_scheduler',
        'schedule': crontab(minute='*/5'),
    },
    'verificador-corte-dinamico': {
        'task': 'app.celery_worker.verificar_hora_corte',
        'schedule': crontab(minute='2,7,12,17,22,27,32,37,42,47,52,57', hour='6-12'),
    }
}


def _sync_log_estado(errores, had_exception=False):
    if had_exception:
        return 'error'
    if errores and errores > 0:
        return 'parcial'
    return 'ok'


@celery.task
def sync_scheduler():
    """Despachador configurable: master data nocturno + fichajes en vivo."""
    with app.app_context():
        from app.services.sync_config_service import SyncConfigService
        try:
            if SyncConfigService.should_run_master_sync():
                app.logger.info(">>> Scheduler: lanzando sync nocturna de master data")
                auto_sync_odoo.delay()
            if SyncConfigService.should_run_fichajes_sync():
                app.logger.info(">>> Scheduler: lanzando sync de fichajes en vivo")
                fichajes_en_vivo.delay()
            if SyncConfigService.should_run_fichajes_retro_sync():
                app.logger.info(">>> Scheduler: lanzando sync retrospectiva de fichajes")
                fichajes_retroactivos.delay()
        finally:
            _cleanup_db_session()

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
# ====================================================================
# LÓGICA MULTI-TENANT PARA TAREAS EN SEGUNDO PLANO
# ====================================================================
@celery.task
def verificar_hora_corte():
    with app.app_context():
        from app.models import ConfiguracionGlobal
        from datetime import datetime, timedelta
        from app.services.email_service import enviar_super_reporte_diario

        try:
            _cleanup_db_session()
            for tenant_data in _load_active_tenants():
                subdominio = tenant_data['subdominio']
                try:
                    _set_search_path(tenant_data['schema_name'])
                    _bind_tenant_context(tenant_data)

                    conf_hora = ConfiguracionGlobal.query.filter_by(clave='hora_limite_entrada').first()
                    hora_str = conf_hora.valor if conf_hora else "08:30"
                    hora_corte = datetime.strptime(hora_str, "%H:%M").time()
                    ahora_espana = datetime.utcnow() + timedelta(hours=2)

                    if ahora_espana.time() >= hora_corte:
                        hoy_str = ahora_espana.strftime('%Y-%m-%d')
                        conf_ultimo = ConfiguracionGlobal.query.filter_by(clave='ultimo_reporte_enviado').first()

                        if not conf_ultimo or conf_ultimo.valor != hoy_str:
                            app.logger.info(f">>> HORA DE CORTE ALCANZADA PARA {subdominio.upper()}")

                            from app.services.sync_service import procesar_fichajes_diarios
                            procesar_fichajes_diarios()
                            enviar_super_reporte_diario()

                            if not conf_ultimo:
                                db.session.add(ConfiguracionGlobal(clave='ultimo_reporte_enviado', valor=hoy_str))
                            else:
                                conf_ultimo.valor = hoy_str
                            db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    app.logger.error(f"!!! Error en hora de corte para inquilino {subdominio}: {e}")
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
   
   
 app/celery_worker.py
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
    'sync-scheduler': {
        'task': 'app.celery_worker.sync_scheduler',
        'schedule': crontab(minute='*/5'),
    },
    'verificador-corte-dinamico': {
        'task': 'app.celery_worker.verificar_hora_corte',
        'schedule': crontab(minute='2,7,12,17,22,27,32,37,42,47,52,57', hour='6-12'),
    }
}


def _sync_log_estado(errores, had_exception=False):
    if had_exception:
        return 'error'
    if errores and errores > 0:
        return 'parcial'
    return 'ok'


@celery.task
def sync_scheduler():
    """Despachador configurable: master data nocturno + fichajes en vivo."""
    with app.app_context():
        from app.services.sync_config_service import SyncConfigService
        try:
            if SyncConfigService.should_run_master_sync():
                app.logger.info(">>> Scheduler: lanzando sync nocturna de master data")
                auto_sync_odoo.delay()
            if SyncConfigService.should_run_fichajes_sync():
                app.logger.info(">>> Scheduler: lanzando sync de fichajes en vivo")
                fichajes_en_vivo.delay()
            if SyncConfigService.should_run_fichajes_retro_sync():
                app.logger.info(">>> Scheduler: lanzando sync retrospectiva de fichajes")
                fichajes_retroactivos.delay()
        finally:
            _cleanup_db_session()

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
        from app.services.sync_config_service import SyncConfigService
        from app.utils.timezone_utils import utc_now
        import time
        t0 = time.time()
        app.logger.info(">>> INICIANDO SYNC DE FICHAJES EN VIVO (AUTOMÁTICO)")
        had_error = False
        err_msg = None
        try:
            service = OdooSyncService()
            service.sync_fichajes_diarios()
            SyncConfigService.mark_fichajes_sync_done()
            app.logger.info(">>> Sincronización en vivo cruzada correctamente.")
        except Exception as e:
            had_error = True
            err_msg = str(e)
            app.logger.error(f"!!! Error cruzando fichajes en vivo: {e}")
        finally:
            duracion = int((time.time() - t0) * 1000)
            try:
                db.session.add(SyncLog(
                    fecha=utc_now(),
                    tipo='Fichajes',
                    modo='Automático',
                    nuevos=0, actualizados=0, finalizados=0, errores=1 if had_error else 0,
                    detalles='Sincronización automática de fichajes del día.',
                    estado='error' if had_error else 'ok',
                    duracion_ms=duracion,
                    mensaje_error=err_msg,
                ))
                db.session.commit()
            except Exception:
                db.session.rollback()
            _cleanup_db_session()


@celery.task
def fichajes_retroactivos():
    with app.app_context():
        from app.services.sync_runner_service import run_fichajes_retro_sync
        from app.services.sync_config_service import SyncConfigService
        app.logger.info(">>> INICIANDO SYNC RETROSPECTIVA DE FICHAJES (AUTOMÁTICO)")
        try:
            run_fichajes_retro_sync()
            SyncConfigService.mark_fichajes_retro_sync_done()
            app.logger.info(">>> Revisión retrospectiva de fichajes completada.")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"!!! Error en sync retrospectiva de fichajes: {e}")
        finally:
            _cleanup_db_session()


@celery.task
def auto_sync_obras():
    with app.app_context():
        from app.services.sync_runner_service import run_auto_sync_obras
        from app.services.sync_config_service import SyncConfigService
        try:
            if SyncConfigService.get_config()['obras_enabled']:
                run_auto_sync_obras()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"!!! Error sync obras: {e}")
        finally:
            _cleanup_db_session()


@celery.task
def auto_sync_empleados():
    with app.app_context():
        from app.services.sync_runner_service import run_auto_sync_empleados
        from app.services.sync_config_service import SyncConfigService
        try:
            if SyncConfigService.get_config()['empleados_enabled']:
                run_auto_sync_empleados()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"!!! Error sync empleados: {e}")
        finally:
            _cleanup_db_session()


@celery.task
def auto_sync_subcontratas():
    with app.app_context():
        from app.services.sync_runner_service import run_auto_sync_subcontratas
        from app.services.sync_config_service import SyncConfigService
        try:
            if SyncConfigService.get_config()['subcontratas_enabled']:
                run_auto_sync_subcontratas()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"!!! Error sync subcontratas: {e}")
        finally:
            _cleanup_db_session()


            
@celery.task
def auto_sync_odoo():
    with app.app_context():
        from app.services.sync_config_service import SyncConfigService
        import time
        t0 = time.time()
        app.logger.info(">>> INICIANDO SYNC NOCTURNA COMPLETA")
        critical_error = None
        try:
            from app.services.sync_runner_service import (
                run_auto_sync_obras, run_auto_sync_empleados, run_auto_sync_subcontratas,
            )
            cfg = SyncConfigService.get_config()
            if cfg['obras_enabled']:
                run_auto_sync_obras()
            if cfg['empleados_enabled']:
                run_auto_sync_empleados()
            if cfg['subcontratas_enabled']:
                run_auto_sync_subcontratas()
            SyncConfigService.mark_master_sync_done()
            app.logger.info(">>> Sincronización nocturna finalizada con éxito.")
        except Exception as e:
            critical_error = str(e)
            db.session.rollback()
            app.logger.error(f"!!! Error crítico en sync nocturna: {e}")
            try:
                from app.utils.timezone_utils import utc_now
                db.session.add(SyncLog(
                    fecha=utc_now(), tipo='Master Data', modo='Automático',
                    nuevos=0, actualizados=0, finalizados=0, errores=1,
                    detalles='Fallo crítico en sincronización nocturna.',
                    estado='error', mensaje_error=critical_error,
                    duracion_ms=int((time.time() - t0) * 1000),
                ))
                db.session.commit()
            except Exception:
                db.session.rollback()
        finally:
            _cleanup_db_session()