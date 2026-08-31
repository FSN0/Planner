"""Tests del enlace tablero → auditoría desde PersonDayTimeline."""
from datetime import date

from sqlalchemy import text

from app.models import RegistroFichaje
from app.services.person_day_timeline_service import build_person_day_timeline


class TestPersonDayTimelineAuditLink:
    def test_timeline_incluye_registro_auditoria_pendiente(
        self, session, app, tenant_soltec, user_operario, obra_activa
    ):
        dia = date.today()
        session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}, public"))
        from flask import g
        g.current_tenant = tenant_soltec

        session.add(RegistroFichaje(
            user_id=user_operario.id,
            fecha=dia,
            obra_planificada_id=obra_activa.id,
            estado='Conflicto',
        ))
        session.commit()

        data = build_person_day_timeline(user_operario.id, dia)
        assert data['success'] is True
        assert data['registro_auditoria_id'] is not None
        assert data['estado_actual'] == 'Conflicto'

        session.execute(text('SET search_path TO public'))
