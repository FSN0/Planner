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