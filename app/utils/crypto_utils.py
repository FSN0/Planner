from cryptography.fernet import Fernet
from flask import current_app
import logging

logger = logging.getLogger(__name__)

def get_fernet():
    """Obtiene la instancia de Fernet usando la clave maestra del servidor."""
    key = current_app.config.get('ENCRYPTION_KEY')
    if not key:
        raise ValueError("CRÍTICO: ENCRYPTION_KEY no está configurada en las variables de entorno.")
    
    # Si la clave es un string, convertirla a bytes
    if isinstance(key, str):
        key = key.encode('utf-8')
    
    return Fernet(key)

def encrypt_data(text: str) -> str:
    """Encripta un string en texto plano."""
    if not text:
        return text
    try:
        f = get_fernet()
        # Fernet devuelve bytes, los convertimos a string para guardarlos en BBDD
        return f.encrypt(text.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logger.error(f"Error al encriptar datos: {e}")
        raise

def decrypt_data(encrypted_text: str) -> str:
    """Desencripta un string cifrado previamente."""
    if not encrypted_text:
        return encrypted_text
    try:
        f = get_fernet()
        return f.decrypt(encrypted_text.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logger.error(f"Error al desencriptar datos (¿Clave maestra cambiada?): {e}")
        return "" # Devolvemos vacío en vez de romper la app si algo falla