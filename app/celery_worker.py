# app/celery_worker.py
import os
import time
from celery import Celery
from celery.schedules import crontab
from app import create_app, mail, db
from app.models import SyncLog
import logging
from flask_mail import Message

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


def _tenant_has_odoo_module(tenant_data):
    from sqlalchemy import text

    with db.engine.connect() as conn:
        row = conn.execute(
            text('SELECT modulos_activos FROM public.tenants WHERE id = :id'),
            {'id': tenant_data['id']},
        ).fetchone()
    if not row or not row[0]:
        return False
    modulos = row[0] if isinstance(row[0], dict) else {}
    return bool(modulos.get('odoo'))


def _for_each_tenant(callback):
    """Ejecuta callback(tenant_data) en el schema de cada tenant activo con Odoo."""
    _cleanup_db_session()
    for tenant_data in _load_active_tenants():
        if not _tenant_has_odoo_module(tenant_data):
            continue
        subdominio = tenant_data['subdominio']
        try:
            _set_search_path(tenant_data['schema_name'])
            _bind_tenant_context(tenant_data)
            callback(tenant_data)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"!!! Error en tarea para inquilino {subdominio}: {e}")
        finally:
            _cleanup_db_session()


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


@celery.task
def sync_scheduler():
    """Despachador configurable: master data nocturno + fichajes en vivo."""
    with app.app_context():
        from app.services.sync_config_service import SyncConfigService

        master_needed = False
        fichajes_needed = False
        retro_needed = False

        def _check_tenant_schedule(_tenant_data):
            nonlocal master_needed, fichajes_needed, retro_needed
            if SyncConfigService.should_run_master_sync():
                master_needed = True
            if SyncConfigService.should_run_fichajes_sync():
                fichajes_needed = True
            if SyncConfigService.should_run_fichajes_retro_sync():
                retro_needed = True

        try:
            _for_each_tenant(_check_tenant_schedule)
            if master_needed:
                app.logger.info(">>> Scheduler: lanzando sync nocturna de master data")
                auto_sync_odoo.delay()
            if fichajes_needed:
                app.logger.info(">>> Scheduler: lanzando sync de fichajes en vivo")
                fichajes_en_vivo.delay()
            if retro_needed:
                app.logger.info(">>> Scheduler: lanzando sync retrospectiva de fichajes")
                fichajes_retroactivos.delay()
        finally:
            _cleanup_db_session()


@celery.task
def send_async_email(subject, recipients, body, html):
    with app.app_context():
        sender = app.config.get("MAIL_DEFAULT_SENDER")
        msg = Message(subject, recipients=recipients, body=body, html=html, sender=sender)
        app.logger.info(
            "Preparando envío de correo: subject='%s', sender='%s', recipients=%s",
            subject, sender, recipients,
        )
        try:
            mail.send(msg)
            app.logger.info("Correo enviado correctamente.")
        except Exception as e:
            app.logger.error("Error enviando correo: %s", e)
        finally:
            _cleanup_db_session()


@celery.task
def verificar_hora_corte():
    with app.app_context():
        from app.models import ConfiguracionGlobal
        from datetime import datetime
        from app.services.email_service import enviar_super_reporte_diario
        from app.services.sync_service import procesar_fichajes_diarios
        from app.utils.timezone_utils import now_local, today_local

        def _run_for_tenant(_tenant_data):
            conf_hora = ConfiguracionGlobal.query.filter_by(clave='hora_limite_entrada').first()
            hora_str = conf_hora.valor if conf_hora else "08:30"
            hora_corte = datetime.strptime(hora_str, "%H:%M").time()
            ahora_local = now_local()

            if ahora_local.time() < hora_corte:
                return

            hoy_str = today_local().strftime('%Y-%m-%d')
            conf_ultimo = ConfiguracionGlobal.query.filter_by(clave='ultimo_reporte_enviado').first()
            if conf_ultimo and conf_ultimo.valor == hoy_str:
                return

            app.logger.info(f">>> HORA DE CORTE ALCANZADA ({hora_str}). MARCANDO AUSENCIAS Y ENVIANDO REPORTE.")
            procesar_fichajes_diarios()
            enviar_super_reporte_diario()

            if not conf_ultimo:
                db.session.add(ConfiguracionGlobal(clave='ultimo_reporte_enviado', valor=hoy_str))
            else:
                conf_ultimo.valor = hoy_str

        try:
            _for_each_tenant(_run_for_tenant)
        finally:
            _cleanup_db_session()


@celery.task
def fichajes_en_vivo():
    with app.app_context():
        from app.services.sync_service import procesar_fichajes_diarios
        from app.services.sync_config_service import SyncConfigService
        from app.utils.timezone_utils import utc_now

        def _run_for_tenant(tenant_data):
            t0 = time.time()
            had_error = False
            err_msg = None
            app.logger.info(f">>> INICIANDO SYNC DE FICHAJES EN VIVO ({tenant_data['subdominio']})")
            try:
                procesar_fichajes_diarios()
                SyncConfigService.mark_fichajes_sync_done()
                app.logger.info(">>> Sincronización en vivo cruzada correctamente.")
            except Exception as e:
                had_error = True
                err_msg = str(e)
                app.logger.error(f"!!! Error cruzando fichajes en vivo: {e}")
            finally:
                duracion = int((time.time() - t0) * 1000)
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

        try:
            _for_each_tenant(_run_for_tenant)
        finally:
            _cleanup_db_session()


@celery.task
def fichajes_retroactivos():
    with app.app_context():
        from app.services.sync_runner_service import run_fichajes_retro_sync
        from app.services.sync_config_service import SyncConfigService

        def _run_for_tenant(_tenant_data):
            app.logger.info(">>> INICIANDO SYNC RETROSPECTIVA DE FICHAJES (AUTOMÁTICO)")
            run_fichajes_retro_sync()
            SyncConfigService.mark_fichajes_retro_sync_done()
            app.logger.info(">>> Revisión retrospectiva de fichajes completada.")

        try:
            _for_each_tenant(_run_for_tenant)
        except Exception as e:
            app.logger.error(f"!!! Error en sync retrospectiva de fichajes: {e}")
        finally:
            _cleanup_db_session()


@celery.task
def auto_sync_obras():
    with app.app_context():
        from app.services.sync_runner_service import run_auto_sync_obras
        from app.services.sync_config_service import SyncConfigService

        def _run_for_tenant(_tenant_data):
            if SyncConfigService.get_config()['obras_enabled']:
                run_auto_sync_obras()

        try:
            _for_each_tenant(_run_for_tenant)
        finally:
            _cleanup_db_session()


@celery.task
def auto_sync_empleados():
    with app.app_context():
        from app.services.sync_runner_service import run_auto_sync_empleados
        from app.services.sync_config_service import SyncConfigService

        def _run_for_tenant(_tenant_data):
            if SyncConfigService.get_config()['empleados_enabled']:
                run_auto_sync_empleados()

        try:
            _for_each_tenant(_run_for_tenant)
        finally:
            _cleanup_db_session()


@celery.task
def auto_sync_subcontratas():
    with app.app_context():
        from app.services.sync_runner_service import run_auto_sync_subcontratas
        from app.services.sync_config_service import SyncConfigService

        def _run_for_tenant(_tenant_data):
            if SyncConfigService.get_config()['subcontratas_enabled']:
                run_auto_sync_subcontratas()

        try:
            _for_each_tenant(_run_for_tenant)
        finally:
            _cleanup_db_session()


@celery.task
def auto_sync_ausencias():
    with app.app_context():
        from app.services.sync_runner_service import run_auto_sync_ausencias
        from app.services.sync_config_service import SyncConfigService

        def _run_for_tenant(_tenant_data):
            if SyncConfigService.get_config().get('ausencias_enabled', True):
                run_auto_sync_ausencias()

        try:
            _for_each_tenant(_run_for_tenant)
        finally:
            _cleanup_db_session()


@celery.task
def auto_sync_odoo():
    with app.app_context():
        from app.services.sync_config_service import SyncConfigService
        from app.services.sync_runner_service import (
            run_auto_sync_obras, run_auto_sync_empleados, run_auto_sync_subcontratas,
            run_auto_sync_ausencias,
        )

        def _run_for_tenant(_tenant_data):
            t0 = time.time()
            app.logger.info(f">>> INICIANDO SYNC NOCTURNA COMPLETA ({_tenant_data['subdominio']})")
            critical_error = None
            try:
                cfg = SyncConfigService.get_config()
                if cfg['obras_enabled']:
                    run_auto_sync_obras()
                if cfg['empleados_enabled']:
                    run_auto_sync_empleados()
                if cfg['subcontratas_enabled']:
                    run_auto_sync_subcontratas()
                if cfg.get('ausencias_enabled', True):
                    run_auto_sync_ausencias()
                SyncConfigService.mark_master_sync_done()
                app.logger.info(">>> Sincronización nocturna finalizada con éxito.")
            except Exception as e:
                critical_error = str(e)
                db.session.rollback()
                app.logger.error(f"!!! Error crítico en sync nocturna: {e}")
                from app.utils.timezone_utils import utc_now
                db.session.add(SyncLog(
                    fecha=utc_now(), tipo='Master Data', modo='Automático',
                    nuevos=0, actualizados=0, finalizados=0, errores=1,
                    detalles='Fallo crítico en sincronización nocturna.',
                    estado='error', mensaje_error=critical_error,
                    duracion_ms=int((time.time() - t0) * 1000),
                ))

        try:
            _for_each_tenant(_run_for_tenant)
        finally:
            _cleanup_db_session()
