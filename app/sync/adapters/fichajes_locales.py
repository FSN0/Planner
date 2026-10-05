"""
Adaptador de sincronización local (sin ERP externo).

Uso: Para tenants que no tienen integración con Odoo/SAP y gestionan
obras/empleados/fichajes directamente en la aplicación.

Este adaptador devuelve listas vacías porque no hay fuente externa para sincronizar.
Si quieres importar datos desde Excel/CSV, puedes extender este adaptador.
"""
from app.sync.adapters.base import BaseSyncAdapter


class Adapter(BaseSyncAdapter):
    """Adaptador para gestión local sin ERP externo."""

    def __init__(self, tenant_id: int):
        super().__init__(tenant_id)

    def get_diff_obras(self) -> dict:
        """No hay fuente externa, devuelve vacío."""
        return {
            'nuevas': [],
            'actualizadas': [],
            'sin_cambios': [],
            'finalizadas': [],
            'validadas_manual': []
        }

    def get_diff_empleados(self) -> dict:
        """No hay fuente externa, devuelve vacío."""
        return {
            'nuevos': [],
            'actualizados': [],
            'sin_cambios': [],
            'desactivados': [],
        }

    def get_fichajes_diarios(self, fecha_str=None) -> list:
        """No hay fuente externa, devuelve vacío.
        
        Los fichajes se registran manualmente en la app, no vienen de un ERP.
        """
        return []

    def get_diff_subcontratas(self) -> dict:
        return {
            'empresas': {'nuevas': [], 'actualizadas': []},
            'empleados': {'nuevos': [], 'actualizados': [], 'desactivados': []},
        }
