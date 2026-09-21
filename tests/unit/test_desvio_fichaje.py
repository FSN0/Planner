"""Desvío plan→ficha: a favor / en contra por lado y matriz de cierre."""
from datetime import date, datetime, time
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.models import Asignacion, Obra, RegistroFichaje, ROLE_JEFE
from app.services.desvio_fichaje_service import (
    ACCION_ACEPTAR_ENTRADA,
    ACCION_CONFIRMAR_DESVIO,
    ACCION_LIBERAR_PLAZA,
    ACCION_MANTENER_FALTA,
    ACCION_RECHAZAR_DESVIO,
    ACCION_RECHAZAR_ENTRADA,
    DesvioFichajeError,
    aplicar_accion_desvio,
    botones_desvio_para,
    debe_mostrar_pendiente_a,
    es_desvio_disputa,
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

    def test_mismo_jefe_botones_cierre(self, session, tenant_soltec, desvio_ctx):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        desvio_ctx.obra_y.jefe_obra_id = desvio_ctx.jefe_x.id
        session.commit()
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        assert mismo_jefe_desvio(reg) is True
        botones = botones_desvio_para(reg, desvio_ctx.jefe_x)
        acciones = [b['accion'] for b in botones]
        assert ACCION_CONFIRMAR_DESVIO in acciones
        assert ACCION_LIBERAR_PLAZA in acciones
        assert ACCION_ACEPTAR_ENTRADA in acciones


class TestFirmasIndependientes:
    def test_liberar_luego_aceptar(self, session, tenant_soltec, desvio_ctx):
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
        assert reg.desvio_decision_plan == 'liberar'
        # Desasignar ya quita la plaza del plan
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
            obra_id=desvio_ctx.obra_x.id,
            fecha=reg.fecha,
        ).first() is None
        assert Asignacion.query.filter_by(
            user_id=desvio_ctx.operario.id,
            obra_id=desvio_ctx.obra_y.id,
            fecha=reg.fecha,
        ).first() is not None

    def test_mantener_falta_confirma_inmediato(self, session, tenant_soltec, desvio_ctx):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        reg_id = reg.id

        r1 = aplicar_accion_desvio(reg, ACCION_MANTENER_FALTA, desvio_ctx.jefe_x)
        session.commit()
        reg = RegistroFichaje.query.get(reg_id)

        assert r1['resolved'] is True
        assert reg.estado == 'Falta'
        assert Asignacion.query.filter_by(
            user_id=desvio_ctx.operario.id,
            obra_id=desvio_ctx.obra_x.id,
            fecha=reg.fecha,
        ).first() is not None

    def test_liberar_luego_rechazar_legado_acepta(self, session, tenant_soltec, desvio_ctx):
        """Rechazar entrada ya no niega el fichaje: se trata como aceptar."""
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        reg_id = reg.id
        aplicar_accion_desvio(reg, ACCION_LIBERAR_PLAZA, desvio_ctx.jefe_x)
        session.commit()
        reg = RegistroFichaje.query.get(reg_id)
        r2 = aplicar_accion_desvio(reg, ACCION_RECHAZAR_ENTRADA, desvio_ctx.jefe_y)
        session.commit()
        reg = RegistroFichaje.query.get(reg_id)

        assert r2['resolved'] is True
        assert reg.estado == 'Resuelto_Movido'

    def test_aceptar_propaga_hermanos(self, session, tenant_soltec, desvio_ctx):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        obra_z = _obra(session, 'Obra Plan Z', 'Z-01', jefe_id=desvio_ctx.jefe_x.id)
        session.commit()
        reg1 = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        session.add(Asignacion(
            user_id=desvio_ctx.operario.id, obra_id=obra_z.id, fecha=reg1.fecha,
        ))
        reg2 = RegistroFichaje(
            user_id=desvio_ctx.operario.id,
            fecha=reg1.fecha,
            obra_planificada_id=obra_z.id,
            obra_real_id=desvio_ctx.obra_y.id,
            estado='Conflicto',
            check_in=reg1.check_in,
        )
        session.add(reg2)
        session.commit()
        id1, id2 = reg1.id, reg2.id

        aplicar_accion_desvio(reg1, ACCION_ACEPTAR_ENTRADA, desvio_ctx.jefe_y)
        session.commit()
        reg1 = RegistroFichaje.query.get(id1)
        reg2 = RegistroFichaje.query.get(id2)
        assert reg1.desvio_ack_real_at is not None
        assert reg2.desvio_ack_real_at is not None
        assert Asignacion.query.filter_by(
            user_id=desvio_ctx.operario.id,
            obra_id=desvio_ctx.obra_y.id,
            fecha=reg1.fecha,
        ).first() is not None

    def test_admin_falta_desvio(self, session, tenant_soltec, desvio_ctx):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        reg_id = reg.id
        r = aplicar_accion_desvio(reg, ACCION_RECHAZAR_DESVIO, desvio_ctx.admin)
        session.commit()
        reg = RegistroFichaje.query.get(reg_id)
        assert r['resolved'] is True
        assert reg.estado == 'Falta'

    def test_jefe_plan_no_puede_aceptar_entrada(self, session, tenant_soltec, desvio_ctx):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        with pytest.raises(DesvioFichajeError):
            aplicar_accion_desvio(reg, ACCION_ACEPTAR_ENTRADA, desvio_ctx.jefe_x)

    def test_admin_confirma_ambos(self, session, tenant_soltec, desvio_ctx):
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

    def test_botones_jefe_ambos_lados(self, session, tenant_soltec, desvio_ctx):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        bx = botones_desvio_para(reg, desvio_ctx.jefe_x)
        by = botones_desvio_para(reg, desvio_ctx.jefe_y)
        assert [b['accion'] for b in bx] == [ACCION_LIBERAR_PLAZA, ACCION_MANTENER_FALTA]
        assert [b['label'] for b in bx] == ['Desasignar', 'Confirmar falta']
        assert [b['accion'] for b in by] == [ACCION_ACEPTAR_ENTRADA]
        assert [b['label'] for b in by] == ['Aceptar']
        assert lados_pendientes_para(reg, desvio_ctx.jefe_x) == {'plan'}
        assert lados_pendientes_para(reg, desvio_ctx.jefe_y) == {'real'}

    def test_botones_admin_cierre_completo(self, session, tenant_soltec, desvio_ctx):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        botones = botones_desvio_para(reg, desvio_ctx.admin)
        acciones = [b['accion'] for b in botones]
        assert ACCION_CONFIRMAR_DESVIO in acciones
        assert ACCION_LIBERAR_PLAZA in acciones
        assert ACCION_MANTENER_FALTA in acciones
        assert ACCION_ACEPTAR_ENTRADA in acciones

    def test_admin_puede_liberar_con_ambos_pendientes(
        self, session, tenant_soltec, desvio_ctx,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}, public'))
        reg = _registro_desvio(
            session, desvio_ctx.operario, desvio_ctx.obra_x, desvio_ctx.obra_y,
        )
        r = aplicar_accion_desvio(reg, ACCION_LIBERAR_PLAZA, desvio_ctx.admin)
        assert r['resolved'] is False
        assert reg.desvio_decision_plan == 'liberar'


def test_repartir_secciones_proyecta_espejos():
    from app.services.desvio_fichaje_service import (
        DesvioEspejoView,
        repartir_secciones_auditoria,
    )

    desvio = SimpleNamespace(
        id=1,
        estado='Conflicto',
        obra_planificada_id=10,
        obra_real_id=20,
        desvio_ui={
            'es_desvio': True,
            'ack_plan': False,
            'ack_real': False,
        },
    )
    desvio_ack_real = SimpleNamespace(
        id=2,
        estado='Conflicto',
        obra_planificada_id=11,
        obra_real_id=21,
        desvio_ui={
            'es_desvio': True,
            'ack_plan': False,
            'ack_real': True,
        },
    )
    ausencia = SimpleNamespace(id=3, estado='Ausencia', desvio_ui=None)
    para = SimpleNamespace(id=4, estado='Paracaidista', desvio_ui=None)

    out = repartir_secciones_auditoria(
        [desvio, desvio_ack_real, ausencia, para]
    )
    assert len(out['conflictos']) == 2
    assert ausencia in out['ausencias']
    assert para in out['paracaidistas']
    espejos_aus = [x for x in out['ausencias'] if isinstance(x, DesvioEspejoView)]
    espejos_para = [x for x in out['paracaidistas'] if isinstance(x, DesvioEspejoView)]
    assert len(espejos_aus) == 2  # ambos desvíos con plan pendiente
    assert len(espejos_para) == 1  # solo el que aún no ack_real
    assert espejos_para[0].desvio_espejo == 'real'
    assert espejos_para[0].id == 1
