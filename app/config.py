import os


def _env_bool(name, default=False):
    """Lee una variable de entorno booleana de forma tolerante."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


class Config:
    # SECRET_KEY: NUNCA debe tener un valor por defecto en producción.
    # Si no está definida, create_app() abortará el arranque (ver app/__init__.py).
    SECRET_KEY = os.environ.get('SECRET_KEY')

    # --- CREDENCIALES DEL SUPERADMIN ---
    # Sin valores por defecto: si no están configuradas, el panel /superadmin
    # queda inaccesible (check_auth devuelve False).
    SUPERADMIN_USER = os.environ.get('SUPERADMIN_USER')
    SUPERADMIN_PASS = os.environ.get('SUPERADMIN_PASS')

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@db:5432/gestion_obra_db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')

    # Correo transaccional (alta, recuperar contraseña, avisos).
    # Producción: info@signaplan.com vía SMTP IONOS.
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.ionos.es')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', 'info@signaplan.com')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = (
        os.environ.get('MAIL_DEFAULT_SENDER') or MAIL_USERNAME or 'info@signaplan.com'
    )

    # Configuración de Celery.
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
    # En producción debe ser False para que las tareas las ejecute el worker.
    # En desarrollo, exporta CELERY_TASK_ALWAYS_EAGER=true para ejecución síncrona.
    CELERY_TASK_ALWAYS_EAGER = _env_bool('CELERY_TASK_ALWAYS_EAGER', default=False)

    SSO_SECRET_KEY = os.environ.get('SSO_SECRET_KEY')
    # URL base de la app externa Alta Odoo (puerto 5002 en dev). Ej: https://alta.tu-dominio.com
    ODOO_ALTA_APP_URL = (os.environ.get('ODOO_ALTA_APP_URL') or '').strip().rstrip('/') or None
    ODOO_ALTA_TENANT_SLUG = (os.environ.get('ODOO_ALTA_TENANT_SLUG') or '').strip() or None

    # --- Endurecimiento de cookies de sesión ---
    # SESSION_COOKIE_SECURE solo en producción (requiere HTTPS); en debug se desactiva.
    SESSION_COOKIE_SECURE = not _env_bool('FLASK_DEBUG', default=False)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = not _env_bool('FLASK_DEBUG', default=False)
    REMEMBER_COOKIE_HTTPONLY = True


    # Detrás de Caddy/Traefik: ProxyFix para esquema/host/IP reales.
    BEHIND_PROXY = _env_bool('BEHIND_PROXY', default=False)
    # Hosts dedicados → tenant (csv). Entradas con punto = hostname; sin punto = subdominio.
    # Ej: soltec,planner.soltecgrupo.es  → planner.soltecgrupo.es resuelve al tenant soltec.
    TENANT_HOST_ALIASES = (os.environ.get('TENANT_HOST_ALIASES') or '').strip()

    # Dominio raíz del producto (subdominios {cliente}.signaplan.com).
    SIGNAPLAN_BASE_DOMAIN = (os.environ.get('SIGNAPLAN_BASE_DOMAIN') or 'signaplan.com').strip()
    # Host comercial / DOMAIN del compose (localhost en dev, signaplan.com en prod).
    DOMAIN = (os.environ.get('DOMAIN') or '').strip() or None

    # Stripe (opcional). Sin clave, la pasarela no está activa.
    STRIPE_SECRET_KEY = (os.environ.get('STRIPE_SECRET_KEY') or '').strip() or None
    STRIPE_WEBHOOK_SECRET = (os.environ.get('STRIPE_WEBHOOK_SECRET') or '').strip() or None
    STRIPE_PRICE_ID = (os.environ.get('STRIPE_PRICE_ID') or '').strip() or None

    # Cobro freemium (cupo 10, geo de pago, etc.). Mientras no haya autónomo/Stripe,
    # déjalo en false: todo el mundo usa el producto sin bloqueos de plan.
    BILLING_ENFORCED = _env_bool('BILLING_ENFORCED', default=False)

    # Google Analytics (opcional). Vacío = no se carga el script aunque haya consentimiento.
    GOOGLE_ANALYTICS_ID = (os.environ.get('GOOGLE_ANALYTICS_ID') or '').strip() or None

    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 20,
        'max_overflow': 40,
        'pool_recycle': 1800,
        'pool_pre_ping': True  # Verifica que la conexión está viva antes de usarla
    }
