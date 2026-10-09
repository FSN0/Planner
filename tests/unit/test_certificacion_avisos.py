"""Avisos de certificación por mes: pendientes, dismiss y reactivación."""
from sqlalchemy import text


def _obra(session, tenant, nombre='Obra avisos'):
    from app.models import Obra
    session.execute(text(f'SET search_path TO {tenant.schema_name}'))
    o = Obra(nombre=nombre, codigo=f'AV-{abs(hash(nombre)) % 10000:04d}', estado='En Curso', is_deleted=False)
    session.add(o)
    session.commit()
    return o


def _prop(session, tenant, company, obra, *, anio, mes, estado='borrador', direccion='empresa'):
    from app.models import CertificacionPropuesta
    session.execute(text(f'SET search_path TO {tenant.schema_name}'))
    p = CertificacionPropuesta(
        company_id=company.id,
        obra_id=obra.id,
        anio=anio,
        mes=mes,
        direccion=direccion,
        estado=estado,
    )
    session.add(p)
    session.commit()
    return p


def test_resumen_avisos_counts_prev_and_actual(session, tenant_soltec, company_internal, app):
    from app.services.certificacion_avisos_service import (
        dismiss_aviso,
        resumen_avisos,
        scope_obra,
    )

    obra = _obra(session, tenant_soltec)
    _prop(session, tenant_soltec, company_internal, obra, anio=2026, mes=8, estado='borrador')
    _prop(
        session, tenant_soltec, company_internal, obra,
        anio=2026, mes=9, estado='enviada', direccion='subcontrata',
    )
    _prop(session, tenant_soltec, company_internal, obra, anio=2026, mes=10, estado='aceptada')

    with app.app_context():
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        scope = scope_obra(obra.id, company_id=company_internal.id)
        r = resumen_avisos(
            scope, anio=2026, mes=9,
            company_id=company_internal.id, obra_id=obra.id,
        )
        assert r['actual'] is True
        assert r['prev'] >= 1
        assert r['next'] == 0

        dismiss_aviso(scope, 2026, 9)
        r2 = resumen_avisos(
            scope, anio=2026, mes=9,
            company_id=company_internal.id, obra_id=obra.id,
        )
        assert r2['actual'] is False
        assert r2['silenciado'] is True

        from app.services.certificacion_avisos_service import undismiss_aviso
        undismiss_aviso(scope, 2026, 9)
        r3 = resumen_avisos(
            scope, anio=2026, mes=9,
            company_id=company_internal.id, obra_id=obra.id,
        )
        assert r3['actual'] is True
        assert r3['silenciado'] is False


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
