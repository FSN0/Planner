import importlib
import logging
from flask import g
from app.services.config_service import get_tenant_config
from app.sync.adapters.base import BaseSyncAdapter

logger = logging.getLogger(__name__)

def get_sync_adapter() -> BaseSyncAdapter:
    """
    Lee la configuración del inquilino, busca el archivo Python correspondiente
    en caliente (sin reiniciar el server) y devuelve la instancia del adaptador.
    """
    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        raise Exception("No hay un inquilino activo en el contexto.")

    # 1. Miramos qué motor tiene configurado este cliente (ej: 'odoo_cliente_a')
    # Si no tiene ninguno, podemos devolver un adaptador por defecto (ej: 'fichajes_locales') o None.
    motor_nombre = get_tenant_config('motor_sincronizacion', default='fichajes_locales')

    # 2. Construimos la ruta del módulo Python (ej: 'app.sync.adapters.odoo_cliente_a')
    module_path = f"app.sync.adapters.{motor_nombre}"

    try:
        # 3. IMPORTACIÓN DINÁMICA: Carga el archivo .py en caliente
        # importlib.invalidate_caches() # (Opcional) Fuerza a Python a buscar archivos recién creados
        modulo = importlib.import_module(module_path)
        
        # 4. Asumimos que el archivo tiene una clase llamada 'Adapter' que hereda de BaseSyncAdapter
        adapter_class = getattr(modulo, 'Adapter')
        
        # 5. Instanciamos el adaptador pasándole el ID del tenant por si necesita buscar sus claves encriptadas
        return adapter_class(tenant_id=g.current_tenant.id)

    except ImportError:
        logger.error(f"No se encontró el archivo del adaptador '{motor_nombre}.py' en app/sync/adapters/")
        raise Exception(f"El módulo de sincronización '{motor_nombre}' no está instalado o no existe.")
    except AttributeError:
        logger.error(f"El archivo '{motor_nombre}.py' debe contener una clase llamada 'Adapter'.")
        raise Exception("Formato de adaptador inválido.")