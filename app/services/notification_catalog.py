"""Catálogo de notificaciones por correo (matriz tenant).

Modos por evento: off | immediate | debounce | digest
Destinatarios: admin | laboral | rrhh | jefe | trabajador | target | requester
"""
from __future__ import annotations

MODE_OFF = 'off'
MODE_IMMEDIATE = 'immediate'
MODE_DEBOUNCE = 'debounce'
MODE_DIGEST = 'digest'
DELIVERY_MODES = (MODE_OFF, MODE_IMMEDIATE, MODE_DEBOUNCE, MODE_DIGEST)

RECIPIENT_ADMIN = 'admin'
RECIPIENT_LABORAL = 'laboral'
RECIPIENT_RRHH = 'rrhh'
RECIPIENT_JEFE = 'jefe'
RECIPIENT_TRABAJADOR = 'trabajador'
RECIPIENT_TARGET = 'target'       # usuario concreto (transaccional)
RECIPIENT_REQUESTER = 'requester' # quien abrió la solicitud

# (key, label, group, default_mode, default_recipients, allowed_modes, legacy_config_key)
NOTIFICATION_EVENTS = (
    # Planificación
    ('asignacion', 'Nueva asignación de personal', 'Planificación',
     MODE_DEBOUNCE, (RECIPIENT_JEFE,), DELIVERY_MODES, 'email_asignacion'),
    ('desasignacion', 'Desasignación de personal', 'Planificación',
     MODE_DEBOUNCE, (RECIPIENT_JEFE,), DELIVERY_MODES, 'email_desasignacion'),
    ('traslado', 'Traslado interno', 'Planificación',
     MODE_DEBOUNCE, (RECIPIENT_JEFE, RECIPIENT_ADMIN), DELIVERY_MODES, 'email_traslado'),
    # Solicitudes
    ('sol_generica', 'Nueva solicitud genérica', 'Solicitudes',
     MODE_IMMEDIATE, (RECIPIENT_ADMIN,), DELIVERY_MODES, 'email_sol_generica'),
    ('sol_concreta', 'Nueva solicitud concreta', 'Solicitudes',
     MODE_IMMEDIATE, (RECIPIENT_ADMIN,), DELIVERY_MODES, 'email_sol_concreta'),
    ('sol_vehiculo', 'Nueva solicitud de vehículo', 'Solicitudes',
     MODE_IMMEDIATE, (RECIPIENT_ADMIN,), DELIVERY_MODES, 'email_sol_vehiculo'),
    ('sol_resuelta', 'Solicitud resuelta', 'Solicitudes',
     MODE_IMMEDIATE, (RECIPIENT_JEFE, RECIPIENT_TRABAJADOR, RECIPIENT_REQUESTER),
     DELIVERY_MODES, 'email_sol_resuelta'),
    # Jornada
    ('desvio_fichaje', 'Desvío de fichaje (plan ≠ real)', 'Jornada',
     MODE_DEBOUNCE, (RECIPIENT_JEFE,), DELIVERY_MODES, None),
    ('hora_corte_reporte', 'Informe diario general (hora de corte)', 'Jornada',
     MODE_OFF, (RECIPIENT_ADMIN, RECIPIENT_LABORAL),
     (MODE_OFF, MODE_IMMEDIATE), None),
    # Acceso (transaccional: solo off/immediate; destinatario = target)
    ('acceso_pin', 'Enlace para definir PIN / fichaje', 'Acceso',
     MODE_IMMEDIATE, (RECIPIENT_TARGET,), (MODE_OFF, MODE_IMMEDIATE), None),
    ('acceso_info', 'Información de acceso a la app', 'Acceso',
     MODE_IMMEDIATE, (RECIPIENT_TARGET,), (MODE_OFF, MODE_IMMEDIATE), None),
    ('password_reset', 'Recuperar contraseña', 'Acceso',
     MODE_IMMEDIATE, (RECIPIENT_TARGET,), (MODE_OFF, MODE_IMMEDIATE), None),
    ('signup_confirm', 'Confirmación de alta / reserva', 'Acceso',
     MODE_IMMEDIATE, (RECIPIENT_TARGET,), (MODE_OFF, MODE_IMMEDIATE), None),
    ('tenant_access_link', 'Enlace de acceso a espacio', 'Acceso',
     MODE_IMMEDIATE, (RECIPIENT_TARGET,), (MODE_OFF, MODE_IMMEDIATE), None),
    ('marketing_contact', 'Formulario de contacto web', 'Acceso',
     MODE_IMMEDIATE, (RECIPIENT_ADMIN,), (MODE_OFF, MODE_IMMEDIATE), None),
)

CONFIG_DEBOUNCE_MINUTES = 'notif.debounce_minutes'
CONFIG_DIGEST_HOUR = 'notif.digest_hour'  # HH:MM local tenant
CONFIG_MIGRATED = 'notif._matrix_v1'
CONFIG_HORA_CORTE_FOLDED = 'notif._hora_corte_folded'
CONFIG_INCLUDE_ALL = '*'
CONFIG_INCLUDE_NONE = 'none'  # nadie ('' lo traga get_tenant_config como «sin config»)

# Destinatarios contextuales (no son un rol de User.role para listar personas)
CONTEXTUAL_RECIPIENTS = frozenset({
    RECIPIENT_TRABAJADOR,
    RECIPIENT_TARGET,
    RECIPIENT_REQUESTER,
})

# Roles builtin de oficina (siempre en la matriz; los custom se añaden dinámicamente)
_OFFICE_BUILTIN_ROLE_KEYS = (
    RECIPIENT_ADMIN,
    RECIPIENT_LABORAL,
    RECIPIENT_RRHH,
    RECIPIENT_JEFE,
)

# Compat: imports antiguos; preferir include_role_keys()
INCLUDE_ROLE_KEYS = _OFFICE_BUILTIN_ROLE_KEYS

DEFAULT_DEBOUNCE_MINUTES = 15
DEFAULT_DIGEST_HOUR = '08:00'
DEFAULT_HORA_LIMITE_ENTRADA = '08:30'

# Texto de ayuda (tooltip) por evento: qué correo es y cuándo salta.
EVENT_HELP = {
    'asignacion': (
        'Avisa cuando se asigna personal a una obra. '
        'Si el modo es «Agrupar», junta varios cambios de la misma sesión en un solo correo.'
    ),
    'desasignacion': (
        'Avisa cuando se quita personal de una obra (baja del cuadrante). '
        'También puede agruparse en sesión.'
    ),
    'traslado': (
        'Avisa cuando se mueve a alguien de una obra a otra en el planificador.'
    ),
    'sol_generica': (
        'Correo al crear una solicitud genérica de personal (sin personas concretas aún).'
    ),
    'sol_concreta': (
        'Correo al crear una solicitud concreta (con trabajadores concretos pedidos).'
    ),
    'sol_vehiculo': (
        'Correo al crear una solicitud de vehículo.'
    ),
    'sol_resuelta': (
        'Avisa cuando una solicitud se aprueba, deniega o cumple. '
        'Puede ir al jefe, al trabajador afectado y/o a quien la pidió.'
    ),
    'desvio_fichaje': (
        'Alerta cuando alguien ficha en una obra distinta de la planificada ese día '
        '(desvío plan ≠ real). Suele ir al jefe de la obra del plan y/o de la real.'
    ),
    'hora_corte_reporte': (
        'Informe del día ya cerrado: ausencias sin fichar y desvíos/paracaidistas pendientes. '
        'Se dispara a la hora límite de entrada. «No enviar» lo apaga por completo.'
    ),
    'acceso_pin': (
        'Correo al propio usuario con el enlace para definir o cambiar el PIN de fichaje en móvil.'
    ),
    'acceso_info': (
        'Correo al usuario con datos de acceso a la aplicación (alta / bienvenida).'
    ),
    'password_reset': (
        'Correo al usuario con el enlace para restablecer la contraseña. Solo off o inmediato.'
    ),
    'signup_confirm': (
        'Correo de confirmación al reservar o confirmar un alta de espacio / cuenta.'
    ),
    'tenant_access_link': (
        'Enlace de acceso al espacio (tenant) para el destinatario indicado.'
    ),
    'marketing_contact': (
        'Aviso interno cuando alguien envía el formulario de contacto de la web pública.'
    ),
}


def include_role_keys() -> tuple[str, ...]:
    """Roles con lista de personas en ajustes: builtin de oficina + custom del tenant.

    No incluye operario (el destinatario «trabajador» es contextual al evento).
    """
    from app.models import ROLE_OPERARIO
    from app.services.role_registry_service import list_roles

    seen = set()
    out = []
    for key in _OFFICE_BUILTIN_ROLE_KEYS:
        if key not in seen:
            seen.add(key)
            out.append(key)
    try:
        for key, _label in list_roles():
            if not key or key in seen:
                continue
            if key == ROLE_OPERARIO or key in CONTEXTUAL_RECIPIENTS:
                continue
            seen.add(key)
            out.append(key)
    except Exception:
        pass
    return tuple(out)


def event_help(key: str) -> str:
    return EVENT_HELP.get(key or '', '')


def include_config_key(role_key: str) -> str:
    return f'notif.include.{role_key}'[:50]

_EVENT_BY_KEY = {e[0]: e for e in NOTIFICATION_EVENTS}
_LEGACY_TO_KEY = {e[6]: e[0] for e in NOTIFICATION_EVENTS if e[6]}


def event_keys():
    return [e[0] for e in NOTIFICATION_EVENTS]


def get_event(key: str):
    return _EVENT_BY_KEY.get(key)


def normalize_event_key(key: str) -> str:
    key = (key or '').strip()
    if key in _EVENT_BY_KEY:
        return key
    return _LEGACY_TO_KEY.get(key, key)


def events_by_group():
    groups = {}
    for row in NOTIFICATION_EVENTS:
        groups.setdefault(row[2], []).append(row)
    return groups


def mode_label(mode: str) -> str:
    return {
        MODE_OFF: 'No enviar',
        MODE_IMMEDIATE: 'Inmediato',
        MODE_DEBOUNCE: 'Agrupar (sesión)',
        MODE_DIGEST: 'Digest diario',
    }.get(mode, mode)
