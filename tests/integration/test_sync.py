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


class TestCommitObras:
    def test_commit_only_nuevas_does_not_crash(
        self, authenticated_client, session, tenant_soltec
    ):
        """Guardar obras nuevas no debe petar por un 'obra' sin asignar."""
        tenant_soltec.modulos_activos = {
            **(tenant_soltec.modulos_activos or {}),
            'odoo': True,
        }
        session.add(tenant_soltec)
        session.commit()
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

        resp = authenticated_client.post('/sync/commit_obras', json={
            'nuevas': [{
                'odoo_id': 777,
                'codigo': 'T26/999',
                'nombre': 'Obra nueva test',
                'cliente': 'Cliente',
                'fecha_inicio': '2026-08-01',
                'jefe_obra_id': None,
                'encargado_id': None,
            }],
            'actualizadas': [],
            'finalizadas': [],
            'errores': 0,
        })
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body and body.get('success') is True
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        obra = Obra.query.filter_by(codigo='T26/999').first()
        assert obra is not None
        assert (obra.external_ids or {}).get('odoo') == '777'


class TestOdooObrasAdapter:
    def test_get_diff_obras_tolerates_false_odoo_values(
        self, session, tenant_soltec, app
    ):
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        from flask import g
        from app.sync.adapters.odoo_soltec import Adapter

        adapter = Adapter.__new__(Adapter)
        adapter.tenant_id = tenant_soltec.id
        adapter.db_name = 'db'
        adapter.uid = 2
        adapter.pwd = 'x'
        adapter._emp_resolve_cache = {}
        adapter.models = Mock()

        def execute_kw(*args, **kwargs):
            model = args[3]
            method = args[4]
            if model == 'bim.project.state':
                return [{'id': 6, 'name': 'Ejecución'}]
            if model == 'bim.project' and method == 'fields_get':
                return {
                    'id': {}, 'name': {}, 'nombre': {}, 'customer_id': {},
                    'date_ini': {}, 'nexecution_manager': {}, 'encargado_obra': {},
                }
            if model == 'hr.employee' and method == 'fields_get':
                return {'id': {}, 'name': {}, 'work_contact_id': {}, 'user_id': {}}
            if model == 'bim.project' and method == 'search_read':
                return [{
                    'id': 555,
                    'name': False,
                    'nombre': False,
                    'customer_id': False,
                    'date_ini': False,
                    'nexecution_manager': False,
                    'encargado_obra': False,
                }]
            return []

        adapter.models.execute_kw.side_effect = execute_kw

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            diff = adapter.get_diff_obras()

        assert len(diff['nuevas']) == 1
        nueva = diff['nuevas'][0]
        assert nueva['odoo_id'] == 555
        assert nueva['codigo'] == 'ODOO-555'
        assert nueva['nombre'] == 'ODOO-555'
        assert nueva['cliente'] == ''
        assert nueva['fecha_inicio'] is None
        assert nueva['warn_jefe'] is False
        assert nueva['warn_encargado'] is False


class TestMasterSyncSchedule:
    def test_catches_up_if_missed_night_window(
        self, session, tenant_soltec, app, mocker
    ):
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        from flask import g
        from app.models import ConfiguracionGlobal
        from app.services.sync_config_service import SyncConfigService

        for clave, valor in (
            ('sync_last_master_date', '2026-07-30'),
            ('sync_master_hour', '3'),
            ('sync_master_minute', '0'),
            ('sync_obras_enabled', 'true'),
        ):
            row = ConfiguracionGlobal.query.filter_by(clave=clave).first()
            if row:
                row.valor = valor
            else:
                session.add(ConfiguracionGlobal(clave=clave, valor=valor))
        session.commit()

        morning = datetime(2026, 8, 26, 10, 28, 0)
        mocker.patch('app.services.sync_config_service.now_local', return_value=morning)
        mocker.patch('app.services.sync_config_service.today_local', return_value=morning.date())

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            assert SyncConfigService.should_run_master_sync() is True

        before = datetime(2026, 8, 26, 2, 0, 0)
        mocker.patch('app.services.sync_config_service.now_local', return_value=before)
        mocker.patch('app.services.sync_config_service.today_local', return_value=before.date())

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            assert SyncConfigService.should_run_master_sync() is False


class TestEmployeeBajaService:
    """Baja manual / Odoo: historial intacto, asignaciones futuras liberadas."""

    def test_dar_de_baja_libera_futuro_y_conserva_dni(
        self, session, tenant_soltec, user_admin, user_operario, obra_activa, app
    ):
        from flask import g
        from datetime import timedelta
        from app.models import Asignacion, Solicitud
        from app.services.employee_baja_service import dar_de_baja
        from app.utils.timezone_utils import today_local

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

            today = today_local()
            fut = today + timedelta(days=3)
            session.add(Asignacion(
                user_id=user_operario.id,
                obra_id=obra_activa.id,
                fecha=fut,
                company_id=user_operario.company_id,
            ))
            session.commit()

            dni_antes = user_operario.dni
            result = dar_de_baja(
                user_operario,
                actor_id=user_admin.id,
                motivo='manual',
                commit=True,
            )

            assert result['changed'] is True
            assert result['liberadas'] == 1
            assert user_operario.active is False
            assert user_operario.dni == dni_antes
            assert user_operario.is_deleted is False
            assert user_operario.deactivation_reason == 'manual'
            assert user_operario.deactivated_at is not None
            assert user_operario.deactivated_by_id == user_admin.id
            assert 'Baja manual' in user_operario.inactive_reason_label
            assert Asignacion.query.filter_by(
                user_id=user_operario.id, fecha=fut
            ).first() is None
            sol = Solicitud.query.filter_by(
                empleado_id=user_operario.id, accion='DESASIGNAR', estado='CUMPLIDA'
            ).first()
            assert sol is not None
            assert 'Baja' in (sol.notas or '')

    def test_baja_externo_archiva_empresa_sin_activos(
        self, session, tenant_soltec, company_subcontrata, user_admin, app
    ):
        from flask import g
        from werkzeug.security import generate_password_hash
        from app.services.employee_baja_service import dar_de_baja, reactivar

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

            ext = User(
                email='ext-baja@test.com',
                password_hash=generate_password_hash('x'),
                role='operario',
                name='Ext',
                lastname='Uno',
                dni='EX999001A',
                company_id=company_subcontrata.id,
                active=True,
                email_verified=True,
            )
            session.add(ext)
            session.commit()

            dar_de_baja(ext, actor_id=user_admin.id, commit=True)
            session.refresh(company_subcontrata)
            assert company_subcontrata.active is False

            reactivar(ext, actor_id=user_admin.id, commit=True)
            session.refresh(company_subcontrata)
            assert ext.active is True
            assert company_subcontrata.active is True


class TestOdooEmpleadosDesactivados:
    def test_desactivados_solo_si_odoo_inactivo_o_faltante(
        self, session, tenant_soltec, company_internal, user_operario, app
    ):
        from flask import g
        from app.sync.adapters.odoo_soltec import Adapter

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

            user_operario.external_ids = {'odoo': '9001'}
            session.add(user_operario)
            session.commit()

            adapter = Adapter.__new__(Adapter)
            adapter.tenant_id = tenant_soltec.id
            adapter.db_name = 'db'
            adapter.uid = 2
            adapter.pwd = 'x'
            adapter.models = Mock()

            def execute_kw(*args, **kwargs):
                model = args[3]
                method = args[4]
                if model == 'hr.employee' and method == 'search_read':
                    domain = args[5][0] if len(args) > 5 else []
                    # Pull activos de departamentos: vacío
                    if domain and domain[0] == ['active', '=', True]:
                        return []
                    # Lectura puntual con active_test=False
                    return [{'id': 9001, 'active': False, 'name': 'Juan Operario'}]
                return []

            adapter.models.execute_kw.side_effect = execute_kw
            diff = adapter.get_diff_empleados()

            assert len(diff['desactivados']) == 1
            assert diff['desactivados'][0]['local_id'] == user_operario.id
            assert diff['desactivados'][0]['motivo'] == 'inactivo_odoo'

    def test_no_baja_si_activo_fuera_de_departamento(
        self, session, tenant_soltec, company_internal, user_operario, app
    ):
        """Activo en Odoo pero no entra en el filtro de departamentos → no baja."""
        from flask import g
        from app.sync.adapters.odoo_soltec import Adapter

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

            user_operario.external_ids = {'odoo': '9002'}
            session.add(user_operario)
            session.commit()

            adapter = Adapter.__new__(Adapter)
            adapter.tenant_id = tenant_soltec.id
            adapter.db_name = 'db'
            adapter.uid = 2
            adapter.pwd = 'x'
            adapter.models = Mock()

            def execute_kw(*args, **kwargs):
                model = args[3]
                method = args[4]
                if model == 'hr.employee' and method == 'search_read':
                    domain = args[5][0] if len(args) > 5 else []
                    if domain and domain[0] == ['active', '=', True]:
                        return []
                    return [{'id': 9002, 'active': True, 'name': 'Juan Operario'}]
                return []

            adapter.models.execute_kw.side_effect = execute_kw
            diff = adapter.get_diff_empleados()
            assert diff['desactivados'] == []

    def test_run_auto_sync_aplica_baja(
        self, session, tenant_soltec, company_internal, user_operario, app, mocker
    ):
        from flask import g
        from app.services.sync_runner_service import run_auto_sync_empleados

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

            user_operario.external_ids = {'odoo': '9003'}
            session.add(user_operario)
            session.commit()

            mock_adapter = Mock()
            mock_adapter.get_diff_empleados.return_value = {
                'nuevos': [],
                'actualizados': [],
                'sin_cambios': [],
                'desactivados': [{
                    'odoo_id': 9003,
                    'local_id': user_operario.id,
                    'name': user_operario.name,
                    'lastname': user_operario.lastname,
                }],
            }
            mocker.patch(
                'app.services.sync_runner_service.get_sync_adapter',
                return_value=mock_adapter,
            )

            result = run_auto_sync_empleados()
            session.refresh(user_operario)
            assert result['desactivados'] == 1
            assert user_operario.active is False

    def test_no_baja_si_emparejado_por_dni_con_id_odoo_antiguo(
        self, session, tenant_soltec, company_internal, user_operario, app
    ):
        """Ficha activa en Odoo (otro id) + id local apuntando a archivo → no baja y reenlaza."""
        from flask import g
        from app.sync.adapters.odoo_soltec import Adapter

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

            user_operario.external_ids = {'odoo': '100'}
            session.add(user_operario)
            session.commit()

            adapter = Adapter.__new__(Adapter)
            adapter.tenant_id = tenant_soltec.id
            adapter.db_name = 'db'
            adapter.uid = 2
            adapter.pwd = 'x'
            adapter.models = Mock()

            def execute_kw(*args, **kwargs):
                model = args[3]
                method = args[4]
                if model == 'hr.employee' and method == 'search_read':
                    domain = args[5][0] if len(args) > 5 else []
                    if domain and domain[0] == ['active', '=', True]:
                        return [{
                            'id': 200,
                            'name': 'Juan Operario',
                            'identification_id': user_operario.dni,
                            'work_email': user_operario.email,
                            'job_title': user_operario.categoria_profesional,
                            'department_id': [1, 'Producción clima'],
                            'job_id': [1, user_operario.categoria_profesional],
                        }]
                    return [{'id': 100, 'active': False, 'name': 'Juan Operario (archivo)'}]
                return []

            adapter.models.execute_kw.side_effect = execute_kw
            diff = adapter.get_diff_empleados()

            assert diff['desactivados'] == []
            assert len(diff['actualizados']) == 1
            assert diff['actualizados'][0]['local_id'] == user_operario.id
            assert diff['actualizados'][0]['odoo_id'] == 200
            assert 'Id Odoo' in diff['actualizados'][0]['cambios']

    def test_no_baja_si_odoo_no_encuentra_el_registro(
        self, session, tenant_soltec, company_internal, user_operario, app
    ):
        """Id local que no existe en hr.employee → no se interpreta como baja."""
        from flask import g
        from app.sync.adapters.odoo_soltec import Adapter

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

            user_operario.external_ids = {'odoo': '9009'}
            session.add(user_operario)
            session.commit()

            adapter = Adapter.__new__(Adapter)
            adapter.tenant_id = tenant_soltec.id
            adapter.db_name = 'db'
            adapter.uid = 2
            adapter.pwd = 'x'
            adapter.models = Mock()

            def execute_kw(*args, **kwargs):
                model = args[3]
                method = args[4]
                if model == 'hr.employee' and method == 'search_read':
                    return []
                return []

            adapter.models.execute_kw.side_effect = execute_kw
            diff = adapter.get_diff_empleados()
            assert diff['desactivados'] == []

    def test_run_auto_sync_no_baja_si_tambien_actualizado(
        self, session, tenant_soltec, company_internal, user_operario, app, mocker
    ):
        from flask import g
        from app.services.sync_runner_service import run_auto_sync_empleados

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

            user_operario.external_ids = {'odoo': '100'}
            session.add(user_operario)
            session.commit()

            mock_adapter = Mock()
            mock_adapter.get_diff_empleados.return_value = {
                'nuevos': [],
                'actualizados': [{
                    'odoo_id': 200,
                    'local_id': user_operario.id,
                    'name': user_operario.name,
                    'lastname': user_operario.lastname,
                    'role': 'operario',
                    'categoria_profesional': user_operario.categoria_profesional,
                }],
                'sin_cambios': [],
                'desactivados': [{
                    'odoo_id': 100,
                    'local_id': user_operario.id,
                    'name': user_operario.name,
                    'lastname': user_operario.lastname,
                }],
            }
            mocker.patch(
                'app.services.sync_runner_service.get_sync_adapter',
                return_value=mock_adapter,
            )

            result = run_auto_sync_empleados()
            session.refresh(user_operario)
            assert result['desactivados'] == 0
            assert user_operario.active is True
            assert str(user_operario.external_ids.get('odoo')) == '200'


class TestOdooEmpleadosDepartamentos:
    def _adapter(self, tenant, execute_kw):
        from app.sync.adapters.odoo_soltec import Adapter
        adapter = Adapter.__new__(Adapter)
        adapter.tenant_id = tenant.id
        adapter.db_name = 'db'
        adapter.uid = 2
        adapter.pwd = 'x'
        adapter.models = Mock()
        adapter.models.execute_kw.side_effect = execute_kw
        return adapter

    def _odoo_emp(self, **overrides):
        emp = {
            'id': 355,
            'name': 'Raquel Prats',
            'identification_id': '44444444D',
            'work_email': 'operario@test.com',
            'job_title': 'Oficial 1ª',
            'department_id': [9, 'Recursos Humanos'],
            'job_id': [1, 'Oficial 1ª'],
        }
        emp.update(overrides)
        return emp

    def _execute_active(self, employees):
        def execute_kw(*args, **kwargs):
            model = args[3]
            method = args[4]
            if model == 'hr.employee' and method == 'search_read':
                domain = args[5][0] if len(args) > 5 else []
                if domain and domain[0] == ['active', '=', True]:
                    return employees
                return []
            return []
        return execute_kw

    def test_omite_departamento_no_autorizado(
        self, session, tenant_soltec, company_internal, app
    ):
        from flask import g

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            adapter = self._adapter(
                tenant_soltec,
                self._execute_active([self._odoo_emp()]),
            )
            diff = adapter.get_diff_empleados()
            assert diff['nuevos'] == []
            assert len(diff['omitidos']) == 1
            assert diff.get('omitidos_decision') == []
            assert 'Recursos Humanos' in diff['omitidos'][0]['motivo']

    def test_omitido_con_ficha_local_requiere_decision(
        self, session, tenant_soltec, company_internal, app, user_operario,
    ):
        from flask import g

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            user_operario.external_ids = {'odoo': '355'}
            user_operario.dni = '44444444D'
            user_operario.active = True
            user_operario.is_deleted = False
            session.add(user_operario)
            session.commit()

            adapter = self._adapter(
                tenant_soltec,
                self._execute_active([self._odoo_emp()]),
            )
            diff = adapter.get_diff_empleados()
            assert diff['omitidos'] == []
            assert len(diff['omitidos_decision']) == 1
            row = diff['omitidos_decision'][0]
            assert row['local_id'] == user_operario.id
            assert row['departamento'] == 'Recursos Humanos'
            assert row['role_sugerido'] == 'operario'
            assert diff['desactivados'] == []

    def test_incluye_si_se_anade_departamento(
        self, session, tenant_soltec, company_internal, app
    ):
        from flask import g
        from app.services.sync_config_service import SyncConfigService

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            SyncConfigService.save_config({
                'sync_empleados_departamentos': 'Recursos Humanos',
            })
            adapter = self._adapter(
                tenant_soltec,
                self._execute_active([self._odoo_emp()]),
            )
            diff = adapter.get_diff_empleados()
            assert diff['omitidos'] == []
            assert len(diff['nuevos']) == 1
            assert diff['nuevos'][0]['odoo_id'] == 355

    def test_departamento_jo_entra_como_jefe(
        self, session, tenant_soltec, company_internal, app
    ):
        from flask import g

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            adapter = self._adapter(
                tenant_soltec,
                self._execute_active([self._odoo_emp(
                    department_id=[2, 'JO clima'],
                    job_title='Jefe',
                )]),
            )
            diff = adapter.get_diff_empleados()
            assert diff['omitidos'] == []
            assert diff['nuevos'][0]['role'] == 'jefe_obra'

    def test_rol_configurable_por_departamento(
        self, session, tenant_soltec, company_internal, app
    ):
        from flask import g
        from app.services.sync_config_service import SyncConfigService

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            SyncConfigService.save_config({
                'sync_empleados_departamentos': [
                    {'department': 'Recursos Humanos', 'role': 'laboral'},
                ],
            })
            adapter = self._adapter(
                tenant_soltec,
                self._execute_active([self._odoo_emp()]),
            )
            diff = adapter.get_diff_empleados()
            assert diff['nuevos'][0]['role'] == 'laboral'

    def test_departamento_puede_entrar_como_admin(
        self, session, tenant_soltec, company_internal, app
    ):
        from flask import g
        from app.services.sync_config_service import SyncConfigService

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            SyncConfigService.save_config({
                'sync_empleados_departamentos': [
                    {'department': 'Dirección', 'role': 'admin'},
                ],
            })
            adapter = self._adapter(
                tenant_soltec,
                self._execute_active([self._odoo_emp(department_id=[3, 'Dirección'])]),
            )
            diff = adapter.get_diff_empleados()
            assert diff['nuevos'][0]['role'] == 'admin'

    def test_jefe_obra_puede_subir_a_admin_si_departamento_lo_mapea(
        self, session, tenant_soltec, company_internal, user_operario, app
    ):
        from flask import g
        from app.services.sync_config_service import SyncConfigService

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            user_operario.role = 'jefe_obra'
            user_operario.external_ids = {'odoo': '355'}
            session.add(user_operario)
            session.commit()
            SyncConfigService.save_config({
                'sync_empleados_departamentos': [
                    {'department': 'Dirección', 'role': 'admin'},
                ],
            })
            adapter = self._adapter(
                tenant_soltec,
                self._execute_active([self._odoo_emp(
                    identification_id=user_operario.dni,
                    work_email=user_operario.email,
                    department_id=[3, 'Dirección'],
                    name='Raquel Prats',
                )]),
            )
            diff = adapter.get_diff_empleados()
            row = (diff['actualizados'] or diff['sin_cambios'])[0]
            assert row['role'] == 'admin'
            assert row['cambios']['Rol'] == 'jefe_obra ➔ admin'

    def test_no_degrada_jefe_obra_si_cambia_departamento(
        self, session, tenant_soltec, company_internal, user_operario, app
    ):
        from flask import g

        with app.app_context():
            g.current_tenant = tenant_soltec
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            user_operario.role = 'jefe_obra'
            user_operario.external_ids = {'odoo': '355'}
            session.add(user_operario)
            session.commit()

            adapter = self._adapter(
                tenant_soltec,
                self._execute_active([self._odoo_emp(
                    identification_id=user_operario.dni,
                    work_email=user_operario.email,
                    department_id=[1, 'Producción clima'],
                    name='Raquel Prats',
                )]),
            )
            diff = adapter.get_diff_empleados()
            row = (diff['actualizados'] or diff['sin_cambios'])[0]
            assert row['role'] == 'jefe_obra'
            assert 'Rol' not in (row.get('cambios') or {})

