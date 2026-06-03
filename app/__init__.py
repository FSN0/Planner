from flask import Flask, redirect, url_for, request, g, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_mail import Mail
from sqlalchemy import text
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
    # Importación de Blueprints
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
    app.jinja_env.globals.update(get_weekday_initial=get_weekday_initial)



    # Importación local de constantes para evitar referencias circulares
    from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_RRHH, ROLE_OPERARIO

    @app.context_processor
    def inject_notifications():
        from app.models import Solicitud, ROLE_ADMIN, ROLE_JEFE
        pending_count = 0

        if current_user.is_authenticated:
            if current_user.role == ROLE_ADMIN:
                pending_count = Solicitud.query.filter(
                    Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])
                ).count()
            elif current_user.role == ROLE_JEFE:
                pending_count = Solicitud.query.filter(
                    Solicitud.requested_by_id == current_user.id,
                    Solicitud.estado.in_(['CUMPLIDA', 'DENEGADA', 'CERRADA_PARCIAL'])
                ).count()

        return dict(pending_notifications=pending_count)

    # ---------------------------------------------------------
    # Redirecciones y Seguridad
    # ---------------------------------------------------------
    def redirect_by_role(user):
        """Redirige al usuario a su panel correspondiente según su rol."""
        if user.role == ROLE_ADMIN: return redirect(url_for('admin.panel'))
        elif user.role == ROLE_JEFE: return redirect(url_for('jefe.panel'))
        elif user.role == ROLE_RRHH: return redirect(url_for('rrhh.panel'))
        else: return redirect(url_for('main.dashboard'))

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
        if host == 'localhost' or host.replace('.', '').isnumeric():
            db.session.execute(text("SET search_path TO public"))
            return

        # Separamos la URL por puntos para sacar la empresa
        parts = host.split('.')
        subdomain = parts[0]

        if subdomain not in ['www', 'admin', 'superadmin']:
            from app.models import Tenant
            tenant = Tenant.query.filter_by(subdominio=subdomain, is_active=True).first()
            
            if tenant:
                g.current_tenant = tenant
                db.session.execute(text(f"SET search_path TO {tenant.schema_name}, public"))
            else:
                abort(404, description="La organización solicitada no existe o se encuentra inactiva.")
        else:
            db.session.execute(text("SET search_path TO public"))

    return app