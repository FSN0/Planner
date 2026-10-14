"""Avisos de certificación: solo acción en tu tejado + requerir a subcontrata."""
from sqlalchemy import text


DIR_SUB = 'subcontrata_a_empresa'
DIR_EMP = 'empresa_a_subcontrata'


def _obra(session, tenant, nombre='Obra avisos'):
    from app.models import Obra
    session.execute(text(f'SET search_path TO {tenant.schema_name}'))
    o = Obra(nombre=nombre, codigo=f'AV-{abs(hash(nombre)) % 10000:04d}', estado='En Curso', is_deleted=False)
    session.add(o)
    session.commit()
    return o


def _prop(session, tenant, company, obra, *, anio, mes, estado='borrador', direccion=DIR_EMP, **extra):
    from app.models import CertificacionPropuesta
    session.execute(text(f'SET search_path TO {tenant.schema_name}'))
    p = CertificacionPropuesta(
        company_id=company.id,
        obra_id=obra.id,
        anio=anio,
        mes=mes,
        direccion=direccion,
        estado=estado,
        **extra,
    )
    session.add(p)
    session.commit()
    return p


def test_resumen_avisos_solo_recibida_no_borrador(session, tenant_soltec, company_subcontrata, app):
    from app.services.certificacion_avisos_service import (
        dismiss_aviso,
        resumen_avisos,
        scope_obra,
    )

    obra = _obra(session, tenant_soltec)
    # Borrador sin enviar: NO aviso
    _prop(session, tenant_soltec, company_subcontrata, obra, anio=2026, mes=8, estado='borrador', direccion=DIR_SUB)
    # Subcontrata envió → oficina tiene recibida
    _prop(
        session, tenant_soltec, company_subcontrata, obra,
        anio=2026, mes=9, estado='enviada', direccion=DIR_SUB,
    )
    _prop(session, tenant_soltec, company_subcontrata, obra, anio=2026, mes=10, estado='aceptada', direccion=DIR_SUB)

    with app.app_context():
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        scope = scope_obra(obra.id, company_id=company_subcontrata.id)
        r = resumen_avisos(
            scope, anio=2026, mes=9,
            company_id=company_subcontrata.id, obra_id=obra.id,
            vista_subcontrata=False,
        )
        assert r['actual'] is True
        assert r['motivo_actual'] == 'recibida'
        assert r['prev'] == 0
        assert r['next'] == 0

        dismiss_aviso(scope, 2026, 9)
        r2 = resumen_avisos(
            scope, anio=2026, mes=9,
            company_id=company_subcontrata.id, obra_id=obra.id,
            vista_subcontrata=False,
        )
        assert r2['actual'] is False
        assert r2['silenciado'] is True


def test_avisos_subcontrata_recibida_y_requerida(
    session, tenant_soltec, company_subcontrata, app,
):
    from app.services.certificacion_avisos_service import pares_pendientes_mes, resumen_avisos, scope_obra
    from app.utils.timezone_utils import utc_now

    obra = _obra(session, tenant_soltec, 'Obra sub aviso')
    # Oficina envió contrapropuesta → subcontrata recibida
    _prop(
        session, tenant_soltec, company_subcontrata, obra,
        anio=2026, mes=7, estado='enviada', direccion=DIR_EMP,
    )
    # Requerida completar (borrador DIR_SUB con requerida_at)
    _prop(
        session, tenant_soltec, company_subcontrata, obra,
        anio=2026, mes=8, estado='borrador', direccion=DIR_SUB,
        requerida_at=utc_now(),
    )

    with app.app_context():
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        pares7 = pares_pendientes_mes(
            anio=2026, mes=7, company_id=company_subcontrata.id, obra_id=obra.id,
            vista_subcontrata=True,
        )
        assert pares7.get((company_subcontrata.id, obra.id)) == 'recibida'

        pares8 = pares_pendientes_mes(
            anio=2026, mes=8, company_id=company_subcontrata.id, obra_id=obra.id,
            vista_subcontrata=True,
        )
        assert pares8.get((company_subcontrata.id, obra.id)) == 'requerida'

        # Oficina no ve el requerimiento como aviso propio
        pares8_ofi = pares_pendientes_mes(
            anio=2026, mes=8, company_id=company_subcontrata.id, obra_id=obra.id,
            vista_subcontrata=False,
        )
        assert (company_subcontrata.id, obra.id) not in pares8_ofi

        scope = scope_obra(obra.id, company_id=company_subcontrata.id, vista_subcontrata=True)
        r = resumen_avisos(
            scope, anio=2026, mes=8,
            company_id=company_subcontrata.id, obra_id=obra.id,
            vista_subcontrata=True,
        )
        assert r['actual'] is True
        assert r['motivo_actual'] == 'requerida'
        assert r['prev'] >= 1


def test_reactivar_avisos_clears_dismiss(session, tenant_soltec, company_internal, app):
    from app.services.certificacion_avisos_service import (
        dismiss_aviso,
        is_dismissed,
        reactivar_avisos_mes,
        scope_obra,
    )

    obra = _obra(session, tenant_soltec, 'Obra reactivar')
    scope = scope_obra(obra.id, company_id=company_internal.id)
    with app.app_context():
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        dismiss_aviso(scope, 2026, 5)
        assert is_dismissed(scope, 2026, 5)
        reactivar_avisos_mes(2026, 5, company_id=company_internal.id, obra_id=obra.id)
        assert not is_dismissed(scope, 2026, 5)
