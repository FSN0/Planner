import os
from flask import Flask, redirect, url_for, request, g, abort, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_mail import Mail
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import text
from .config import Config
import logging
import re

# Instancias globales
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
mail = Mail()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.environ.get('RATELIMIT_STORAGE_URI', Config.CELERY_BROKER_URL),
    default_limits=[],
)

# Patrón seguro para nombres de esquema/subdominio (evita inyección SQL en search_path)
_SCHEMA_SAFE_RE = re.compile(r'^[a-z0-9_]+$')


def is_safe_schema_name(name):
    """Valida que un nombre de esquema solo contenga caracteres seguros."""
    return bool(name) and bool(_SCHEMA_SAFE_RE.match(name))


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    if app.config.get('BEHIND_PROXY'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # --- Verificación de configuración crítica ---
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError(
            "SECRET_KEY no está configurada. Define la variable de entorno SECRET_KEY "
            "(un valor aleatorio y secreto) antes de arrancar la aplicación."
        )

    logging.basicConfig(level=logging.INFO)

    db.init_app(app)

    # ---------------------------------------------------------
    # Tenant ANTES que Flask-Login.
    #
    # load_user() exige g.current_tenant. Si LoginManager corre primero,
    # tras un login correcto el siguiente request ve usuario anónimo y te
    # devuelve al formulario con el flash «Inicio de sesión exitoso».
    # ---------------------------------------------------------
    @app.get('/health')
    def health_check():
        return {'status': 'ok'}, 200

    @app.before_request
    def handle_tenant_routing():
        if request.endpoint in ('static', 'health_check'):
            return

        # API de login para la app externa Alta Odoo (tenant va en el JSON, no en el Host)
        if request.path.startswith('/api/v6/odoo-alta'):
            db.session.execute(text('SET search_path TO public'))
            return

        from app.services.tenant_domain_service import (
            normalize_host,
            resolve_tenant_by_custom_domain,
            resolve_tenant_by_host_alias,
            resolve_tenant_by_subdomain,
            _RESERVED_SUBDOMAINS,
        )

        host = normalize_host(request.host)

        # IP / localhost sin subdominio → marketing (igual que producción).
        es_ip = bool(host) and all(p.isdigit() for p in host.split('.')) and host.count('.') == 3
        if host in ('localhost', 'web', 'host.docker.internal') or es_ip:
            db.session.execute(text("SET search_path TO public"))
            return

        tenant = resolve_tenant_by_custom_domain(host)
        if tenant:
            if not is_safe_schema_name(tenant.schema_name):
                abort(500, description="Configuración de esquema inválida para esta organización.")
            g.current_tenant = tenant
            db.session.execute(text(f"SET search_path TO {tenant.schema_name}, public"))
            return

        tenant = resolve_tenant_by_host_alias(host)
        if tenant:
            if not is_safe_schema_name(tenant.schema_name):
                abort(500, description="Configuración de esquema inválida para esta organización.")
            g.current_tenant = tenant
            db.session.execute(text(f"SET search_path TO {tenant.schema_name}, public"))
            return

        parts = host.split('.')
        subdomain = None

        # empresa.localhost, empresa.signaplan.com, empresa.<ip>.sslip.io (parts[0])
        if len(parts) == 2 and parts[1] == 'localhost' and parts[0] not in ('localhost', 'www'):
            subdomain = parts[0]
        # Producción: dominio raíz (ej: signaplan.com) → esquema público
        elif len(parts) == 2:
            db.session.execute(text("SET search_path TO public"))
            return
        elif len(parts) > 2:
            subdomain = parts[0]
        else:
            subdomain = None

        if subdomain in _RESERVED_SUBDOMAINS:
            db.session.execute(text("SET search_path TO public"))
            return

        tenant = resolve_tenant_by_subdomain(subdomain)
        if tenant:
            if not is_safe_schema_name(tenant.schema_name):
                abort(500, description="Configuración de esquema inválida para esta organización.")
            g.current_tenant = tenant
            db.session.execute(text(f"SET search_path TO {tenant.schema_name}, public"))
            return

        if subdomain:
            abort(404, description="La organización solicitada no existe o se encuentra inactiva.")
        db.session.execute(text("SET search_path TO public"))

    # LoginManager DESPUÉS del tenant: así load_user ya tiene g.current_tenant.
    login_manager.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    csrf.init_app(app)
    if app.config.get('TESTING'):
        app.config['RATELIMIT_ENABLED'] = False
    limiter.init_app(app)

    # Idioma: tras tenant + sesión, para poder leer preferencia del usuario.
    @app.before_request
    def _resolve_locale():
        from app.services.i18n_service import detect_request_locale
        user = None
        try:
            if getattr(current_user, 'is_authenticated', False):
                user = current_user
        except Exception:
            user = None
        g.locale = detect_request_locale(user=user)

    @app.context_processor
    def inject_i18n():
        from app.services.i18n_service import (
            _,
            frontend_catalog,
            get_locale,
            role_label,
            LOCALE_LABELS,
            SUPPORTED_LOCALES,
        )
        return dict(
            _=_,
            current_locale=get_locale(),
            frontend_i18n=frontend_catalog(),
            supported_locales=SUPPORTED_LOCALES,
            locale_labels=LOCALE_LABELS,
            role_label=role_label,
        )

    # Exponemos el token CSRF en una cookie legible por JS (patrón double-submit)
    # para que las peticiones AJAX/fetch existentes puedan enviarlo en la cabecera.
    @app.after_request
    def set_csrf_cookie(response):
        try:
            response.set_cookie(
                'csrf_token',
                generate_csrf(),
                secure=app.config.get('SESSION_COOKIE_SECURE', False),
                samesite='Lax',
            )
        except Exception:
            pass
        return response

    @app.teardown_appcontext
    def _shutdown_session(exception=None):
        # Si algo dejó la transacción abortada, no envenene la siguiente petición.
        if exception is not None:
            try:
                db.session.rollback()
            except Exception:
                pass
        try:
            db.session.remove()
        except Exception:
            pass

    @app.after_request
    def translate_html_ui(response):
        """Traduce textos de interfaz del HTML al idioma activo."""
        try:
            from app.services.i18n_service import get_locale, translate_html_document
            if get_locale() == 'es':
                return response
            ctype = (response.content_type or '').lower()
            if 'text/html' not in ctype:
                return response
            if request.path.startswith('/static'):
                return response
            html = response.get_data(as_text=True)
            translated = translate_html_document(html)
            if translated != html:
                response.set_data(translated)
        except Exception:
            pass
        return response

    # ---------------------------------------------------------
    # Importación de Blueprints
    # ---------------------------------------------------------
    from app.auth.routes import auth_bp
    from app.jefe_obra.routes import jefe_bp
    from app.admin.routes import admin_bp
    from app.routes import main_bp
    from app.notas.routes import notas_bp
    from app.api.routes import api_bp
    from app.sync.routes import sync_bp
    from app.api.asignaciones import asignaciones_api
    from app.api.vehiculos import vehiculos_api
    from app.api.ausencias import ausencias_api
    from app.superadmin import superadmin_bp
    from app.operarios import operarios_bp
    from app.empleado import empleado_bp
    from app.marketing.routes import marketing_bp

    # ¡AQUÍ ESTÁ LA SOLUCIÓN!
    # Forzamos el 'url_prefix' para que ninguna ruta se vuelva a quedar en blanco
    app.register_blueprint(main_bp)
    app.register_blueprint(marketing_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(jefe_bp, url_prefix='/jefe')
    app.register_blueprint(notas_bp, url_prefix='/notas')
    app.register_blueprint(api_bp, url_prefix='/api/v6')
    app.register_blueprint(sync_bp, url_prefix='/sync')
    app.register_blueprint(asignaciones_api, url_prefix='/api')
    app.register_blueprint(vehiculos_api, url_prefix='/api')
    app.register_blueprint(ausencias_api, url_prefix='/api')
    app.register_blueprint(superadmin_bp, url_prefix='/superadmin')
    # El prefijo lo declara el propio blueprint: la PWA lo necesita fijo en /mi
    # porque el alcance del service worker se registra contra esa ruta.
    app.register_blueprint(operarios_bp)
    app.register_blueprint(empleado_bp)

    from app.cli import register_cli
    register_cli(app)

    # ---------------------------------------------------------
    # Registro de utilidades de Jinja
    # ---------------------------------------------------------
    from app.utils.date_utils import get_weekday_initial
    from app.utils.timezone_utils import (
        format_datetime, format_time, format_date, today_local,
        get_user_timezone, get_app_timezone, COMMON_TIMEZONES, timezone_label,
    )
    app.jinja_env.globals.update(get_weekday_initial=get_weekday_initial)
    app.jinja_env.filters['format_dt'] = format_datetime
    app.jinja_env.filters['format_time'] = format_time
    app.jinja_env.filters['format_date'] = format_date

    # Importación local de constantes para evitar referencias circulares
    from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_OPERARIO, ROLE_RRHH, ROLE_LABORAL

    @app.context_processor
    def inject_notifications():
        from app.models import Solicitud, SolicitudVehiculo, ROLE_ADMIN, ROLE_JEFE

        pending_count = 0
        unread_logs_count = 0
        unread_laboral_count = 0

        if current_user.is_authenticated:
            if current_user.role == ROLE_ADMIN:
                pending_count = Solicitud.query.filter(
                    Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])
                ).count()
                pending_count += SolicitudVehiculo.query.filter(
                    SolicitudVehiculo.estado.in_(['PENDIENTE', 'EN_PROCESO'])
                ).count()

                from app.services.log_notification_service import (
                    get_total_unread_logs,
                    get_unread_laboral_logs,
                )
                unread_logs_count = get_total_unread_logs(current_user.id)
                unread_laboral_count = get_unread_laboral_logs(current_user.id)
            elif current_user.role in (ROLE_LABORAL, ROLE_RRHH):
                from app.services.log_notification_service import get_unread_laboral_logs
                unread_laboral_count = get_unread_laboral_logs(current_user.id)

            # 2. JEFE DE OBRA: solicitudes abiertas de sus obras o creadas por él
            elif current_user.role == ROLE_JEFE:
                from sqlalchemy import or_
                from app.models import Obra
                pending_count = Solicitud.query.join(Obra).filter(
                    or_(
                        Solicitud.requested_by_id == current_user.id,
                        Obra.jefe_obra_id == current_user.id,
                    ),
                    Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO']),
                ).count()
                pending_count += SolicitudVehiculo.query.filter(
                    SolicitudVehiculo.requested_by_id == current_user.id,
                    SolicitudVehiculo.estado.in_(['PENDIENTE', 'EN_PROCESO']),
                ).count()

        tz_ctx = {}
        if current_user.is_authenticated:
            tz_ctx = dict(
                user_timezone=get_user_timezone(current_user),
                app_timezone=get_app_timezone(),
                today_local=today_local(),
                timezone_options=COMMON_TIMEZONES,
            )
        modulos_activos = {}
        tenant_has_odoo = False
        tenant_has_odoo_alta = False
        tenant_has_integrations = False
        tenant_has_registro_jornada = True
        tenant_has_fichaje_operario = False
        if current_user.is_authenticated:
            tenant = getattr(g, 'current_tenant', None)
            if tenant:
                modulos_activos = getattr(tenant, 'modulos_activos', {}) or {}
                tenant_has_odoo = bool(modulos_activos.get('odoo'))
                tenant_has_odoo_alta = bool(modulos_activos.get('odoo_alta'))
                tenant_has_integrations = tenant_has_odoo or tenant_has_odoo_alta
                tenant_has_registro_jornada = bool(
                    modulos_activos.get('registro_jornada', True)
                )
                tenant_has_fichaje_operario = bool(
                    modulos_activos.get('fichaje_operario')
                )

        from app.services.permission_service import (
            user_can, is_laboral, is_admin, can_resolve_fichajes,
        )
        mostrar_onboarding = False
        if current_user.is_authenticated and current_user.role == ROLE_ADMIN:
            try:
                from app.services.onboarding_service import necesita_onboarding
                mostrar_onboarding = necesita_onboarding()
            except Exception:
                mostrar_onboarding = False
        demo_data_activa = False
        if current_user.is_authenticated and current_user.role == ROLE_ADMIN:
            try:
                from app.services.demo_data_service import demo_activa
                demo_data_activa = demo_activa()
            except Exception:
                demo_data_activa = False
        return dict(
            pending_notifications=pending_count,
            unread_logs_count=unread_logs_count,
            unread_laboral_count=unread_laboral_count,
            modulos_activos=modulos_activos,
            tenant_has_odoo=tenant_has_odoo,
            tenant_has_odoo_alta=tenant_has_odoo_alta,
            tenant_has_integrations=tenant_has_integrations,
            tenant_has_registro_jornada=tenant_has_registro_jornada,
            tenant_has_fichaje_operario=tenant_has_fichaje_operario,
            mostrar_onboarding=mostrar_onboarding,
            demo_data_activa=demo_data_activa,
            user_can=user_can,
            is_laboral=is_laboral,
            is_admin=is_admin,
            can_resolve_fichajes=can_resolve_fichajes,
            **tz_ctx,
        )

    # ---------------------------------------------------------
    # Redirecciones y Seguridad
    # ---------------------------------------------------------
    def redirect_by_role(user):
        """Redirige al usuario a su panel correspondiente según su rol."""
        if user.role == ROLE_ADMIN:
            return redirect(url_for('admin.panel'))
        elif user.role == ROLE_JEFE:
            return redirect(url_for('jefe.panel'))
        elif user.role in (ROLE_LABORAL, ROLE_RRHH):
            return redirect(url_for('admin.panel_laboral'))
        elif user.role == ROLE_OPERARIO:
            if getattr(user, 'web_access', False):
                return redirect(url_for('empleado.inicio'))
            from flask_login import logout_user
            logout_user()
            from flask import flash
            flash('Tu perfil no tiene acceso a la aplicación.', 'warning')
            return redirect(url_for('auth.login'))
        return redirect(url_for('auth.login'))

    @login_manager.unauthorized_handler
    def handle_needs_login():
        if current_user.is_authenticated:
            return redirect_by_role(current_user)
        return redirect(url_for('auth.login'))

    @app.errorhandler(403)
    def handle_forbidden(e):
        if current_user.is_authenticated:
            return redirect_by_role(current_user)
        return redirect(url_for('auth.login'))

    return app
