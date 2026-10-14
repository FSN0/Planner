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
        [{'empleado_external_id': '99', 'fecha': '2026-06-02', 'check_in': '08:00',
          'check_out': '17:30', 'obra_external_id': '123', 'note': 'opcional',
          'registro_external_id': '4471', 'origen_modelo': 'hr.attendance'}]

        'registro_external_id' identifica el apunte en el sistema de origen y
        debe ser estable entre sincronizaciones. Sin él, el libro de eventos no
        puede distinguir un fichaje nuevo de una corrección de uno anterior y
        acaba duplicando registros en cada pasada.
        """
        pass

    def get_leaves(self, date_from=None, date_to=None) -> list:
        """
        Opcional. Ausencias / time off del ERP (vacaciones, bajas, permisos, puentes…).
        [
          {
            'external_id': '2808',
            'empleado_external_id': '99',
            'tipo': 'Vacaciones',
            'tipo_external_id': '14',
            'estado': 'aprobada',  # aprobada | pendiente | rechazada
            'fecha_inicio': '2026-07-01',
            'fecha_fin': '2026-07-05',
            'dias': 5.0,
            'descripcion': '...',
          }
        ]
        Por defecto vacío: adapters sin time off no rompen el sync.
        """
        return []

    def get_diff_vehiculos(self) -> dict:
        """
        Opcional. Diff de flota (fleet.vehicle) vs Vehiculo local.
        {
          'nuevos': [{
            'odoo_id': 1, 'nombre': '...', 'matricula': '...',
            'marca': '...', 'modelo': '...', 'active': True,
            'driver_partner_id': 10, 'driver_name': '...', 'cambios': {},
          }],
          'actualizados': [...],
          'sin_cambios': [...],
          'error': None,  # str si el módulo Fleet no está disponible
        }
        """
        return {'nuevos': [], 'actualizados': [], 'sin_cambios': [], 'error': 'No implementado'}

    def get_odometros_diarios(self, fecha=None, fecha_hasta=None) -> list:
        """
        Opcional. Lecturas de odómetro (fleet.vehicle.odometer).
        fecha / fecha_hasta: 'YYYY-MM-DD' (si solo fecha → ese día).
        [
          {
            'odoo_vehicle_id': 1,
            'date': '2026-07-28',
            'value': 12345.0,
            'driver_partner_id': 10,
            'driver_name': 'Juan Pérez',
          }
        ]
        """
        return []

    def get_attendance_contract_rates(
        self, partner_id, project_id, on_date=None,
        date_from=None, date_to=None,
    ):
        """Opcional. Tarifa de partner.attendance.contract (empresa+obra).

        {
          'contract_id': 1,
          'hourly_rate': 18.5,
          'lines': {partner_id_operario: 20.0},
          'date_start': '2026-01-01',
          'date_end': None,
        }

        Con date_from/date_to: contrato que solape ese rango (mes de certificación).
        """
        return None

    def list_attendance_contracts(self, partner_id, project_id):
        """Opcional. Contratos de asistencia empresa+obra (vigencias).

        [
          {'contract_id': 1, 'date_start': '2026-01-01', 'date_end': '2026-06-30', 'state': 'open'},
          ...
        ]
        """
        return []

    def get_viajes_diarios(self, fecha=None, fecha_hasta=None) -> list:
        """
        Opcional. Viajes / trayectos de flota (cobertura por fecha inicio–fin).
        [
          {
            'odoo_vehicle_id': 1,
            'odoo_viaje_id': 99,
            'date_registro': '2026-07-29',
            'date_start': '2026-07-28',
            'date_end': '2026-07-29',
            'km_start': 1000.0,   # suele ser último odómetro
            'km_end': 1120.0,
            'driver_partner_id': 10,
            'driver_name': 'Juan Pérez',
          }
        ]
        """
        return []
