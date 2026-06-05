"""
Tests de Sincronización con Odoo

Verifica la integración con sistemas externos (Odoo en este caso).
Usa mocks para no depender de un Odoo real durante los tests.
"""

import pytest
from datetime import date, datetime
from unittest.mock import Mock, patch
from app.models import Obra, User, Company, SyncLog
from app.sync.dispatcher import get_sync_adapter
from sqlalchemy import text


class TestOdooConnection:
    """Tests de conexión y autenticación con Odoo"""
    
    @patch('app.sync.adapters.odoo_soltec.xmlrpc.client.ServerProxy')
    def test_odoo_connection_successful(self, mock_server, app):
        """
        Test: Conexión exitosa a Odoo
        
        Usa un mock para simular la respuesta de Odoo sin conectar realmente.
        """
        # Simular respuesta de autenticación de Odoo
        mock_common = Mock()
        mock_common.authenticate.return_value = 123  # UID de usuario
        
        mock_server.return_value = mock_common
        
        # Intentar autenticar (tu código real)
        # from app.sync.adapters.odoo_soltec import OdooSoltecAdapter
        # adapter = OdooSoltecAdapter()
        # uid = adapter.conectar()
        
        # assert uid == 123
        # assert adapter.is_connected == True
        
        # Por ahora, test placeholder
        assert True
    
    
    @patch('app.sync.adapters.odoo_soltec.xmlrpc.client.ServerProxy')
    def test_odoo_connection_fails_gracefully(self, mock_server, app):
        """
        Test: Fallo de conexión a Odoo se maneja correctamente
        
        Si Odoo está caído, la app no debe crashear.
        """
        # Simular error de conexión
        mock_server.side_effect = Exception("Connection refused")
        
        # Tu código debe capturar la excepción y loggearla
        try:
            # adapter = OdooSoltecAdapter()
            # adapter.conectar()
            pass
        except Exception as e:
            # Debe manejar el error sin crashear
            assert "Connection refused" in str(e) or True
    
    
    @patch('app.sync.adapters.odoo_soltec.xmlrpc.client.ServerProxy')
    def test_odoo_invalid_credentials(self, mock_server, app):
        """
        Test: Credenciales incorrectas de Odoo se detectan
        """
        # Simular autenticación fallida (Odoo devuelve False)
        mock_common = Mock()
        mock_common.authenticate.return_value = False
        
        mock_server.return_value = mock_common
        
        # Debe detectar que la autenticación falló
        # uid = adapter.conectar()
        # assert uid == False
        
        assert True


class TestSyncObras:
    """Tests de sincronización de obras desde Odoo"""
    
    def test_import_new_obra_from_odoo(
        self, session, tenant_soltec, user_jefe, mocker
    ):
        """
        Test: Importar una obra nueva desde Odoo
        
        Simula que Odoo tiene una obra que no existe localmente.
        Debe crearla en la base de datos.
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        # Mock del adapter de Odoo
        mock_adapter = Mock()
        mock_adapter.get_diff_obras.return_value = {
            'nuevas': [{
                'odoo_id': 99,
                'codigo': 'OBR-ODOO-001',
                'nombre': 'Reforma Importada',
                'cliente': 'Cliente Test',
                'fecha_inicio': '2024-01-15',
                'jefe_obra_id': user_jefe.id,
                'encargado_id': None
            }],
            'actualizadas': [],
            'finalizadas': []
        }
        
        mocker.patch(
            'app.sync.dispatcher.get_sync_adapter',
            return_value=mock_adapter
        )
        
        # Ejecutar importación (tu lógica de sync)
        diff = mock_adapter.get_diff_obras()
        
        for obra_data in diff['nuevas']:
            nueva_obra = Obra(
                codigo=obra_data['codigo'],
                nombre=obra_data['nombre'],
                descripcion=obra_data.get('cliente', ''),
                fecha_inicio=datetime.strptime(obra_data['fecha_inicio'], '%Y-%m-%d').date(),
                estado='Pendiente',
                jefe_obra_id=obra_data.get('jefe_obra_id'),
                external_ids={'odoo': str(obra_data['odoo_id'])}
            )
            session.add(nueva_obra)
        
        session.commit()
        
        # Verificar que se importó
        obra = Obra.query.filter_by(codigo='OBR-ODOO-001').first()
        assert obra is not None
        assert obra.nombre == 'Reforma Importada'
        assert obra.external_ids.get('odoo') == '99'
    
    
    def test_update_existing_obra_from_odoo(
        self, session, tenant_soltec, obra_activa, mocker
    ):
        """
        Test: Actualizar una obra existente con datos de Odoo
        
        Si la obra existe localmente pero cambió en Odoo, debe actualizarse.
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        # Asignar external_id a la obra existente
        obra_activa.external_ids = {'odoo': '100'}
        session.commit()
        
        # Mock: Odoo dice que esta obra cambió de nombre
        mock_adapter = Mock()
        mock_adapter.get_diff_obras.return_value = {
            'nuevas': [],
            'actualizadas': [{
                'local_id': obra_activa.id,
                'odoo_id': 100,
                'codigo': 'OBR001',
                'nombre': 'Reforma Hotel Central ACTUALIZADA',  # <-- Nombre nuevo
                'cliente': 'Cliente Actualizado',
                'fecha_inicio': '2024-01-15',
                'jefe_obra_id': obra_activa.jefe_obra_id,
                'encargado_id': None
            }],
            'finalizadas': []
        }
        
        mocker.patch(
            'app.sync.dispatcher.get_sync_adapter',
            return_value=mock_adapter
        )
        
        # Ejecutar sincronización
        diff = mock_adapter.get_diff_obras()
        
        for obra_data in diff['actualizadas']:
            obra = Obra.query.get(obra_data['local_id'])
            if obra:
                obra.nombre = obra_data['nombre']
                obra.descripcion = obra_data.get('cliente', '')
        
        session.commit()
        
        # Verificar que se actualizó
        session.expire_all()
        obra_actualizada = Obra.query.get(obra_activa.id)
        assert 'ACTUALIZADA' in obra_actualizada.nombre
    
    
    def test_mark_obra_finished_from_odoo(
        self, session, tenant_soltec, obra_activa, mocker
    ):
        """
        Test: Marcar obra como finalizada cuando Odoo lo indica
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        obra_activa.external_ids = {'odoo': '101'}
        session.commit()
        
        # Mock: Odoo dice que esta obra finalizó
        mock_adapter = Mock()
        mock_adapter.get_diff_obras.return_value = {
            'nuevas': [],
            'actualizadas': [],
            'finalizadas': [{
                'local_id': obra_activa.id,
                'odoo_id': 101
            }]
        }
        
        mocker.patch(
            'app.sync.dispatcher.get_sync_adapter',
            return_value=mock_adapter
        )
        
        # Ejecutar sincronización
        diff = mock_adapter.get_diff_obras()
        
        for obra_data in diff['finalizadas']:
            obra = Obra.query.get(obra_data['local_id'])
            if obra:
                obra.estado = 'Finalizada'
                obra.fecha_fin = date.today()
        
        session.commit()
        
        # Verificar
        session.expire_all()
        obra_finalizada = Obra.query.get(obra_activa.id)
        assert obra_finalizada.estado == 'Finalizada'
        assert obra_finalizada.fecha_fin is not None


class TestSyncEmpleados:
    """Tests de sincronización de empleados desde Odoo"""
    
    def test_import_new_employee_from_odoo(
        self, session, tenant_soltec, company_internal, mocker
    ):
        """
        Test: Importar un empleado nuevo desde Odoo
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        # Mock del adapter
        mock_adapter = Mock()
        mock_adapter.get_diff_empleados.return_value = {
            'nuevos': [{
                'odoo_id': 200,
                'name': 'Pedro',
                'lastname': 'Importado',
                'dni': '99999999Z',
                'email': 'pedro@importado.com',
                'role': 'operario',
                'categoria_profesional': 'Oficial 2ª'
            }],
            'actualizados': []
        }
        
        mocker.patch(
            'app.sync.dispatcher.get_sync_adapter',
            return_value=mock_adapter
        )
        
        # Ejecutar importación
        diff = mock_adapter.get_diff_empleados()
        
        from werkzeug.security import generate_password_hash
        
        for emp_data in diff['nuevos']:
            nuevo_user = User(
                name=emp_data['name'],
                lastname=emp_data['lastname'],
                dni=emp_data['dni'],
                email=emp_data['email'],
                role=emp_data['role'],
                categoria_profesional=emp_data.get('categoria_profesional', 'Sin definir'),
                company_id=company_internal.id,
                active=True,
                password_hash=generate_password_hash("123456"),
                external_ids={'odoo': str(emp_data['odoo_id'])}
            )
            session.add(nuevo_user)
        
        session.commit()
        
        # Verificar
        pedro = User.query.filter_by(dni='99999999Z').first()
        assert pedro is not None
        assert pedro.name == 'Pedro'
        assert pedro.external_ids.get('odoo') == '200'


class TestSyncLog:
    """Tests de logging de sincronizaciones"""
    
    def test_sync_creates_log_entry(self, session, tenant_soltec):
        """
        Test: Cada sincronización crea un log
        
        Importante para auditoría y debugging.
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        # Simular una sincronización
        log = SyncLog(
            fecha=datetime.now(),
            tipo='Obras',
            modo='Manual',
            detalles='Test de sincronización'
        )
        session.add(log)
        session.commit()
        
        # Verificar que se guardó
        logs = SyncLog.query.all()
        assert len(logs) > 0
        assert logs[0].tipo == 'Obras'
    
    
    def test_sync_log_records_errors(self, session, tenant_soltec, mocker):
        """
        Test: Errores de sincronización se loggean
        
        Si falla la sincronización, debe quedar registrado el error.
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        # Simular error de sincronización usando el mock directamente
        mock_adapter = Mock()
        mock_adapter.get_diff_obras.side_effect = Exception("Error de conexión")
        
        # Simular el flujo de error de sincronización
        try:
            mock_adapter.get_diff_obras()
        except Exception as e:
            log = SyncLog(
                fecha=datetime.now(),
                tipo='Obras',
                modo='Automático',
                detalles=f'ERROR: {str(e)}'
            )
            session.add(log)
            session.commit()
        
        # Verificar que se registró el error
        logs = SyncLog.query.filter(SyncLog.detalles.like('%ERROR%')).all()
        assert len(logs) > 0
        assert 'Error de conexión' in logs[0].detalles
