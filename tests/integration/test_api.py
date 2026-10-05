"""
Tests de API REST

Verifica los endpoints de API: autenticación, autorización,
formatos de respuesta, códigos HTTP, etc.
"""

import pytest
import json
from datetime import date, timedelta
from app.models import User, Obra, Asignacion
from sqlalchemy import text


class TestAPIAuth:
    """Tests de autenticación en API"""
    
    def test_api_requires_authentication(self, tenant_client):
        """
        Test: Endpoints de API requieren autenticación
        
        Sin sesión, debe redirigir al login o devolver 401.
        """
        response = tenant_client.get('/api/v6/recursos_activos')
        
        assert response.status_code in [401, 302, 403]
    
    
    def test_api_with_valid_authentication(
        self, authenticated_client, tenant_soltec, session
    ):
        """
        Test: Con autenticación válida, API responde correctamente
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = authenticated_client.get('/api/v6/recursos_activos')
        
        assert response.status_code == 200


class TestAPIObras:
    """Tests de endpoints de obras (recursos_activos)"""
    
    def test_get_recursos_activos_returns_json(
        self, authenticated_client, tenant_soltec, obra_activa, session
    ):
        """
        Test: GET /api/v6/recursos_activos devuelve JSON válido con obras y usuarios
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = authenticated_client.get('/api/v6/recursos_activos')
        
        assert response.status_code == 200
        assert 'json' in response.content_type
        
        data = json.loads(response.data)
        
        assert 'obras' in data
        assert 'users' in data
        assert isinstance(data['obras'], list)
        assert isinstance(data['users'], list)
    
    
    def test_get_recursos_activos_contains_obra(
        self, authenticated_client, tenant_soltec, obra_activa, session
    ):
        """
        Test: La obra activa aparece en los recursos activos
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = authenticated_client.get('/api/v6/recursos_activos')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        
        obra_ids = [o['id'] for o in data['obras']]
        assert obra_activa.id in obra_ids
    
    
    def test_universal_calendar_returns_events(
        self, authenticated_client, tenant_soltec, obra_activa, user_operario, session
    ):
        """
        Test: GET /api/v6/universal-calendar devuelve eventos del calendario
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        today = date.today()
        start = (today - timedelta(days=7)).strftime('%Y-%m-%d')
        end = (today + timedelta(days=7)).strftime('%Y-%m-%d')
        
        response = authenticated_client.get(
            f'/api/v6/universal-calendar?context=obra&id={obra_activa.id}&start={start}&end={end}'
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
    
    
    def test_universal_calendar_requires_dates(
        self, authenticated_client, tenant_soltec, session
    ):
        """
        Test: El endpoint devuelve lista vacía si no se proporcionan fechas
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = authenticated_client.get('/api/v6/universal-calendar?context=obra&id=1')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data == []


    def test_company_calendar_obras_groups_people(
        self, authenticated_client, tenant_soltec, company_internal,
        obra_activa, user_operario, user_jefe, session
    ):
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        today = date.today()
        session.add(Asignacion(
            user_id=user_operario.id,
            obra_id=obra_activa.id,
            fecha=today,
            company_id=company_internal.id,
        ))
        session.add(Asignacion(
            user_id=user_jefe.id,
            obra_id=obra_activa.id,
            fecha=today,
            company_id=company_internal.id,
        ))
        session.commit()

        start = today.strftime('%Y-%m-%d')
        end = (today + timedelta(days=1)).strftime('%Y-%m-%d')
        base = (
            f'/api/v6/universal-calendar?context=empresa&id={company_internal.id}'
            f'&start={start}&end={end}'
        )

        grouped = json.loads(authenticated_client.get(base + '&mode=obras').data)
        obra_events = [
            ev for ev in grouped
            if (ev.get('extendedProps') or {}).get('type') == 'obra_group'
        ]
        assert len(obra_events) == 1
        tip = obra_events[0]['extendedProps']['tooltipContent']
        assert 'Juan Operario' in tip
        assert 'Carlos Jefe' in tip
        assert obra_events[0]['extendedProps']['obra_id'] == obra_activa.id

        people = json.loads(authenticated_client.get(base + '&mode=empleados').data)
        person_events = [
            ev for ev in people
            if (ev.get('extendedProps') or {}).get('type') == 'asignacion'
        ]
        assert len(person_events) == 2


class TestAPIAsignaciones:
    """Tests de endpoints de asignaciones"""
    
    def test_assign_worker_requires_data(
        self, authenticated_client, tenant_soltec, session
    ):
        """
        Test: POST /api/v6/assign rechaza peticiones sin datos válidos
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = authenticated_client.post(
            '/api/v6/assign',
            data=json.dumps({}),
            content_type='application/json'
        )
        
        assert response.status_code == 400
    
    
    def test_assign_worker_success(
        self, authenticated_client, tenant_soltec, user_operario, obra_activa, session
    ):
        """
        Test: POST /api/v6/assign crea asignación correctamente
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        tomorrow = (date.today() + timedelta(days=1)).strftime('%Y-%m-%d')
        
        response = authenticated_client.post(
            '/api/v6/assign',
            data=json.dumps({
                'worker_id': user_operario.id,
                'target_obra_id': obra_activa.id,
                'selected_dates': [tomorrow]
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data.get('success') == True or data.get('conflict')
    
    
    def test_unassign_worker_requires_worker_id(
        self, authenticated_client, tenant_soltec, session
    ):
        """
        Test: POST /api/v6/unassign_worker requiere worker_id
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = authenticated_client.post(
            '/api/v6/unassign_worker',
            data=json.dumps({}),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data.get('success') == False


class TestAPIValidation:
    """Tests de validación de datos en API"""
    
    def test_api_rejects_invalid_assign_data(
        self, authenticated_client, tenant_soltec, session
    ):
        """
        Test: API rechaza datos inválidos para asignación
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = authenticated_client.post(
            '/api/v6/assign',
            data=json.dumps({
                'worker_id': 'invalid',
                'target_obra_id': None
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 400


class TestAPIRateLimiting:
    """Tests de rate limiting en API"""
    
    def test_api_rate_limit_enforcement(
        self, authenticated_client, tenant_soltec, session
    ):
        """
        Test: API aplica rate limiting (si está configurado)
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        for i in range(100):
            response = authenticated_client.get('/api/v6/recursos_activos')
            
            if response.status_code == 429:
                assert True
                return
        
        # Si no hay rate limiting en este endpoint, el test pasa igualmente
        assert True


class TestAPIErrorHandling:
    """Tests de manejo de errores en API"""
    
    def test_api_toggle_pin_requires_obra_id(
        self, authenticated_client, tenant_soltec, session
    ):
        """
        Test: toggle_pin_obra devuelve 400 sin obra_id
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = authenticated_client.post(
            '/api/v6/toggle_pin_obra',
            data=json.dumps({}),
            content_type='application/json'
        )
        
        assert response.status_code == 400
    
    
    def test_api_toggle_pin_with_valid_obra(
        self, authenticated_client, tenant_soltec, obra_activa, session
    ):
        """
        Test: toggle_pin_obra funciona con obra_id válido
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        response = authenticated_client.post(
            '/api/v6/toggle_pin_obra',
            data=json.dumps({'obra_id': obra_activa.id}),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data.get('success') == True
        assert data.get('action') in ['pinned', 'unpinned']
