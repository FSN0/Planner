# app/celery_worker.py
import os
import time
from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init
from app import create_app, is_safe_schema_name, mail, db
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


@worker_process_init.connect
def _dispose_db_pool_after_fork(**_kwargs):
    """Prefork hereda conexiones del padre; hay que tirar el pool o Postgres se desincroniza."""
    with app.app_context():
        try:
            db.session.remove()
        except Exception:
            pass
        try:
            db.engine.dispose()
        except Exception:
            pass


def _cleanup_db_session(*, dispose_on_error=False):
    """Devuelve la conexión al pool limpia tras cada tarea / tenant Celery."""
    try:
        db.session.rollback()
    except Exception:
        dispose_on_error = True
    try:
        db.session.remove()
    except Exception:
        dispose_on_error = True
    if dispose_on_error:
        try:
            db.engine.dispose()
        except Exception:
            pass


def _set_search_path(schema='public'):
    """Cambia el search_path de la sesión actual del worker (tenant + public)."""
    from sqlalchemy import text

    if schema != 'public' and not is_safe_schema_name(schema):
        raise ValueError(f'schema inseguro: {schema!r}')
    target = 'public' if schema == 'public' else f'{schema}, public'
    db.session.execute(text(f'SET search_path TO {target}'))


def _load_active_tenants():
    """Lee tenants desde public con conexión aislada (seguro entre workers)."""
    from sqlalchemy import text

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                'SELECT id, schema_name, subdominio, nombre, modulos_activos '
                'FROM public.tenants WHERE is_active = true'
            )
        ).fetchall()

    return [
        {
            'id': row[0],
            'schema_name': row[1],
            'subdominio': row[2],
            'nombre': row[3],
            'modulos_activos': row[4] if isinstance(row[4], dict) else {},
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
        modulos_activos=tenant_data.get('modulos_activos') or {},
    )
    g.current_tenant = tenant
    return tenant


def _tenant_has_odoo_module(tenant_data):
    modulos = tenant_data.get('modulos_activos') or {}
    return bool(modulos.get('odoo'))


def _for_each_tenant(callback, *, solo_odoo=True):
    """
    Ejecuta callback(tenant_data) en el schema de cada tenant activo.

    Por defecto solo tenants con módulo Odoo (sync ERP). Para cierre de
    jornada / hora de corte pasar solo_odoo=False: el fichaje local (PWA)
    también necesita marcar ausencias tras el corte.
    """
    _cleanup_db_session()
    for tenant_data in _load_active_tenants():
        if solo_odoo and not _tenant_has_odoo_module(tenant_data):
            continue
        subdominio = tenant_data['subdominio']
        try:
            _set_search_path(tenant_data['schema_name'])
            _bind_tenant_context(tenant_data)
            callback(tenant_data)
            db.session.commit()
        except Exception as e:
            app.logger.error(f"!!! Error en tarea para inquilino {subdominio}: {e}")
            _cleanup_db_session(dispose_on_error=True)
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
        # Cada 5 min, todo el día: la hora de corte es configurable por tenant
        # (p. ej. 14:00). Antes solo cubría 6–12 y un corte tarde no se ejecutaba.
        'schedule': crontab(minute='2,7,12,17,22,27,32,37,42,47,52,57'),
    },
    'notif-flush-debounce-digest': {
        'task': 'app.celery_worker.flush_notification_queues',
        'schedule': crontab(minute='*/1'),
    },
}


@celery.task
def sync_scheduler():
    """Despachador configurable: master data nocturno + fichajes/vehículos en vivo."""
    with app.app_context():
        from app.services.sync_config_service import SyncConfigService

        master_needed = False
        fichajes_needed = False
        retro_needed = False
        vehiculos_needed = False
        vehiculos_retro_needed = False

        def _check_tenant_schedule(_tenant_data):
            nonlocal master_needed, fichajes_needed, retro_needed
            nonlocal vehiculos_needed, vehiculos_retro_needed
            if SyncConfigService.should_run_master_sync():
                master_needed = True
            if SyncConfigService.should_run_fichajes_sync():
                fichajes_needed = True
            if SyncConfigService.should_run_fichajes_retro_sync():
                retro_needed = True
            if SyncConfigService.should_run_vehiculos_sync():
                vehiculos_needed = True
            if SyncConfigService.should_run_vehiculos_retro_sync():
                vehiculos_retro_needed = True

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
            if vehiculos_needed:
                app.logger.info(">>> Scheduler: lanzando sync de vehículos en vivo")
                vehiculos_en_vivo.delay()
            if vehiculos_retro_needed:
                app.logger.info(">>> Scheduler: lanzando sync retrospectiva de vehículos")
                vehiculos_retroactivos.delay()
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
def flush_notification_queues():
    """Vacía colas debounce (ventana cerrada) y digest (hora configurada)."""
    with app.app_context():
        from app.services.notification_dispatch_service import (
            flush_debounce_due,
            flush_digest_for_hour,
        )

        def _run(_tenant_data):
            n_deb = flush_debounce_due()
            n_dig = flush_digest_for_hour()
            if n_deb or n_dig:
                app.logger.info(
                    'Notificaciones flush: debounce=%s digest=%s', n_deb, n_dig
                )

        try:
            _for_each_tenant(_run, solo_odoo=False)
        finally:
            _cleanup_db_session()


@celery.task
def verificar_hora_corte():
    with app.app_context():
        from app.models import ConfiguracionGlobal
        from datetime import datetime, timedelta
        from app.services.email_service import enviar_super_reporte_diario
        from app.services.sync_service import procesar_fichajes_diarios
        from app.services.desvio_fichaje_service import consolidar_pendientes_a_ausencia
        from app.utils.timezone_utils import now_local, today_local

        def _run_for_tenant(_tenant_data):
            from app.services.tenant_modules import hora_corte_activa
            if not hora_corte_activa():
                return

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

            app.logger.info(
                f">>> HORA DE REPORTE ({hora_str}). "
                f"Consolidando ausencias de AYER y enviando reporte del día cerrado."
            )
            procesar_fichajes_diarios()
            consolidar_pendientes_a_ausencia(today_local() - timedelta(days=1))
            enviar_super_reporte_diario()

            if not conf_ultimo:
                db.session.add(ConfiguracionGlobal(clave='ultimo_reporte_enviado', valor=hoy_str))
            else:
                conf_ultimo.valor = hoy_str

        try:
            # Todos los tenants activos: con o sin Odoo. Sin ERP el adaptador
            # local no trae fichajes externos, pero sí siembra Sin_Registro
            # desde asignaciones reales y consolida ausencias del día anterior.
            _for_each_tenant(_run_for_tenant, solo_odoo=False)
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
            skipped = False
            err_msg = None
            app.logger.info(f">>> INICIANDO SYNC DE FICHAJES EN VIVO ({tenant_data['subdominio']})")
            try:
                ran = procesar_fichajes_diarios()
                if ran is False:
                    skipped = True
                    app.logger.warning(
                        ">>> Sync fichajes omitida (candado ocupado) en %s — no se marca como hecha.",
                        tenant_data['subdominio'],
                    )
                else:
                    SyncConfigService.mark_fichajes_sync_done()
                    app.logger.info(">>> Sincronización en vivo cruzada correctamente.")
            except Exception as e:
                had_error = True
                err_msg = str(e)
                app.logger.error(f"!!! Error cruzando fichajes en vivo: {e}")
            finally:
                duracion = int((time.time() - t0) * 1000)
                estado = 'error' if had_error else ('parcial' if skipped else 'ok')
                detalle = (
                    'Sincronización omitida: otra instancia en curso.'
                    if skipped
                    else 'Sincronización automática de fichajes del día.'
                )
                db.session.add(SyncLog(
                    fecha=utc_now(),
                    tipo='Fichajes',
                    modo='Automático',
                    nuevos=0, actualizados=0, finalizados=0, errores=1 if had_error else 0,
                    detalles=detalle,
                    estado=estado,
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
def vehiculos_en_vivo():
    with app.app_context():
        from app.services.vehicle_sync_service import run_vehiculos_en_vivo
        from app.services.sync_config_service import SyncConfigService
        from app.utils.timezone_utils import utc_now

        def _run_for_tenant(tenant_data):
            t0 = time.time()
            had_error = False
            err_msg = None
            app.logger.info(f">>> INICIANDO SYNC VEHÍCULOS EN VIVO ({tenant_data['subdominio']})")
            try:
                if not SyncConfigService.get_config()['vehiculos_enabled']:
                    return
                run_vehiculos_en_vivo(modo='Automático')
                SyncConfigService.mark_vehiculos_sync_done()
                app.logger.info(">>> Sincronización de vehículos en vivo completada.")
            except Exception as e:
                had_error = True
                err_msg = str(e)
                app.logger.error(f"!!! Error sync vehículos en vivo: {e}")
            finally:
                if had_error:
                    duracion = int((time.time() - t0) * 1000)
                    db.session.add(SyncLog(
                        fecha=utc_now(),
                        tipo='Vehículos',
                        modo='Automático',
                        nuevos=0, actualizados=0, finalizados=0, errores=1,
                        detalles='Fallo en sincronización de vehículos del día.',
                        estado='error',
                        duracion_ms=duracion,
                        mensaje_error=err_msg,
                    ))

        try:
            _for_each_tenant(_run_for_tenant)
        finally:
            _cleanup_db_session()


@celery.task
def vehiculos_retroactivos():
    with app.app_context():
        from app.services.vehicle_sync_service import run_vehiculos_retro
        from app.services.sync_config_service import SyncConfigService

        def _run_for_tenant(_tenant_data):
            if not SyncConfigService.get_config()['vehiculos_enabled']:
                return
            app.logger.info(">>> INICIANDO SYNC RETROSPECTIVA DE VEHÍCULOS (AUTOMÁTICO)")
            run_vehiculos_retro(modo='Automático')
            SyncConfigService.mark_vehiculos_retro_sync_done()
            app.logger.info(">>> Revisión retrospectiva de vehículos completada.")

        try:
            _for_each_tenant(_run_for_tenant)
        except Exception as e:
            app.logger.error(f"!!! Error en sync retrospectiva de vehículos: {e}")
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


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def process_odoo_hook_task(self, schema_name, resource, meta=None):
    """Un aviso de Odoo: sync del módulo en el tenant que llamó, no en todos."""
    with app.app_context():
        from sqlalchemy import text
        from app.services.odoo_hook_service import run_hook_resource

        try:
            tenant_row = None
            with db.engine.connect() as conn:
                tenant_row = conn.execute(
                    text(
                        'SELECT id, schema_name, subdominio, nombre, modulos_activos '
                        'FROM public.tenants WHERE schema_name = :schema AND is_active = true '
                        'LIMIT 1'
                    ),
                    {'schema': schema_name},
                ).fetchone()
            if not tenant_row:
                app.logger.warning('Hook Odoo: schema %s no encontrado', schema_name)
                return
            tenant_data = {
                'id': tenant_row[0],
                'schema_name': tenant_row[1],
                'subdominio': tenant_row[2],
                'nombre': tenant_row[3],
                'modulos_activos': tenant_row[4] if isinstance(tenant_row[4], dict) else {},
            }
            if not _tenant_has_odoo_module(tenant_data):
                app.logger.warning(
                    'Hook Odoo: tenant %s sin módulo Odoo, se omite', schema_name,
                )
                return
            _set_search_path(schema_name)
            _bind_tenant_context(tenant_data)
            run_hook_resource(resource, meta=meta or {})
        except ValueError as e:
            # Credenciales / URL Odoo: no reintentar en bucle.
            app.logger.error('Hook Odoo %s en %s: %s', resource, schema_name, e)
        except Exception as e:
            app.logger.exception('Hook Odoo %s en %s falló: %s', resource, schema_name, e)
            raise self.retry(exc=e)
        finally:
            _cleanup_db_session()


@celery.task(bind=True, soft_time_limit=3 * 60 * 60, time_limit=3 * 60 * 60 + 10 * 60)
def process_nota_audio_task(self, schema_name: str, job_id: int):
    """Transcribe audio subido y crea nota privada en el tenant indicado."""
    with app.app_context():
        try:
            # Tenant está en public; el job/nota viven en schema_name
            from sqlalchemy import text
            tenant_row = None
            with db.engine.connect() as conn:
                tenant_row = conn.execute(
                    text(
                        'SELECT id, schema_name, subdominio, nombre, modulos_activos '
                        'FROM public.tenants WHERE schema_name = :schema LIMIT 1'
                    ),
                    {'schema': schema_name},
                ).fetchone()

            _set_search_path(schema_name)
            if tenant_row:
                _bind_tenant_context({
                    'id': tenant_row[0],
                    'schema_name': tenant_row[1],
                    'subdominio': tenant_row[2],
                    'nombre': tenant_row[3],
                    'modulos_activos': tenant_row[4] if isinstance(tenant_row[4], dict) else {},
                })

            app.logger.info(
                'process_nota_audio_task start job=%s schema=%s', job_id, schema_name,
            )
            from app.services.nota_audio_service import process_nota_audio_job
            process_nota_audio_job(job_id)
            app.logger.info(
                'process_nota_audio_task done job=%s schema=%s', job_id, schema_name,
            )
        except Exception as e:
            app.logger.exception(
                'Error procesando nota de voz job=%s schema=%s: %s', job_id, schema_name, e,
            )
        finally:
            _cleanup_db_session()


@celery.task
def send_nota_reunion_informe_task(schema_name: str, nota_id: int):
    """PDF de reunión → correo solo al autor."""
    with app.app_context():
        try:
            from sqlalchemy import text

            tenant_row = None
            with db.engine.connect() as conn:
                tenant_row = conn.execute(
                    text(
                        'SELECT id, schema_name, subdominio, nombre, modulos_activos '
                        'FROM public.tenants WHERE schema_name = :schema LIMIT 1'
                    ),
                    {'schema': schema_name},
                ).fetchone()

            _set_search_path(schema_name)
            if tenant_row:
                _bind_tenant_context({
                    'id': tenant_row[0],
                    'schema_name': tenant_row[1],
                    'subdominio': tenant_row[2],
                    'nombre': tenant_row[3],
                    'modulos_activos': tenant_row[4] if isinstance(tenant_row[4], dict) else {},
                })

            from app.services.nota_informe_service import send_informe_to_author
            send_informe_to_author(nota_id, schema_name=schema_name)
        except Exception as e:
            app.logger.warning(
                'Informe reunión nota_id=%s schema=%s: %s', nota_id, schema_name, e,
            )
        finally:
            _cleanup_db_session()
