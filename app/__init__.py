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
    from app.operarios.routes import operarios_bp
    from app.jefe_obra.routes import jefe_bp
    from app.rrhh.routes import rrhh_bp
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
    app.jinja_env.globals.update(get_weekday_initial=get_weekday_initial)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(jefe_bp)
    app.register_blueprint(rrhh_bp)
    app.register_blueprint(operarios_bp)
    app.register_blueprint(notas_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(sync_bp)

    # Importación local de constantes para evitar referencias circulares
    from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_RRHH, ROLE_OPERARIO

    @app.context_processor
    def inject_notifications():
        from app.models import Solicitud, ROLE_ADMIN, ROLE_JEFE, SystemLog, LogPreference
        
        pending_count = 0
        unread_logs_count = 0 # <-- NUEVO CONTADOR

        if current_user.is_authenticated:
            # 1. ADMIN: Solo contamos cuántas hay PENDIENTES o EN_PROCESO
            if current_user.role == ROLE_ADMIN:
                pending_count = Solicitud.query.filter(
                    Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])
                ).count()
                
                # --- NUEVO: CÁLCULO DE LA BURBUJA DE LOGS ---
                prefs = LogPreference.query.filter_by(user_id=current_user.id, is_active=True).all()
                for pref in prefs:
                    # Cuenta cuántos logs de esta categoría se han creado DESPUÉS de su última lectura
                    unread_logs_count += SystemLog.query.filter(
                        SystemLog.category == pref.category,
                        SystemLog.timestamp > pref.last_read_at
                    ).count()
                # --------------------------------------------

            # 2. JEFE DE OBRA: Solo contamos cuántas de SUS solicitudes tienen feedback
            elif current_user.role == ROLE_JEFE:
                pending_count = Solicitud.query.filter(
                    Solicitud.requested_by_id == current_user.id,
                    Solicitud.estado.in_(['CUMPLIDA', 'DENEGADA', 'CERRADA_PARCIAL'])
                ).count()

        # Ya no enviamos 'notifications' vacío, solo el conteo
        return dict(pending_notifications=pending_count, unread_logs_count=unread_logs_count)

    # ---------------------------------------------------------
    # Función auxiliar para unificar las redirecciones
    # ---------------------------------------------------------
    def redirect_by_role(user):
        """Redirige al usuario a su panel correspondiente según su rol."""
        if user.role == ROLE_ADMIN:
            return redirect(url_for('admin.panel'))
        elif user.role == ROLE_JEFE:
            return redirect(url_for('jefe.panel'))
        elif user.role == ROLE_RRHH:
            return redirect(url_for('rrhh.panel'))
        else:
            return redirect(url_for('main.dashboard'))

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