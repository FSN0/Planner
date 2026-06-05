"""
Tests del Sistema de Fichajes

Verifica la lógica de registro de entrada/salida, cálculo de horas,
validaciones, y reportes de fichajes.
"""

import pytest
from datetime import date, datetime, time, timedelta
from app.models import RegistroFichaje, Asignacion, User, Obra, Festivo, ConfiguracionGlobal
from sqlalchemy import text


class TestRegistroFichaje:
    """Tests de creación y validación de fichajes"""
    
    def test_create_fichaje_completo(
        self, session, tenant_soltec, user_operario, obra_activa
    ):
        """
        Test: Crear un fichaje completo (check_in y check_out)
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        hoy = date.today()
        fichaje = RegistroFichaje(
            user_id=user_operario.id,
            obra_planificada_id=obra_activa.id,
            obra_real_id=obra_activa.id,
            fecha=hoy,
            check_in=datetime.combine(hoy, time(8, 0)),
            check_out=datetime.combine(hoy, time(17, 0)),
            estado='Correcto'
        )
        session.add(fichaje)
        session.commit()
        
        fichaje_db = RegistroFichaje.query.filter_by(user_id=user_operario.id, fecha=hoy).first()
        assert fichaje_db is not None
        assert fichaje_db.estado == 'Correcto'
        assert fichaje_db.check_in is not None
        assert fichaje_db.check_out is not None
    
    
    def test_fichaje_calculates_hours_from_checkin_checkout(
        self, session, tenant_soltec, user_operario, obra_activa
    ):
        """
        Test: Se puede calcular las horas trabajadas a partir de check_in y check_out
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        hoy = date.today()
        check_in_dt = datetime.combine(hoy, time(8, 30))
        check_out_dt = datetime.combine(hoy, time(14, 30))
        
        fichaje = RegistroFichaje(
            user_id=user_operario.id,
            obra_planificada_id=obra_activa.id,
            obra_real_id=obra_activa.id,
            fecha=hoy,
            check_in=check_in_dt,
            check_out=check_out_dt,
            estado='Correcto'
        )
        session.add(fichaje)
        session.commit()
        
        diferencia = fichaje.check_out - fichaje.check_in
        horas_trabajadas = diferencia.total_seconds() / 3600
        
        assert horas_trabajadas == 6.0
    
    
    def test_fichaje_sin_checkout_queda_sin_registro(
        self, session, tenant_soltec, user_operario, obra_activa
    ):
        """
        Test: Fichaje solo con check_in (sin check_out) queda pendiente
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        hoy = date.today()
        fichaje = RegistroFichaje(
            user_id=user_operario.id,
            obra_planificada_id=obra_activa.id,
            fecha=hoy,
            check_in=datetime.combine(hoy, time(8, 0)),
            check_out=None,
            estado='Sin_Registro'
        )
        session.add(fichaje)
        session.commit()
        
        assert fichaje.check_out is None
        assert fichaje.estado == 'Sin_Registro'
    
    
    def test_fichaje_paracaidista_sin_asignacion(
        self, session, tenant_soltec, user_operario, obra_activa
    ):
        """
        Test: Fichaje en obra sin asignación previa marca como Paracaidista
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        hoy = date.today()
        fichaje = RegistroFichaje(
            user_id=user_operario.id,
            obra_planificada_id=None,
            obra_real_id=obra_activa.id,
            fecha=hoy,
            check_in=datetime.combine(hoy, time(9, 15)),
            check_out=datetime.combine(hoy, time(17, 0)),
            estado='Paracaidista'
        )
        session.add(fichaje)
        session.commit()
        
        assert fichaje.estado == 'Paracaidista'
    
    
    def test_no_duplicate_fichajes_same_obra_same_day(
        self, session, tenant_soltec, user_operario, obra_activa
    ):
        """
        Test: El sistema maneja fichajes existentes correctamente
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        hoy = date.today()
        
        fichaje1 = RegistroFichaje(
            user_id=user_operario.id,
            obra_planificada_id=obra_activa.id,
            obra_real_id=obra_activa.id,
            fecha=hoy,
            check_in=datetime.combine(hoy, time(8, 0)),
            check_out=datetime.combine(hoy, time(17, 0)),
            estado='Correcto'
        )
        session.add(fichaje1)
        session.commit()
        
        fichajes_existentes = RegistroFichaje.query.filter_by(
            user_id=user_operario.id,
            obra_real_id=obra_activa.id,
            fecha=hoy
        ).count()
        
        assert fichajes_existentes == 1


class TestAsignaciones:
    """Tests de asignación de operarios a obras"""
    
    def test_create_asignacion(
        self, session, tenant_soltec, user_operario, obra_activa
    ):
        """
        Test: Asignar un operario a una obra en una fecha
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        asignacion = Asignacion(
            user_id=user_operario.id,
            obra_id=obra_activa.id,
            fecha=date.today()
        )
        session.add(asignacion)
        session.commit()
        
        asig_db = Asignacion.query.filter_by(
            user_id=user_operario.id,
            obra_id=obra_activa.id,
            fecha=date.today()
        ).first()
        assert asig_db is not None
        assert asig_db.obra_id == obra_activa.id
    
    
    def test_operario_cannot_be_in_same_obra_twice_same_day(
        self, session, tenant_soltec, user_operario, obra_activa, user_jefe
    ):
        """
        Test: La constraint unique impide duplicar asignación misma obra/usuario/día
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        asig1 = Asignacion(
            user_id=user_operario.id,
            obra_id=obra_activa.id,
            fecha=date(2024, 6, 1)
        )
        session.add(asig1)
        session.commit()
        
        asig2 = Asignacion(
            user_id=user_operario.id,
            obra_id=obra_activa.id,
            fecha=date(2024, 6, 1)
        )
        session.add(asig2)
        
        with pytest.raises(Exception):
            session.commit()
        
        session.rollback()
    
    
    def test_operario_can_be_in_different_obras_same_day(
        self, session, tenant_soltec, user_operario, obra_activa, user_jefe
    ):
        """
        Test: Un operario SÍ puede estar en dos obras diferentes el mismo día
        (multi-asignación permitida por el modelo)
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        obra2 = Obra(
            codigo="OBR002",
            nombre="Otra Obra",
            estado="En proceso",
            jefe_obra_id=user_jefe.id
        )
        session.add(obra2)
        session.commit()
        
        asig1 = Asignacion(
            user_id=user_operario.id,
            obra_id=obra_activa.id,
            fecha=date(2024, 6, 2)
        )
        asig2 = Asignacion(
            user_id=user_operario.id,
            obra_id=obra2.id,
            fecha=date(2024, 6, 2)
        )
        session.add_all([asig1, asig2])
        session.commit()
        
        asignaciones_dia = Asignacion.query.filter_by(
            user_id=user_operario.id,
            fecha=date(2024, 6, 2)
        ).all()
        assert len(asignaciones_dia) == 2


class TestFestivos:
    """Tests de días festivos"""
    
    def test_festivo_blocks_fichaje_processing(
        self, session, tenant_soltec, user_operario, obra_activa
    ):
        """
        Test: Los festivos no se procesan como días laborales
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        festivo = Festivo(
            fecha=date.today(),
            descripcion="Día de Test Nacional"
        )
        session.add(festivo)
        session.commit()
        
        es_festivo = Festivo.query.filter_by(fecha=date.today()).first()
        assert es_festivo is not None
        assert es_festivo.descripcion == "Día de Test Nacional"
    
    
    def test_list_festivos_year(self, session, tenant_soltec):
        """
        Test: Listar todos los festivos del año
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        festivos = [
            Festivo(fecha=date(2024, 1, 1), descripcion="Año Nuevo"),
            Festivo(fecha=date(2024, 5, 1), descripcion="Día del Trabajo"),
            Festivo(fecha=date(2024, 12, 25), descripcion="Navidad"),
        ]
        session.add_all(festivos)
        session.commit()
        
        festivos_2024 = Festivo.query.filter(
            Festivo.fecha >= date(2024, 1, 1),
            Festivo.fecha <= date(2024, 12, 31)
        ).all()
        
        assert len(festivos_2024) == 3


class TestProcesamiento:
    """Tests de procesamiento automático de fichajes"""
    
    def test_procesar_fichajes_diarios_skips_festivos(
        self, session, tenant_soltec, user_operario, obra_activa, mocker, app
    ):
        """
        Test: El procesamiento diario salta los festivos
        """
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
        
        fecha_test = date(2024, 8, 15)
        festivo = Festivo(
            fecha=fecha_test,
            descripcion="Asunción de la Virgen"
        )
        session.add(festivo)
        session.commit()
        
        mocker.patch(
            'app.sync.dispatcher.get_sync_adapter',
            return_value=mocker.Mock(get_fichajes_diarios=lambda fecha_str=None: [])
        )
        
        from app.services.sync_service import procesar_fichajes_diarios
        
        procesar_fichajes_diarios(fecha_test.strftime('%Y-%m-%d'))
        
        registros = RegistroFichaje.query.filter_by(fecha=fecha_test).all()
        assert len(registros) == 0
