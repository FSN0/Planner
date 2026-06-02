from app import db
from app.models import ConfiguracionGlobal
from app.utils.crypto_utils import encrypt_data, decrypt_data

def set_tenant_config(clave: str, valor: str, encriptar: bool = False):
    """
    Guarda o actualiza una configuración en el esquema del cliente actual.
    Si encriptar=True, el valor se cifra antes de guardarse en base de datos.
    """
    if valor and encriptar:
        valor_guardar = encrypt_data(valor)
    else:
        valor_guardar = valor
        
    config = ConfiguracionGlobal.query.filter_by(clave=clave).first()
    if config:
        config.valor = valor_guardar
    else:
        config = ConfiguracionGlobal(clave=clave, valor=valor_guardar)
        db.session.add(config)
        
    db.session.commit()

def get_tenant_config(clave: str, desencriptar: bool = False, default=None):
    """
    Obtiene una configuración del esquema del cliente actual.
    Si desencriptar=True, desencripta el valor al vuelo antes de devolverlo.
    """
    config = ConfiguracionGlobal.query.filter_by(clave=clave).first()
    if not config:
        return default
        
    if desencriptar:
        return decrypt_data(config.valor)
        
    return config.valor