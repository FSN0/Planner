from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_mail import Mail
from .config import Config
import logging

# Instancias globales
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
mail = Mail()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    logging.basicConfig(level=logging.INFO)

    # Inicialización de extensiones
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)

    # ---------------------------------------------------------
    # Importación de Blueprints (Limpios y sin duplicados)
    # ---------------------------------------------------------
    from app.auth.routes import auth_bp
    from app.jefe_obra.routes import jefe_bp
    from app.admin.routes import admin_bp
    from app.routes import main_bp
    from app.notas.routes import notas_bp
    from app.api.routes import api_bp 
    from app.sync.routes import sync_bp
    from app.api.asignaciones import asignaciones_api
    app.register_blueprint(asignaciones_api, url_prefix='/api')

    # ---------------------------------------------------------
    # Registro de Blueprints y utilidades de Jinja
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

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(jefe_bp)
    app.register_blueprint(notas_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(sync_bp)

    # Importación local de constantes para evitar referencias circulares
    from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_OPERARIO, ROLE_RRHH

    @app.context_processor
    def inject_notifications():
        from app.models import Solicitud, ROLE_ADMIN, ROLE_JEFE
        
        pending_count = 0
        unread_logs_count = 0 # <-- NUEVO CONTADOR

        if current_user.is_authenticated:
            # 1. ADMIN: Solo contamos cuántas hay PENDIENTES o EN_PROCESO
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
    # Función auxiliar para unificar las redirecciones
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

    # ---------------------------------------------------------
    # Manejo de Errores de Autenticación / Autorización
    # ---------------------------------------------------------
    @login_manager.unauthorized_handler
    def handle_needs_login():
        # Si no tiene sesión (401), o la perdió
        if current_user.is_authenticated:
            return redirect_by_role(current_user)
        return redirect(url_for('auth.login'))

    @app.errorhandler(403)
    def handle_forbidden(e):
        # Si intenta entrar a una ruta prohibida para su rol (ej: jefe a admin)
        if current_user.is_authenticated:
            return redirect_by_role(current_user)
        return redirect(url_for('auth.login'))

    return app