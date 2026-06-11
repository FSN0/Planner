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

    # Configuración de correo (usa una cuenta Gmail configurada con app password)
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', 'no-reply@tusaas.com')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')  # La contraseña o app password
    MAIL_DEFAULT_SENDER = MAIL_USERNAME

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

    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 20,
        'max_overflow': 40,
        'pool_recycle': 1800,
        'pool_pre_ping': True  # Verifica que la conexión está viva antes de usarla
    }
