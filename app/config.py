import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_secret_key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@db:5432/gestion_obra_db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', '/app/uploads')
    MAX_CONTENT_LENGTH = int(0.5 * 1024 * 1024 * 1024)

    # Configuración de correo (usa una cuenta Gmail configurada con app password)
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = "soltec.app.adm@gmail.com"  # Define en tu entorno, ej. "tu_cuenta@gmail.com"
    MAIL_PASSWORD = "sgnn bkpf acno cnhv"  # La contraseña o app password
    MAIL_DEFAULT_SENDER = MAIL_USERNAME

    # Configuración de Celery: en desarrollo se ejecuta de forma "eager" (síncrona)
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
    CELERY_TASK_ALWAYS_EAGER = True  # En producción, para que se use el worker

    SSO_SECRET_KEY = os.environ.get('SSO_SECRET_KEY')
    ODOO_CONTACTOS_URL = os.environ.get('ODOO_CONTACTOS_URL')
    
    SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_size': 20,
            'max_overflow': 40,
            'pool_recycle': 1800,
            'pool_pre_ping': True  # Verifica que la conexión está viva antes de usarla
        }