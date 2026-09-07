"""Desvío plan→ficha: dos firmas cuando los jefes son distintos."""
from datetime import date, datetime, time
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.models import Asignacion, Obra, RegistroFichaje, ROLE_ADMIN, ROLE_JEFE
from app.services.desvio_fichaje_service import (
    ACCION_ACEPTAR_ENTRADA,
    ACCION_CONFIRMAR_DESVIO,
    ACCION_LIBERAR_PLAZA,
    DesvioFichajeError,
    aplicar_accion_desvio,
    botones_desvio_para,
    debe_mostrar_pendiente_a,
    es_desvio_plan_vs_real,
    lados_pendientes_para,
    mismo_jefe_desvio,
)


def _obra(session, nombre, codigo, jefe_id=None):
    o = Obra(nombre=nombre, codigo=codigo, estado='En Curso', jefe_obra_id=jefe_id)
    session.add(o)
    session.flush()
    return o


def _registro_desvio(session, user, obra_plan, obra_real, fecha=None):
    fecha = fecha or date.today()
    session.add(Asignacion(user_id=user.id, obra_id=obra_plan.id, fecha=fecha))
    reg = RegistroFichaje(
        user_id=user.id,
        fecha=fecha,
        obra_planificada_id=obra_plan.id,
        obra_real_id=obra_real.id,
        estado='Conflicto',
        check_in=datetime.combine(fecha, time(7, 0)),
    )
    session.add(reg)
    session.commit()
    return reg


@pytest.fixture
def desvio_ctx(session, tenant_soltec, user_operario, user_jefe, user_admin, company_internal):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
    from app.models import User
    from werkzeug.security import generate_password_hash

    jefe_b = User(
        email='jefe_b@test.com',
        password_hash=generate_password_hash('jefe123'),
        role=ROLE_JEFE,
        name='Jefe',
        lastname='Beta',
        dni='99999999Z',
        company_id=company_internal.id,
        active=True,
        email_verified=True,
    )
    session.add(jefe_b)
    session.flush()

    obra_x = _obra(session, 'Obra Plan X', 'X-01', jefe_id=user_jefe.id)
    obra_y = _obra(session, 'Obra Real Y', 'Y-01', jefe_id=jefe_b.id)
    session.commit()
    return SimpleNamespace(
        operario=user_operario,
        jefe_x=user_jefe,
        jefe_y=jefe_b,
        admin=user_admin,
        obra_x=obra_x,
        obra_y=obra_y,
    )


class TestDesvioDeteccion:
    def test_es_desvio(self, session, tenant_soltec, desvio_ctx):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        assert es_desvio_plan_vs_real(reg) is True
        assert mismo_jefe_desvio(reg) is False

    def test_mismo_jefe(self, session, tenant_soltec, desvio_ctx):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        desvio_ctx.obra_y.jefe_obra_id = desvio_ctx.jefe_x.id
        session.commit()
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        assert mismo_jefe_desvio(reg) is True
        botones = botones_desvio_para(reg, desvio_ctx.jefe_x)
        assert len(botones) == 1
        assert botones[0]['accion'] == ACCION_CONFIRMAR_DESVIO


class TestFirmasIndependientes:
    def test_liberar_luego_aceptar(
        self, session, tenant_soltec, desvio_ctx,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        reg_id = reg.id

        r1 = aplicar_accion_desvio(reg, ACCION_LIBERAR_PLAZA, desvio_ctx.jefe_x)
        session.commit()
        reg = RegistroFichaje.query.get(reg_id)

        assert r1['resolved'] is False
        assert r1['dismiss_for_viewer'] is True
        assert reg.desvio_ack_plan_at is not None
        assert Asignacion.query.filter_by(
            user_id=desvio_ctx.operario.id,
            obra_id=desvio_ctx.obra_x.id,
            fecha=reg.fecha,
        ).first() is None
        assert debe_mostrar_pendiente_a(reg, desvio_ctx.jefe_x) is False
        assert debe_mostrar_pendiente_a(reg, desvio_ctx.jefe_y) is True

        r2 = aplicar_accion_desvio(reg, ACCION_ACEPTAR_ENTRADA, desvio_ctx.jefe_y)
        session.commit()
        reg = RegistroFichaje.query.get(reg_id)

        assert r2['resolved'] is True
        assert reg.estado == 'Resuelto_Movido'
        assert Asignacion.query.filter_by(
            user_id=desvio_ctx.operario.id,
            obra_id=desvio_ctx.obra_y.id,
            fecha=reg.fecha,
        ).first() is not None

    def test_jefe_plan_no_puede_aceptar_entrada(
        self, session, tenant_soltec, desvio_ctx,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        with pytest.raises(DesvioFichajeError):
            aplicar_accion_desvio(reg, ACCION_ACEPTAR_ENTRADA, desvio_ctx.jefe_x)

    def test_admin_confirma_ambos(
        self, session, tenant_soltec, desvio_ctx,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        reg_id = reg.id
        r = aplicar_accion_desvio(reg, ACCION_CONFIRMAR_DESVIO, desvio_ctx.admin)
        session.commit()
        reg = RegistroFichaje.query.get(reg_id)
        assert r['resolved'] is True
        assert reg.estado == 'Resuelto_Movido'
        assert reg.desvio_ack_plan_at and reg.desvio_ack_real_at

    def test_botones_jefe_solo_su_lado(self, session, tenant_soltec, desvio_ctx):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        bx = botones_desvio_para(reg, desvio_ctx.jefe_x)
        by = botones_desvio_para(reg, desvio_ctx.jefe_y)
        assert [b['accion'] for b in bx] == [ACCION_LIBERAR_PLAZA]
        assert [b['accion'] for b in by] == [ACCION_ACEPTAR_ENTRADA]
        assert lados_pendientes_para(reg, desvio_ctx.jefe_x) == {'plan'}
        assert lados_pendientes_para(reg, desvio_ctx.jefe_y) == {'real'}
