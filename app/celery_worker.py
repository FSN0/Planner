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
        try:
            from app.sync.dispatcher import get_sync_adapter

            _cleanup_db_session()
            for tenant_data in _load_active_tenants():
                subdominio = tenant_data['subdominio']
                try:
                    _set_search_path(tenant_data['schema_name'])
                    _bind_tenant_context(tenant_data)
                    app.logger.info(f">>> SYNC FICHAJES EN VIVO -> {subdominio.upper()}")

                    service = get_sync_adapter()
                    service.get_fichajes_diarios()
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    app.logger.error(f"!!! Error sync vivo inquilino {subdominio}: {e}")
        finally:
            _cleanup_db_session()

@celery.task
def auto_sync_odoo():
    with app.app_context():
        from app.models import Obra, User, Company, SyncLog

        try:
            from app.sync.dispatcher import get_sync_adapter

            _cleanup_db_session()
            for tenant_data in _load_active_tenants():
                subdominio = tenant_data['subdominio']
                try:
                    _set_search_path(tenant_data['schema_name'])
                    _bind_tenant_context(tenant_data)
                    app.logger.info(f">>> SYNC NOCTURNA TOTAL -> {subdominio.upper()}")

                    service = get_sync_adapter()
                    ahora = datetime.now()

                    diff_obras = service.get_diff_obras()
                    nuevas_limpias = [o for o in diff_obras['nuevas'] if not o.get('warn_jefe') and not o.get('warn_encargado')]
                    act_limpias = [o for o in diff_obras['actualizadas'] if not o.get('warn_jefe') and not o.get('warn_encargado')]

                    for obj in nuevas_limpias:
                        f_inicio = datetime.strptime(obj['fecha_inicio'], "%Y-%m-%d").date() if obj.get('fecha_inicio') else None
                        nueva_obra = Obra(
                            codigo=obj['codigo'],
                            nombre=obj['nombre'],
                            descripcion=obj.get('cliente', ''),
                            fecha_inicio=f_inicio,
                            estado='Pendiente',
                            jefe_obra_id=obj.get('jefe_obra_id'),
                            encargado_id=obj.get('encargado_id'),
                            fecha_importacion=ahora,
                            external_ids={'odoo': str(obj['odoo_id'])}
                        )
                        db.session.add(nueva_obra)

                    for obj in act_limpias:
                        obra = Obra.query.get(obj['local_id'])
                        if obra:
                            obra.external_ids = obra.external_ids or {}
                            obra.external_ids['odoo'] = str(obj['odoo_id'])
                            obra.codigo = obj['codigo']
                            obra.nombre = obj['nombre']
                            obra.descripcion = obj.get('cliente', '')
                            obra.fecha_importacion = ahora
                            if obj.get('fecha_inicio'):
                                obra.fecha_inicio = datetime.strptime(obj['fecha_inicio'], "%Y-%m-%d").date()
                            if obj.get('jefe_obra_id'):
                                obra.jefe_obra_id = obj['jefe_obra_id']
                            if obj.get('encargado_id'):
                                obra.encargado_id = obj.get('encargado_id')
                            db.session.add(obra)

                    for obj in diff_obras['finalizadas']:
                        obra = Obra.query.get(obj['local_id'])
                        if obra:
                            obra.estado = 'Finalizada'
                            obra.fecha_fin = ahora.date()
                            obra.fecha_importacion = ahora

                    diff_emp = service.get_diff_empleados()
                    default_company = Company.query.first()
                    default_company_id = default_company.id if default_company else None

                    for obj in diff_emp['nuevos']:
                        nuevo_user = User(
                            name=obj['name'],
                            lastname=obj['lastname'],
                            dni=obj['dni'],
                            email=obj['email'],
                            role=obj['role'],
                            categoria_profesional=obj.get('categoria_profesional', 'Sin definir'),
                            company_id=default_company_id,
                            active=True,
                            password_hash=generate_password_hash(secrets.token_urlsafe(16)),
                            external_ids={'odoo': str(obj['odoo_id'])}
                        )
                        db.session.add(nuevo_user)

                    for obj in [e for e in diff_emp['actualizados'] if not e.get('conflicto')]:
                        user = User.query.get(obj['local_id'])
                        if user:
                            user.external_ids = user.external_ids or {}
                            user.external_ids['odoo'] = str(obj['odoo_id'])
                            user.name = obj['name']
                            user.lastname = obj['lastname']
                            user.role = obj['role']
                            user.categoria_profesional = obj.get('categoria_profesional', user.categoria_profesional)
                            db.session.add(user)

                    db.session.add(SyncLog(
                        fecha=ahora, tipo='Global', modo='Automático',
                        detalles="Sync completada para este inquilino."
                    ))
                    db.session.commit()
                    app.logger.info(f"    └─ Sincronización finalizada: {subdominio}")
                except Exception as e:
                    db.session.rollback()
                    app.logger.error(f"!!! Error crítico en sync nocturna para {subdominio}: {e}")
        finally:
            _cleanup_db_session()
   