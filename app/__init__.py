import os
from flask import Flask, redirect, url_for, request, g, abort
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

    # --- Verificación de configuración crítica ---
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError(
            "SECRET_KEY no está configurada. Define la variable de entorno SECRET_KEY "
            "(un valor aleatorio y secreto) antes de arrancar la aplicación."
        )

    logging.basicConfig(level=logging.INFO)

    # Inicialización de extensiones
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    csrf.init_app(app)
    if app.config.get('TESTING'):
        app.config['RATELIMIT_ENABLED'] = False
    limiter.init_app(app)

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
    from app.superadmin import superadmin_bp 

    # ¡AQUÍ ESTÁ LA SOLUCIÓN! 
    # Forzamos el 'url_prefix' para que ninguna ruta se vuelva a quedar en blanco
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(jefe_bp, url_prefix='/jefe')
    app.register_blueprint(rrhh_bp, url_prefix='/rrhh')
    app.register_blueprint(operarios_bp, url_prefix='/operarios')
    app.register_blueprint(notas_bp, url_prefix='/notas')
    app.register_blueprint(api_bp, url_prefix='/api/v6')
    app.register_blueprint(sync_bp, url_prefix='/sync')
    app.register_blueprint(asignaciones_api, url_prefix='/api')
    app.register_blueprint(superadmin_bp, url_prefix='/superadmin')

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
    from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_OPERARIO, ROLE_RRHH

    @app.context_processor
    def inject_notifications():
        from app.models import Solicitud, ROLE_ADMIN, ROLE_JEFE
        
        pending_count = 0
        unread_logs_count = 0 # <-- NUEVO CONTADOR

        if current_user.is_authenticated:
            if current_user.role == ROLE_ADMIN:
                pending_count = Solicitud.query.filter(
                    Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])
                ).count()
                
                from app.services.log_notification_service import get_total_unread_logs
                unread_logs_count = get_total_unread_logs(current_user.id)

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

        tz_ctx = {}
        if current_user.is_authenticated:
            tz_ctx = dict(
                user_timezone=get_user_timezone(current_user),
                app_timezone=get_app_timezone(),
                today_local=today_local(),
                timezone_options=COMMON_TIMEZONES,
            )
        return dict(
            pending_notifications=pending_count,
            unread_logs_count=unread_logs_count,
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
        elif user.role in (ROLE_RRHH, ROLE_OPERARIO):
            from flask_login import logout_user
            logout_user()
            from flask import flash
            flash('Tu perfil no tiene acceso a la aplicación.', 'warning')
            return redirect(url_for('auth.login'))
        return redirect(url_for('auth.login'))

    @login_manager.unauthorized_handler
    def handle_needs_login():
        if current_user.is_authenticated: return redirect_by_role(current_user)
        return redirect(url_for('auth.login'))

    @app.errorhandler(403)
    def handle_forbidden(e):
        if current_user.is_authenticated: return redirect_by_role(current_user)
        return redirect(url_for('auth.login'))

    # ---------------------------------------------------------
    # Enrutamiento Dinámico Multi-Tenant (PostgreSQL Schemas)
    # ---------------------------------------------------------
    @app.before_request
    def handle_tenant_routing():
        if request.endpoint == 'static':
            return

        # Limpiamos el puerto por si el host viene como "demo.localhost:5000"
        host = request.host.split(':')[0]

        # Si acceden desde localhost o IP pura, van al esquema principal
        if host in ['localhost', 'web'] or host.replace('.', '').isnumeric():
            db.session.execute(text("SET search_path TO public"))
            return

        # Separamos la URL por puntos para sacar la empresa
       # Separamos la URL por puntos para sacar la empresa
        parts = host.split('.')
        
        # Si acceden al dominio raíz (ej: signaplan.com), parts tendrá solo 2 elementos.
        # Lo enviamos directamente al esquema público.
        if len(parts) == 2:
            db.session.execute(text("SET search_path TO public"))
            return

        subdomain = parts[0]

        # Añadimos tu dominio base 'signaplan' a la lista por seguridad adicional
        if subdomain not in ['www', 'admin', 'superadmin', 'signaplan']:
            from app.models import Tenant
            tenant = Tenant.query.filter_by(subdominio=subdomain, is_active=True).first()
            
            if tenant:
                # Defensa en profundidad: nunca interpolar un schema_name no validado
                if not is_safe_schema_name(tenant.schema_name):
                    abort(500, description="Configuración de esquema inválida para esta organización.")
                g.current_tenant = tenant
                db.session.execute(text(f"SET search_path TO {tenant.schema_name}, public"))
            else:
                abort(404, description="La organización solicitada no existe o se encuentra inactiva.")
        else:
            db.session.execute(text("SET search_path TO public"))

    return app