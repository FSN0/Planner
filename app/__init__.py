import os
from flask import Flask, redirect, url_for, request, g, abort, current_app, session, has_app_context
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_mail import Mail
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import event, text
from sqlalchemy.orm import Session as SASession
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


def _restore_tenant_search_path(session, transaction, connection):
    """Reaplica el schema del tenant al abrir transacción (pool / post-commit)."""
    if not has_app_context():
        return
    tenant = getattr(g, 'current_tenant', None)
    schema = getattr(tenant, 'schema_name', None)
    if schema and is_safe_schema_name(schema):
        connection.execute(text(f'SET search_path TO {schema}, public'))


if not event.contains(SASession, 'after_begin', _restore_tenant_search_path):
    event.listen(SASession, 'after_begin', _restore_tenant_search_path)


def create_app():
    from app.services.i18n_service import install_flask_flash_i18n
    install_flask_flash_i18n()

    app = Flask(__name__)
    app.config.from_object(Config)
    # Config.TESTING se evalúa al importar el módulo; leer el env aquí
    # para que Flask-Mail no intente SMTP en pytest.
    if os.environ.get('TESTING', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        app.config['TESTING'] = True
        app.config['MAIL_SUPPRESS_SEND'] = True

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

        # SEO: un solo host indexable. Si Caddy no redirige www, la app sí.
        if host == 'www.signaplan.com':
            from app.services.seo_origin_service import marketing_origin
            dest = marketing_origin() + request.full_path
            if dest.endswith('?'):
                dest = dest[:-1]
            return redirect(dest, code=301)

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

    @app.before_request
    def _mantener_sesion_impersonacion():
        """Evita que la cookie remember del admin rompa la suplantación."""
        try:
            from app.services.impersonation_service import (
                impersonacion_activa,
                reparar_sesion_impersonacion,
            )
            if impersonacion_activa():
                reparar_sesion_impersonacion()
        except Exception:
            pass

    @app.context_processor
    def inject_i18n():
        from flask import url_for as _url_for
        from app.services.i18n_service import (
            _,
            frontend_catalog,
            get_locale,
            hreflang_links,
            locale_href,
            locale_meta,
            locale_og,
            marketing_path,
            role_label,
            LOCALE_LABELS,
            SUPPORTED_LOCALES,
        )

        def mkt_url(endpoint, **values):
            path = _url_for(endpoint, **values)
            return marketing_path(path, get_locale())

        def mkt_home():
            return marketing_path('/', get_locale())

        return dict(
            _=_,
            current_locale=get_locale(),
            frontend_i18n=frontend_catalog(),
            supported_locales=SUPPORTED_LOCALES,
            locale_labels=LOCALE_LABELS,
            role_label=role_label,
            locale_meta=locale_meta(),
            locale_og=locale_og,
            hreflang_links=hreflang_links,
            locale_href=locale_href,
            marketing_path=marketing_path,
            mkt_url=mkt_url,
            mkt_home=mkt_home,
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
    def _set_content_language(response):
        """Idioma real de la respuesta (SEO + cookie si vino de /en/...)."""
        try:
            from app.services.i18n_service import get_locale, set_locale_cookie
            loc = get_locale()
            response.headers.setdefault('Content-Language', loc)
            from app.services.tenant_domain_service import is_marketing_host, normalize_host
            if request.environ.get('HTTP_X_SIGNAPLAN_LOCALE') or is_marketing_host(
                normalize_host(request.host)
            ):
                set_locale_cookie(response, loc)
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
    from app.services.seo_origin_service import marketing_origin, marketing_url
    app.jinja_env.globals.update(
        get_weekday_initial=get_weekday_initial,
        marketing_origin=marketing_origin,
        marketing_url=marketing_url,
    )
    from app.utils.nav_back import resolve_back_url, url_with_back
    app.jinja_env.globals.update(
        resolve_back_url=resolve_back_url,
        url_with_back=url_with_back,
    )
    from app.services.i18n_service import translate_log_action, translate_log_detail
    app.jinja_env.filters['format_dt'] = format_datetime
    app.jinja_env.filters['format_time'] = format_time
    app.jinja_env.filters['format_date'] = format_date
    app.jinja_env.filters['tlog_action'] = translate_log_action
    app.jinja_env.filters['tlog_detail'] = translate_log_detail

    # Importación local de constantes para evitar referencias circulares
    from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_OPERARIO, ROLE_RRHH, ROLE_LABORAL

    @app.context_processor
    def inject_notifications():
        from app.models import Solicitud, SolicitudVehiculo, ROLE_ADMIN, ROLE_JEFE
        import time as _time

        # Tras verificar email solo pintamos una pantalla mínima: no construir sidebar/badges.
        if (request.endpoint or '') == 'auth.verificar_email':
            return dict(
                pending_notifications=0,
                unread_logs_count=0,
                unread_laboral_count=0,
                modulos_activos={},
                tenant_has_odoo=False,
                tenant_has_odoo_alta=False,
                tenant_has_soltec_portal_sso=False,
                tenant_has_integrations=False,
                tenant_has_registro_jornada=True,
                tenant_has_fichaje_operario=False,
                tenant_usa_acceso_pin=False,
                muestra_auditoria_fichajes=False,
                puede_ver_estado_fichaje=False,
                impersonacion_activa=False,
                impersonador_label=None,
                tenant_has_avisos_laborales=False,
                tenant_has_notas=False,
                tenant_has_valoraciones=False,
                tenant_has_auditoria_vehiculos=False,
                jefes_asignan_directo=False,
                mostrar_onboarding=False,
                onboarding_import_done={},
                onboarding_fichaje_asked=False,
                onboarding_fichaje_activo=False,
                demo_data_activa=False,
                sidebar_nav=None,
            )

        pending_count = 0
        unread_logs_count = 0
        unread_laboral_count = 0

        # Primeros pasos / onboarding: priorizar TTFB; los badges no son críticos ahí.
        _light_endpoints = {
            'admin.primeros_pasos',
            'admin.api_tour_fichaje',
            'admin.api_tour_fichaje_demo',
        }
        skip_heavy_badges = (request.endpoint or '') in _light_endpoints

        if current_user.is_authenticated:
            try:
                # Cache corta en sesión: la guía dispara muchas navegaciones seguidas
                # y los COUNT sobre system_logs pueden congelar workers.
                _badge_ttl = 45
                _badge_key = f'_nav_badges_{current_user.id}'
                _cached = session.get(_badge_key)
                _now = _time.time()
                if (
                    not skip_heavy_badges
                    and isinstance(_cached, dict)
                    and (_now - float(_cached.get('t') or 0)) < _badge_ttl
                ):
                    pending_count = int(_cached.get('pending') or 0)
                    unread_logs_count = int(_cached.get('logs') or 0)
                    unread_laboral_count = int(_cached.get('laboral') or 0)
                elif not skip_heavy_badges:
                    if current_user.role == ROLE_ADMIN:
                        pending_count = Solicitud.query.filter(
                            Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])
                        ).count()
                        pending_count += SolicitudVehiculo.query.filter(
                            SolicitudVehiculo.estado.in_(['PENDIENTE', 'EN_PROCESO'])
                        ).count()

                        from app.services.log_notification_service import get_total_unread_logs
                        unread_logs_count = get_total_unread_logs(current_user.id)
                        from app.services.tenant_modules import has_avisos_laborales
                        if has_avisos_laborales():
                            from app.services.log_notification_service import get_unread_laboral_logs
                            unread_laboral_count = get_unread_laboral_logs(current_user.id)
                    elif current_user.role in (ROLE_LABORAL, ROLE_RRHH):
                        from app.services.tenant_modules import has_avisos_laborales
                        if has_avisos_laborales():
                            from app.services.log_notification_service import get_unread_laboral_logs
                            unread_laboral_count = get_unread_laboral_logs(current_user.id)

                    # 2. JEFE DE OBRA: solicitudes abiertas de sus obras o creadas por él
                    elif current_user.role == ROLE_JEFE:
                        from app.services.tenant_modules import jefes_asignan_directo as _jefe_directo
                        if not _jefe_directo():
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

                    session[_badge_key] = {
                        't': _now,
                        'pending': pending_count,
                        'logs': unread_logs_count,
                        'laboral': unread_laboral_count,
                    }
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                pending_count = 0
                unread_logs_count = 0
                unread_laboral_count = 0

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
        tenant_has_soltec_portal_sso = False
        tenant_has_integrations = False
        tenant_has_registro_jornada = True
        tenant_has_fichaje_operario = False
        tenant_usa_acceso_pin = False
        muestra_auditoria_fichajes = False
        puede_ver_estado_fichaje = False
        impersonacion_activa = False
        impersonador_label = None
        tenant_has_avisos_laborales = False
        tenant_has_notas = False
        tenant_has_valoraciones = False
        tenant_has_auditoria_vehiculos = False
        jefes_asignan_directo = False
        if current_user.is_authenticated:
            tenant = getattr(g, 'current_tenant', None)
            if tenant:
                modulos_activos = getattr(tenant, 'modulos_activos', {}) or {}
                tenant_has_odoo = bool(modulos_activos.get('odoo'))
                tenant_has_odoo_alta = bool(modulos_activos.get('odoo_alta'))
                tenant_has_integrations = tenant_has_odoo or tenant_has_odoo_alta
                try:
                    from app.services.soltec_sso_service import soltec_portal_sso_available
                    tenant_has_soltec_portal_sso = soltec_portal_sso_available()
                except Exception:
                    tenant_has_soltec_portal_sso = False
                tenant_has_registro_jornada = bool(
                    modulos_activos.get('registro_jornada', True)
                )
                tenant_has_fichaje_operario = bool(
                    modulos_activos.get('fichaje_operario')
                )
                from app.services.tenant_auth_policy import tenant_usa_acceso_pin as _tenant_usa_acceso_pin
                tenant_usa_acceso_pin = _tenant_usa_acceso_pin(tenant)
                from app.services.tenant_modules import (
                    has_avisos_laborales,
                    has_auditoria_vehiculos,
                    has_notas,
                    has_valoraciones,
                    jefes_asignan_directo as _jefes_asignan_directo,
                )
                tenant_has_avisos_laborales = has_avisos_laborales(tenant)
                tenant_has_notas = has_notas(tenant)
                tenant_has_valoraciones = has_valoraciones(tenant)
                tenant_has_auditoria_vehiculos = has_auditoria_vehiculos(tenant)
                jefes_asignan_directo = _jefes_asignan_directo()
                try:
                    from app.services.fichaje_operario_service import (
                        tenant_muestra_auditoria_fichajes,
                    )
                    muestra_auditoria_fichajes = tenant_muestra_auditoria_fichajes()
                except Exception:
                    muestra_auditoria_fichajes = False
                try:
                    from app.services.fichaje_operario_service import usuario_ve_estado_fichaje
                    puede_ver_estado_fichaje = usuario_ve_estado_fichaje(current_user)
                except Exception:
                    puede_ver_estado_fichaje = False
                try:
                    from app.services.impersonation_service import (
                        impersonacion_activa as _impersonacion_activa,
                        impersonador_label as _impersonador_label,
                    )
                    impersonacion_activa = _impersonacion_activa()
                    impersonador_label = _impersonador_label()
                except Exception:
                    impersonacion_activa = False
                    impersonador_label = None

        from app.services.permission_service import (
            user_can, is_laboral, is_admin, can_resolve_fichajes,
        )
        mostrar_onboarding = False
        onboarding_import_done = {}
        onboarding_fichaje_asked = False
        onboarding_fichaje_activo = False
        tenant_has_onboarding = bool(modulos_activos.get('onboarding'))
        onboarding_completo = False
        academia_visible = False
        if current_user.is_authenticated and current_user.role == ROLE_ADMIN:
            try:
                from app.services.onboarding_service import (
                    academia_visible as _academia_visible,
                    necesita_onboarding,
                    import_tutorials_done,
                    onboarding_marcado_completo,
                    tenant_tiene_onboarding,
                )
                from app.services.fichaje_operario_service import (
                    fichaje_operario_activo,
                    fichaje_preferencia_decidida,
                )
                tenant_has_onboarding = tenant_tiene_onboarding()
                mostrar_onboarding = necesita_onboarding()
                onboarding_completo = onboarding_marcado_completo() and not mostrar_onboarding
                if tenant_has_onboarding:
                    onboarding_import_done = import_tutorials_done()
                    onboarding_fichaje_asked = fichaje_preferencia_decidida()
                    onboarding_fichaje_activo = fichaje_operario_activo()
                    academia_visible = _academia_visible()
            except Exception:
                mostrar_onboarding = False
                onboarding_import_done = {}
                onboarding_fichaje_asked = False
                onboarding_fichaje_activo = False
                academia_visible = bool(tenant_has_onboarding)
        demo_data_activa = False
        if current_user.is_authenticated and current_user.role == ROLE_ADMIN:
            try:
                from app.services.demo_data_service import demo_activa
                demo_data_activa = demo_activa()
            except Exception:
                demo_data_activa = False

        sidebar_nav = None
        if current_user.is_authenticated:
            try:
                from app.services.sidebar_nav_service import build_sidebar_nav
                sidebar_nav = build_sidebar_nav(current_user, {
                    'pending_notifications': pending_count,
                    'unread_logs_count': unread_logs_count,
                    'unread_laboral_count': unread_laboral_count,
                    'tenant_has_odoo': tenant_has_odoo,
                    'tenant_has_odoo_alta': tenant_has_odoo_alta,
                    'tenant_has_soltec_portal_sso': tenant_has_soltec_portal_sso,
                    'tenant_has_integrations': tenant_has_integrations,
                    'tenant_has_registro_jornada': tenant_has_registro_jornada,
                    'tenant_has_fichaje_operario': tenant_has_fichaje_operario,
                    'tenant_usa_acceso_pin': tenant_usa_acceso_pin,
                    'tenant_has_avisos_laborales': tenant_has_avisos_laborales,
                    'tenant_has_notas': tenant_has_notas,
                    'tenant_has_valoraciones': tenant_has_valoraciones,
                    'tenant_has_auditoria_vehiculos': tenant_has_auditoria_vehiculos,
                    'jefes_asignan_directo': jefes_asignan_directo,
                    'mostrar_onboarding': mostrar_onboarding,
                    'tenant_has_onboarding': tenant_has_onboarding,
                    'onboarding_completo': onboarding_completo,
                    'academia_visible': academia_visible,
                    'muestra_auditoria_fichajes': muestra_auditoria_fichajes,
                    'puede_ver_estado_fichaje': puede_ver_estado_fichaje,
                    'impersonacion_activa': impersonacion_activa,
                    'impersonador_label': impersonador_label,
                })
            except Exception:
                sidebar_nav = None

        return dict(
            pending_notifications=pending_count,
            unread_logs_count=unread_logs_count,
            unread_laboral_count=unread_laboral_count,
            modulos_activos=modulos_activos,
            tenant_has_odoo=tenant_has_odoo,
            tenant_has_odoo_alta=tenant_has_odoo_alta,
            tenant_has_soltec_portal_sso=tenant_has_soltec_portal_sso,
            tenant_has_integrations=tenant_has_integrations,
            tenant_has_registro_jornada=tenant_has_registro_jornada,
            tenant_has_fichaje_operario=tenant_has_fichaje_operario,
            tenant_usa_acceso_pin=tenant_usa_acceso_pin,
            muestra_auditoria_fichajes=muestra_auditoria_fichajes,
            puede_ver_estado_fichaje=puede_ver_estado_fichaje,
            impersonacion_activa=impersonacion_activa,
            impersonador_label=impersonador_label,
            tenant_has_avisos_laborales=tenant_has_avisos_laborales,
            tenant_has_notas=tenant_has_notas,
            tenant_has_valoraciones=tenant_has_valoraciones,
            tenant_has_auditoria_vehiculos=tenant_has_auditoria_vehiculos,
            jefes_asignan_directo=jefes_asignan_directo,
            tenant_has_onboarding=tenant_has_onboarding,
            onboarding_completo=onboarding_completo,
            academia_visible=academia_visible,
            mostrar_onboarding=mostrar_onboarding,
            onboarding_import_done=onboarding_import_done,
            onboarding_fichaje_asked=onboarding_fichaje_asked,
            onboarding_fichaje_activo=onboarding_fichaje_activo,
            demo_data_activa=demo_data_activa,
            sidebar_nav=sidebar_nav,
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
            from app.auth.routes import destino_portal_operario
            return redirect(destino_portal_operario(user))
        return redirect(url_for('auth.login'))

    @login_manager.unauthorized_handler
    def handle_needs_login():
        if current_user.is_authenticated:
            return redirect_by_role(current_user)
        return redirect(url_for('auth.login'))

    @app.errorhandler(403)
    def handle_forbidden(e):
        if current_user.is_authenticated:
            try:
                from app.services.impersonation_service import impersonacion_activa
                if impersonacion_activa() and current_user.role == ROLE_OPERARIO:
                    from app.auth.routes import destino_portal_operario
                    return redirect(destino_portal_operario(current_user))
            except Exception:
                pass
            return redirect_by_role(current_user)
        return redirect(url_for('auth.login'))

    from app.i18n.middleware import MarketingLocaleMiddleware
    from app.services.i18n_service import DEFAULT_LOCALE, SUPPORTED_LOCALES
    app.wsgi_app = MarketingLocaleMiddleware(
        app.wsgi_app, SUPPORTED_LOCALES, DEFAULT_LOCALE
    )

    return app
