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
    from app.currantes.routes import currantes_bp
    from app.jefe_obra.routes import jefe_bp
    from app.rrhh.routes import rrhh_bp
    from app.admin.routes import admin_bp
    from app.routes import main_bp
    from app.notas.routes import notas_bp
    from app.api.routes import api_bp 
    from app.sync.routes import sync_bp
    from app.api.asignaciones import asignaciones_api
    app.register_blueprint(asignaciones_api, url_prefix='/api')
# (Tus importaciones anteriores...)
    from app.sync.routes import sync_bp
    from app.api.asignaciones import asignaciones_api
    
    # 1. IMPORTA AQUÍ EL NUEVO BLUEPRINT:
    from app.superadmin import superadmin_bp 

    app.register_blueprint(asignaciones_api, url_prefix='/api')




    
    # 2. REGÍSTRALO AQUÍ:
    app.register_blueprint(superadmin_bp)
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
    app.register_blueprint(currantes_bp)
    app.register_blueprint(notas_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(sync_bp)

    # Importación local de constantes para evitar referencias circulares
    from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_RRHH, ROLE_CURRANTE

    @app.context_processor
    def inject_notifications():
        from app.models import Solicitud, ROLE_ADMIN, ROLE_JEFE
        
        pending_count = 0

        if current_user.is_authenticated:
            # 1. ADMIN: Solo contamos cuántas hay PENDIENTES o EN_PROCESO
            if current_user.role == ROLE_ADMIN:
                pending_count = Solicitud.query.filter(
                    Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])
                ).count()

            # 2. JEFE DE OBRA: Solo contamos cuántas de SUS solicitudes tienen feedback
            elif current_user.role == ROLE_JEFE:
                pending_count = Solicitud.query.filter(
                    Solicitud.requested_by_id == current_user.id,
                    Solicitud.estado.in_(['CUMPLIDA', 'DENEGADA', 'CERRADA_PARCIAL'])
                ).count()

        # Ya no enviamos 'notifications' vacío, solo el conteo
        return dict(pending_notifications=pending_count)

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
    # ---------------------------------------------------------
    # Enrutamiento Dinámico Multi-Tenant (PostgreSQL Schemas)
    # ---------------------------------------------------------
    from flask import request, g, abort
    from sqlalchemy import text

    @app.before_request
    def handle_tenant_routing():
        """
        Intercepta la petición, analiza el subdominio y conmuta el 
        search_path de PostgreSQL al esquema aislado del inquilino.
        """
        # Omitir la lógica de esquemas para archivos estáticos (rendimiento)
        if request.endpoint == 'static':
            return

        host = request.host  # Ej: 'soltec.tusaas.com:5000' o 'localhost:5000'
        parts = host.split('.')

        # Identificar si existe un subdominio válido
        if len(parts) > 2 and parts[0] not in ['www', 'admin']:
            subdomain = parts[0]
            
            from app.models import Tenant
            # Buscamos el inquilino en la tabla global del esquema público
            tenant = Tenant.query.filter_by(subdomain=subdomain, is_active=True).first()
            
            if tenant:
                g.current_tenant = tenant
                # Comando clave de Postgres: Prioriza el esquema del inquilino, manteniendo 'public' como fallback
                db.session.execute(text(f"SET search_path TO {tenant.schema_name}, public"))
            else:
                abort(404, description="La organización solicitada no existe o se encuentra inactiva.")
        else:
            # Si acceden desde el dominio principal (Landing Page corporativa o panel de SuperAdmin)
            db.session.execute(text("SET search_path TO public"))
    return app