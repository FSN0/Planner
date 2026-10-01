# app/services/plan_service.py
#
# Freemium (cuando BILLING_ENFORCED=true): free hasta LIMITE_PLAN_GRATUITO
# trabajadores; geo estricta / cupo en pago.
#
# Mientras BILLING_ENFORCED=false (fase pre-autónomo / pre-Stripe): no se
# aplica ningún bloqueo de plan. El producto se usa completo para ganar
# adopción; el día que se active el cobro bastará con poner la env a true.

from flask import current_app, g, has_app_context

from app.models import ROLE_JEFE, ROLE_OPERARIO, Tenant, User

PLAN_FREE = 'free'
PLAN_PAID = 'paid'
PLANES = (PLAN_FREE, PLAN_PAID)

LIMITE_PLAN_GRATUITO = 10
ROLES_QUE_CUENTAN = (ROLE_OPERARIO, ROLE_JEFE)


class PlanLimitError(Exception):
    """Se ha intentado superar el cupo del plan."""


def monetizacion_activa():
    """¿Están activos los límites de cobro? Por defecto no."""
    if not has_app_context():
        return False
    return bool(current_app.config.get('BILLING_ENFORCED'))


def _tenant_actual(tenant=None):
    if tenant is not None:
        return tenant
    return getattr(g, 'current_tenant', None)


def plan_del_tenant(tenant=None):
    tenant = _tenant_actual(tenant)
    if tenant is None:
        return PLAN_FREE
    plan = (getattr(tenant, 'plan', None) or PLAN_FREE).strip().lower()
    return plan if plan in PLANES else PLAN_FREE


def es_plan_pago(tenant=None):
    if not monetizacion_activa():
        return True  # sin cobro: todas las funciones “de pago” abiertas
    tenant = _tenant_actual(tenant)
    if tenant is not None and getattr(tenant, 'billing_exempt', False):
        return True
    return plan_del_tenant(tenant) == PLAN_PAID


def limite_empleados(tenant=None):
    """
    Cupo máximo de plantilla. None = sin límite.

    Con monetización apagada: siempre ilimitado.
    """
    if not monetizacion_activa():
        return None
    tenant = _tenant_actual(tenant)
    if tenant is not None and getattr(tenant, 'limite_empleados', None) is not None:
        return int(tenant.limite_empleados)
    if es_plan_pago(tenant):
        return None
    return LIMITE_PLAN_GRATUITO


def rol_cuenta_como_empleado(role):
    return role in ROLES_QUE_CUENTAN


def cuenta_como_empleado(user=None, role=None, active=None, is_deleted=None):
    """¿Ocupa plaza de plantilla este usuario (o este alta prevista)?"""
    if user is not None:
        role = user.role if role is None else role
        active = user.active if active is None else active
        is_deleted = user.is_deleted if is_deleted is None else is_deleted
    if is_deleted:
        return False
    if not active:
        return False
    return rol_cuenta_como_empleado(role)


def contar_empleados():
    """Plantilla activa del tenant actual (search_path ya apuntando al esquema)."""
    return (
        User.query
        .filter(
            User.is_deleted.is_(False),
            User.active.is_(True),
            User.role.in_(ROLES_QUE_CUENTAN),
        )
        .count()
    )


def plazas_libres(tenant=None):
    limite = limite_empleados(tenant)
    if limite is None:
        return None
    return max(0, limite - contar_empleados())


def puede_anadir(cantidad=1, tenant=None):
    if cantidad <= 0:
        return True
    libres = plazas_libres(tenant)
    if libres is None:
        return True
    return libres >= cantidad


def exigir_cupo(cantidad=1, tenant=None):
    """Lanza PlanLimitError si no caben `cantidad` altas nuevas."""
    if puede_anadir(cantidad, tenant=tenant):
        return
    limite = limite_empleados(tenant)
    usados = contar_empleados()
    raise PlanLimitError(
        f'Has llegado al límite del plan gratuito ({usados}/{limite} trabajadores). '
        f'Pasa al plan de pago para ampliar la plantilla.'
    )


def exigir_alta_empleado(role, active=True, is_deleted=False, tenant=None):
    """Comprueba cupo solo si el alta ocuparía plaza."""
    if cuenta_como_empleado(role=role, active=active, is_deleted=is_deleted):
        exigir_cupo(1, tenant=tenant)


def exigir_cambio_cupo(ocupaba_plaza, ocupara_plaza, tenant=None):
    """Al editar/activar: solo pide plaza si el cambio suma una ocupación nueva."""
    if ocupara_plaza and not ocupaba_plaza:
        exigir_cupo(1, tenant=tenant)


def plan_incluye_geolocalizacion(tenant=None):
    """Con cobro apagado siempre sí; con cobro, plan pago / exempt."""
    return es_plan_pago(tenant)


plan_incluye_fichaje_legal = plan_incluye_geolocalizacion


def exigir_geolocalizacion(tenant=None):
    if plan_incluye_geolocalizacion(tenant):
        return
    raise PlanLimitError(
        'Registrar la ubicación al fichar está incluido en el plan de pago. '
        'En el plan gratuito el fichaje funciona sin geolocalización.'
    )


exigir_fichaje_legal = exigir_geolocalizacion


def asignar_plan(tenant, plan, limite=None, billing_exempt=None):
    """Cambia plan/cupo/exención en public.tenants. No hace commit."""
    plan = (plan or '').strip().lower()
    if plan not in PLANES:
        raise ValueError(f'Plan no válido: {plan}')
    tenant.plan = plan
    if billing_exempt is not None:
        tenant.billing_exempt = bool(billing_exempt)
    if limite is not None and str(limite).strip() != '':
        tenant.limite_empleados = int(limite)
    elif plan == PLAN_PAID or getattr(tenant, 'billing_exempt', False):
        tenant.limite_empleados = None
    else:
        tenant.limite_empleados = LIMITE_PLAN_GRATUITO
    return tenant


def resumen_cupo(tenant=None):
    tenant = _tenant_actual(tenant)
    return {
        'plan': plan_del_tenant(tenant),
        'usados': contar_empleados(),
        'limite': limite_empleados(tenant),
        'libres': plazas_libres(tenant),
        'fichaje_legal': True,
        'geolocalizacion': plan_incluye_geolocalizacion(tenant),
        'billing_exempt': bool(tenant and getattr(tenant, 'billing_exempt', False)),
        'monetizacion_activa': monetizacion_activa(),
    }
