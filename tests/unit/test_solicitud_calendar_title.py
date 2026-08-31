from types import SimpleNamespace

from app.services.solicitud_service import solicitud_calendar_title


def _solicitud(**kwargs):
    defaults = dict(
        tipo='CONCRETA',
        accion='ASIGNAR',
        cantidad_solicitada=1,
        cantidad_cubierta=0,
        perfil_categoria=None,
        empleado=SimpleNamespace(name='María'),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_worker_desasignar_title():
    s = _solicitud(accion='DESASIGNAR')
    title = solicitud_calendar_title(s, 'OB-01 - Torre Norte', view='worker')
    assert title == 'Solicitud de baja · OB-01 - Torre Norte'


def test_worker_asignar_title():
    s = _solicitud(accion='ASIGNAR')
    title = solicitud_calendar_title(s, 'OB-02 - Parking', view='worker')
    assert title == 'Solicitud de asignación · OB-02 - Parking'


def test_obra_admin_titles():
    s = _solicitud(accion='DESASIGNAR')
    assert solicitud_calendar_title(s, '?', view='obra') == 'Solicitud de baja: María'

    s = _solicitud(accion='ASIGNAR')
    assert solicitud_calendar_title(s, '?', view='obra') == 'Solicitud de asignación: María'


def test_generica_title():
    s = _solicitud(
        tipo='GENERICA',
        cantidad_solicitada=3,
        cantidad_cubierta=1,
        perfil_categoria='Oficial',
    )
    title = solicitud_calendar_title(s, 'OB-03 - Nave', view='empresa')
    assert title == 'Solicitud de personal: faltan 2 (Oficial) · OB-03 - Nave'


def test_generica_cubierta_returns_none():
    s = _solicitud(tipo='GENERICA', cantidad_solicitada=2, cantidad_cubierta=2)
    assert solicitud_calendar_title(s, '?', view='obra') is None
