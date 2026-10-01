from types import SimpleNamespace

from app.services.sync_log_detail_service import (
    build_ausencias_detalle,
    resolve_launcher,
)


def main():
    u = SimpleNamespace(id=1, name='Ana', lastname='Lopez', email='a@x.com')
    launcher = resolve_launcher('Manual', actor=u, origen_label='Manual · pantalla Ausencias')
    detalle = build_ausencias_detalle(
        ventana_desde='2026-08-31',
        ventana_hasta='2027-11-04',
        odoo_leidos=10,
        nuevos_items=[{'external_id': '1'}],
        cambiados_items=[],
        sin_cambio_count=8,
        omitidos_items=[],
        errores=0,
        sanados=0,
        launcher=launcher,
    )
    assert detalle['resumen']['nuevos'] == 1
    assert detalle['resumen']['sin_cambio'] == 8
    assert 'Ana' in launcher['lanzado_por_label']
    print('ok')


if __name__ == '__main__':
    main()
