# app/services/onboarding_service.py
#
# Hub de Primeros pasos: el admin elige guía / import / demo / saltar.
# El flag onboarding_completo decide si hay que mostrar el hub.

from flask import g, has_app_context
import json

from app.models import ROLE_OPERARIO, Obra, User
from app.services.config_service import get_tenant_config, set_tenant_config
from app.services.fichaje_operario_service import fichaje_operario_activo
from app.services.oficina_obra_service import buscar_obra_oficina, oficina_activa

CONFIG_ONBOARDING = 'onboarding_completo'
CONFIG_INFORME_VISTO = 'onboarding_informe_visto'
CONFIG_REABRIR = 'onboarding_reabrir'
CONFIG_IMPORT_DONE = 'onboarding_import_done'
CONFIG_TOUR_AUTOSTART = 'onboarding_tour_autostarted'
CONFIG_ACADEMIA_VISIBLE = 'academia_visible'

IMPORT_TUTORIAL_KEYS = (
    'obras',
    'users_internos',
    'users_externos',
    'companies',
)


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
    set_tenant_config(CONFIG_REABRIR, 'False')


def academia_visible() -> bool:
    """
    Si Academia sale en el menú una vez cerrado el recorrido inicial.
    Por defecto True (si la clave no existe).
    """
    raw = get_tenant_config(CONFIG_ACADEMIA_VISIBLE, default=None)
    if raw is None or str(raw).strip() == '':
        return True
    return str(raw).strip().lower() in ('true', '1', 'yes', 'on')


def set_academia_visible(visible: bool) -> None:
    set_tenant_config(CONFIG_ACADEMIA_VISIBLE, 'True' if visible else 'False')


def reiniciar_onboarding():
    """
    Vuelve a mostrar Primeros pasos / guía aunque el tenant ya tenga datos.
    No borra obras ni usuarios: solo reabre el onboarding.
    """
    set_tenant_config(CONFIG_ONBOARDING, 'False')
    set_tenant_config(CONFIG_INFORME_VISTO, 'False')
    set_tenant_config(CONFIG_REABRIR, 'True')
    set_tenant_config(CONFIG_IMPORT_DONE, '{}')
    set_tenant_config(CONFIG_TOUR_AUTOSTART, 'False')
    set_tenant_config(CONFIG_ACADEMIA_VISIBLE, 'True')
    # No borramos academia_tours: los logros hechos se conservan.

def import_tutorials_done() -> dict:
    """Qué listados de la guía de importación ya se han completado."""
    raw = get_tenant_config(CONFIG_IMPORT_DONE, default='{}') or '{}'
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {k: bool(data.get(k)) for k in IMPORT_TUTORIAL_KEYS}


def marcar_import_tutorial(key: str) -> None:
    """Marca un tipo de importación como hecho en la guía (tick)."""
    if key not in IMPORT_TUTORIAL_KEYS:
        return
    data = import_tutorials_done()
    if data.get(key):
        return
    data[key] = True
    set_tenant_config(CONFIG_IMPORT_DONE, json.dumps(data, ensure_ascii=False))


def informe_onboarding_visto():
    return str(get_tenant_config(CONFIG_INFORME_VISTO, default='False')) == 'True'


def marcar_informe_visto():
    """El admin ya ha abierto el registro de jornada (kit Inspección)."""
    set_tenant_config(CONFIG_INFORME_VISTO, 'True')


def estado_onboarding():
    """Estado del hub (flag + métricas útiles para plantillas / banners)."""
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
            'empresa_vacia': False,
            'import_done': {k: False for k in IMPORT_TUTORIAL_KEYS},
        }

    marcado = onboarding_marcado_completo()
    obras_vivas = Obra.query.filter(Obra.is_deleted.is_(False)).count()
    operarios_q = User.query.filter_by(role=ROLE_OPERARIO, is_deleted=False)
    n_operarios = operarios_q.count()
    # pin_hash no nulo/ vacío ≈ tiene PIN (evita cargar todos los usuarios)
    con_pin = operarios_q.filter(
        User.pin_hash.isnot(None),
        User.pin_hash != '',
    ).count()
    fichaje = fichaje_operario_activo()
    oficina = oficina_activa() and buscar_obra_oficina() is not None
    informe = (not tenant_tiene_registro_jornada()) or informe_onboarding_visto()
    reabrir = str(get_tenant_config(CONFIG_REABRIR, default='False')) == 'True'
    completo = marcado and not reabrir

    return {
        'completo': completo,
        'marcado': marcado,
        'pasos': [],
        'pendientes': 0 if completo else 1,
        'obras': obras_vivas,
        'operarios': n_operarios,
        'con_pin': con_pin,
        'fichaje_activo': fichaje,
        'oficina_activa': oficina,
        'informe_visto': informe,
        'empresa_vacia': obras_vivas == 0 and not oficina,
        'import_done': import_tutorials_done(),
    }


def necesita_onboarding():
    """True si el hub debe mostrarse (no marcado, o reabierto desde Configuración)."""
    if not tenant_tiene_onboarding():
        return False
    if str(get_tenant_config(CONFIG_REABRIR, default='False')) == 'True':
        return True
    return not onboarding_marcado_completo()


def tour_ya_autostart():
    """True si el recorrido inicial ya se lanzó una vez (no repetir en cada login)."""
    return str(get_tenant_config(CONFIG_TOUR_AUTOSTART, default='False')) == 'True'


def marcar_tour_autostart():
    set_tenant_config(CONFIG_TOUR_AUTOSTART, 'True')


def debe_redirigir_a_wizard():
    """
    Tras login, si el onboarding no está cerrado, aterriza en el tablero
    (con o sin tour=inicio según si ya se autolanzó).
    """
    if not tenant_tiene_onboarding():
        return False
    return necesita_onboarding()
