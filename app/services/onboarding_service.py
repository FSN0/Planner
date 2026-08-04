# app/services/onboarding_service.py
#
# Primeros pasos tras crear la empresa: obra, gente+PIN, fichaje móvil
# e informe de jornada (lo que se enseña a la Inspección).
# Sin esto el free se abandona en la pantalla vacía.

from flask import g, has_app_context

from app.models import ROLE_OPERARIO, Obra, User
from app.services.config_service import get_tenant_config, set_tenant_config
from app.services.fichaje_operario_service import fichaje_operario_activo
from app.services.oficina_obra_service import buscar_obra_oficina, oficina_activa
from app.services.pin_auth_service import tiene_pin

CONFIG_ONBOARDING = 'onboarding_completo'
CONFIG_INFORME_VISTO = 'onboarding_informe_visto'


def _modulos_tenant():
    if not has_app_context():
        return {}
    tenant = getattr(g, 'current_tenant', None)
    return getattr(tenant, 'modulos_activos', {}) or {}


def tenant_tiene_onboarding():
    """Solo lo activamos explícitamente en altas self-serve."""
    return bool(_modulos_tenant().get('onboarding'))


def tenant_tiene_registro_jornada():
    """
    El informe existe por defecto salvo que un tenant lo desactive de forma
    explícita desde superadmin.
    """
    modulos = _modulos_tenant()
    if 'registro_jornada' not in modulos:
        return True
    return bool(modulos.get('registro_jornada'))


def onboarding_marcado_completo():
    return str(get_tenant_config(CONFIG_ONBOARDING, default='False')) == 'True'


def marcar_onboarding_completo():
    set_tenant_config(CONFIG_ONBOARDING, 'True')


def informe_onboarding_visto():
    return str(get_tenant_config(CONFIG_INFORME_VISTO, default='False')) == 'True'


def marcar_informe_visto():
    """El admin ya ha abierto el registro de jornada (kit Inspección)."""
    set_tenant_config(CONFIG_INFORME_VISTO, 'True')


def estado_onboarding():
    """Pasos del wizard y si hace falta mostrarlo."""
    if not tenant_tiene_onboarding():
        return {
            'completo': True,
            'marcado': True,
            'pasos': [],
            'pendientes': 0,
            'obras': 0,
            'operarios': 0,
            'con_pin': 0,
            'fichaje_activo': False,
            'oficina_activa': False,
            'informe_visto': True,
        }

    obras_vivas = Obra.query.filter(Obra.is_deleted.is_(False)).count()
    operarios = User.query.filter_by(
        role=ROLE_OPERARIO, is_deleted=False, active=True
    ).all()
    con_pin = sum(1 for u in operarios if tiene_pin(u))
    fichaje = fichaje_operario_activo()
    oficina = oficina_activa() and buscar_obra_oficina() is not None
    informe = (not tenant_tiene_registro_jornada()) or informe_onboarding_visto()

    pasos = [
        {
            'id': 'obra',
            'titulo': 'Crea una obra (o activa Oficina)',
            'hecho': obras_vivas > 0 or oficina,
            'hint': 'Sin obra no se puede fichar ni planificar el día.',
        },
        {
            'id': 'gente',
            'titulo': 'Ten plantilla lista para fichar',
            'hecho': len(operarios) > 0,
            'hint': 'Si ya has importado empleados, luego puedes asignarles PIN al editar su ficha.',
        },
        {
            'id': 'fichaje',
            'titulo': 'Activa el fichaje desde el móvil',
            'hecho': fichaje,
            'hint': 'Abre el acceso a /mi para el rol operario.',
        },
        {
            'id': 'informe',
            'titulo': 'Abre el informe de jornada (Inspección)',
            'hecho': informe,
            'hint': (
                'PDF/CSV con cadena de hashes: lo que enseñas si viene Inspección. '
                'Con un fichaje de prueba ya tiene contenido.'
            ),
        },
    ]
    pendientes = [p for p in pasos if not p['hecho']]
    return {
        'completo': onboarding_marcado_completo() or not pendientes,
        'marcado': onboarding_marcado_completo(),
        'pasos': pasos,
        'pendientes': len(pendientes),
        'obras': obras_vivas,
        'operarios': len(operarios),
        'con_pin': con_pin,
        'fichaje_activo': fichaje,
        'oficina_activa': oficina,
        'informe_visto': informe,
    }


def necesita_onboarding():
    """True si quedan pasos: sirve para el aviso del panel."""
    if not tenant_tiene_onboarding():
        return False
    if onboarding_marcado_completo():
        return False
    return bool(estado_onboarding()['pendientes'])


def debe_redirigir_a_wizard():
    """
    Redirige al login solo si la empresa está vacía (sin obra).

    Así un alta nueva cae en el wizard; un tenant ya rodando (Soltec, etc.)
    no se ve arrastrado a primeros pasos por falta de PIN o de fichaje.
    """
    if not tenant_tiene_onboarding():
        return False
    if onboarding_marcado_completo():
        return False
    obra = next(
        (p for p in estado_onboarding()['pasos'] if p['id'] == 'obra'),
        None,
    )
    return bool(obra and not obra['hecho'])
