from abc import ABC, abstractmethod

class BaseSyncAdapter(ABC):
    """
    CONTRATO ESTRICTO: Cualquier adaptador (Odoo, SAP, Fichajes Locales) 
    debe heredar de esta clase y devolver los datos exactamente con esta estructura.
    """

    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    @abstractmethod
    def get_diff_obras(self) -> dict:
        """
        Debe devolver un diccionario con:
        {
            'nuevas': [{'external_id': '123', 'codigo': 'OB-01', 'nombre': 'Edificio A', 'cliente': 'PacoSL', 'fecha_inicio': '2026-06-01', 'jefe_obra_external_id': '99'}],
            'actualizadas': [...],
            'finalizadas': [{'external_id': '123'}]
        }
        """
        pass

    @abstractmethod
    def get_diff_empleados(self) -> dict:
        """
        Debe devolver un diccionario con:
        {
            'nuevos': [{'external_id': '99', 'name': 'Juan', 'lastname': 'Pérez', 'dni': '12345678A', 'email': 'juan@ejemplo.com', 'role': 'operario', 'categoria': 'Oficial 1ª'}],
            'actualizados': [...],
            'desactivados': [{'external_id': '99'}]
        }
        """
        pass

    @abstractmethod
    def get_fichajes_diarios(self) -> list:
        """
        Debe devolver una lista de diccionarios:
        [{'empleado_external_id': '99', 'fecha': '2026-06-02', 'check_in': '08:00', 'check_out': '17:30', 'obra_external_id': '123'}]
        """
        pass