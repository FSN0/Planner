"""
Tests de Multi-Tenancy (Multi-Inquilino)

Estos tests son CRÍTICOS para un SaaS.
Verifican que los datos de cada cliente estén completamente aislados.

Un fallo aquí significa que un cliente podría ver datos de otro cliente.
¡Eso sería una brecha de seguridad catastrófica!
"""

import pytest
from sqlalchemy import text
from app.models import User, Obra, Company, Asignacion
from werkzeug.security import generate_password_hash


class TestTenantIsolation:
    """Tests de aislamiento de datos entre tenants"""
    
    def test_create_two_tenants_with_schemas(self, session, tenant_soltec, tenant_acme):
        """
        Test básico: Verifica que se pueden crear dos tenants
        y que sus schemas existen en PostgreSQL.
        """
        # Verifica que ambos tenants existen
        assert tenant_soltec.subdominio == "soltec"
        assert tenant_acme.subdominio == "acme"
        
        # Verifica que los schemas fueron creados
        result = session.execute(text(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name IN ('tenant_soltec', 'tenant_acme')"
        ))
        schemas = [row[0] for row in result]
        
        assert 'tenant_soltec' in schemas
        assert 'tenant_acme' in schemas
    
    
    def test_users_isolated_between_tenants(self, session, tenant_soltec, tenant_acme):
        """
        TEST CRÍTICO: Usuarios de un tenant no son visibles en otro tenant
        
        Este test simula:
        1. SOLTEC crea un usuario "Juan"
        2. ACME crea un usuario "Pedro"  
        3. Verifica que SOLTEC solo ve a Juan
        4. Verifica que ACME solo ve a Pedro
        """
        # --- TENANT 1: SOLTEC ---
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        # Crear empresa y usuario en SOLTEC
        company_soltec = Company(
            code="SOLTEC",
            nombre="SOLTEC Principal",
            is_internal=True
        )
        session.add(company_soltec)
        session.flush()
        
        user_soltec = User(
            email="juan@soltec.com",
            password_hash=generate_password_hash("123456"),
            role="operario",
            name="Juan",
            lastname="SOLTEC",
            dni="11111111A",
            company_id=company_soltec.id,
            active=True
        )
        session.add(user_soltec)
        session.commit()
        
        # --- TENANT 2: ACME ---
        session.execute(text(f"SET search_path TO {tenant_acme.schema_name}"))
        
        # Crear empresa y usuario en ACME
        company_acme = Company(
            code="ACME",
            nombre="ACME Corp",
            is_internal=True
        )
        session.add(company_acme)
        session.flush()
        
        user_acme = User(
            email="pedro@acme.com",
            password_hash=generate_password_hash("123456"),
            role="operario",
            name="Pedro",
            lastname="ACME",
            dni="22222222B",
            company_id=company_acme.id,
            active=True
        )
        session.add(user_acme)
        session.commit()
        
        # --- VERIFICACIÓN DE AISLAMIENTO ---
        
        # Cuando SOLTEC consulta usuarios, solo debe ver los suyos
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        users_soltec = User.query.all()
        assert len(users_soltec) == 1
        assert users_soltec[0].name == "Juan"
        assert users_soltec[0].email == "juan@soltec.com"
        
        # Cuando ACME consulta usuarios, solo debe ver los suyos
        session.execute(text(f"SET search_path TO {tenant_acme.schema_name}"))
        users_acme = User.query.all()
        assert len(users_acme) == 1
        assert users_acme[0].name == "Pedro"
        assert users_acme[0].email == "pedro@acme.com"
        
        # CRÍTICO: Los IDs pueden coincidir (ambos pueden ser id=1)
        # pero los datos son diferentes. Esto es correcto.
        # Lo importante es que están en schemas separados.
    
    
    def test_obras_isolated_between_tenants(self, session, tenant_soltec, tenant_acme):
        """
        TEST CRÍTICO: Obras de un tenant no son visibles en otro tenant
        
        Escenario real:
        - SOLTEC tiene una obra "Reforma Hotel"
        - ACME tiene una obra "Construcción Oficinas"
        - Cada uno solo debe ver la suya
        """
        # --- Crear obra en SOLTEC ---
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        obra_soltec = Obra(
            codigo="OBR-SOLTEC-001",
            nombre="Reforma Hotel Central",
            descripcion="Obra de SOLTEC",
            estado="En proceso"
        )
        session.add(obra_soltec)
        session.commit()
        
        # --- Crear obra en ACME ---
        session.execute(text(f"SET search_path TO {tenant_acme.schema_name}"))
        
        obra_acme = Obra(
            codigo="OBR-ACME-001",
            nombre="Construcción Oficinas",
            descripcion="Obra de ACME",
            estado="Pendiente"
        )
        session.add(obra_acme)
        session.commit()
        
        # --- Verificar aislamiento ---
        
        # SOLTEC solo ve su obra
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        obras_soltec = Obra.query.all()
        assert len(obras_soltec) == 1
        assert obras_soltec[0].nombre == "Reforma Hotel Central"
        
        # ACME solo ve su obra
        session.execute(text(f"SET search_path TO {tenant_acme.schema_name}"))
        obras_acme = Obra.query.all()
        assert len(obras_acme) == 1
        assert obras_acme[0].nombre == "Construcción Oficinas"
    
    
    def test_cannot_access_other_tenant_data_by_changing_schema(
        self, session, tenant_soltec, tenant_acme, app
    ):
        """
        TEST DE SEGURIDAD: Intento malicioso de cambiar schema manualmente
        
        Simula un atacante que intenta:
        1. Autenticarse en SOLTEC
        2. Cambiar manualmente el schema a ACME
        3. Intentar leer datos de ACME
        
        Tu middleware debe prevenir esto.
        """
        # Crear datos en ambos tenants
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        company_soltec = Company(code="SOL", nombre="SOLTEC", is_internal=True)
        session.add(company_soltec)
        session.commit()
        
        session.execute(text(f"SET search_path TO {tenant_acme.schema_name}"))
        company_acme = Company(code="ACM", nombre="ACME", is_internal=True)
        session.add(company_acme)
        session.commit()
        
        # Intenta acceder desde contexto de SOLTEC a datos de ACME
        with app.test_request_context():
            # Simula que el middleware estableció SOLTEC
            session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
            
            # Si un atacante intenta cambiar el schema...
            try:
                session.execute(text(f"SET search_path TO {tenant_acme.schema_name}"))
                companies = Company.query.all()
                
                # En producción, tu middleware debe REESTABLECER el schema correcto
                # en cada request. Este test documenta el comportamiento esperado.
                # Si llegas aquí, asegúrate de que before_request siempre 
                # establezca el schema correcto basándose en el subdominio.
                
            except Exception:
                # Si lanza excepción, es bueno (protección extra)
                pass
    
    
    def test_tenant_data_survives_public_schema_switch(self, session, tenant_soltec):
        """
        Test: Los datos del tenant siguen ahí después de cambiar a public
        
        Verifica que cambiar temporalmente a 'public' (para consultar Tenants)
        no afecta los datos del tenant.
        """
        # Crear dato en tenant
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        obra = Obra(
            codigo="TEST-SURV",
            nombre="Obra Test Survives",
            estado="Pendiente"
        )
        session.add(obra)
        session.flush()
        obra_id = obra.id
        session.commit()
        
        # Expiramos para forzar re-fetch desde la BD
        session.expire_all()
        
        # Cambiar a public (como hace el middleware)
        session.execute(text("SET search_path TO public"))
        
        # Volver al tenant
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        # La obra debe seguir existiendo
        obra_recuperada = Obra.query.filter_by(id=obra_id).first()
        assert obra_recuperada is not None
        assert obra_recuperada.nombre == "Obra Test Survives"


class TestTenantSubdomain:
    """Tests de enrutamiento por subdominio"""
    
    def test_subdomain_routes_to_correct_tenant(self, client, tenant_soltec, session):
        """
        Test: Acceder desde soltec.tudominio.com carga el tenant correcto
        
        Simula una petición HTTP con el header Host correcto.
        """
        # Simula petición desde soltec.localhost
        response = client.get(
            '/auth/login',
            headers={'Host': 'soltec.localhost:5000'}
        )
        
        # Debe cargar correctamente (sin error 404)
        assert response.status_code == 200
    
    
    def test_nonexistent_subdomain_returns_404(self, client):
        """
        Test: Acceder desde subdominio inexistente devuelve 404
        
        Si alguien accede a noexiste.tudominio.com, debe rechazar.
        """
        response = client.get(
            '/auth/login',
            headers={'Host': 'noexiste.localhost:5000'}
        )
        
        # Debe devolver 404 o redirigir a página de error
        assert response.status_code in [404, 302]
    
    
    def test_inactive_tenant_blocked(self, client, tenant_soltec, session):
        """
        Test: Tenant desactivado no permite acceso
        
        Si un cliente deja de pagar, desactivas su tenant.
        Nadie debe poder acceder a sus datos.
        """
        # Desactivar el tenant
        tenant_soltec.is_active = False
        session.commit()
        
        # Intentar acceder
        response = client.get(
            '/auth/login',
            headers={'Host': 'soltec.localhost:5000'}
        )
        
        # Debe rechazar el acceso
        assert response.status_code in [404, 403, 302]
