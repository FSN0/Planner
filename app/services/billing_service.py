# app/services/billing_service.py
#
# Facturación: hoy no cobramos (hace falta autónomo/SL + cuenta Stripe).
# Este módulo deja el contrato listo: quién está exento, quién debería pagar
# cuando se encienda Stripe, y dónde irán customer/subscription ids.
#
# Flujo previsto el día que se active:
#   1. Crear producto/precio en Stripe Dashboard.
#   2. STRIPE_SECRET_KEY + STRIPE_WEBHOOK_SECRET en el entorno.
#   3. Checkout Session para pasar de free → paid.
#   4. Webhook customer.subscription.* actualiza plan / stripe_* .
#   5. Los tenants con billing_exempt=True no pasan nunca por Checkout.

from app.models import Tenant
from app.services.plan_service import PLAN_FREE, PLAN_PAID, es_plan_pago


def esta_exento_de_cobro(tenant):
    """Soltec, demos, cortesías: premium sin pasarela."""
    return bool(tenant and getattr(tenant, 'billing_exempt', False))


def debe_pasar_por_pasarela(tenant):
    """
    True si, cuando Stripe esté vivo, este tenant tendría que pagar
    para mantener el plan de pago.
    """
    if not tenant:
        return False
    if esta_exento_de_cobro(tenant):
        return False
    return es_plan_pago(tenant)


def marcar_exento(tenant, exento=True, plan=PLAN_PAID):
    """Premium sin cobro. No hace commit."""
    tenant.billing_exempt = bool(exento)
    if exento:
        tenant.plan = plan or PLAN_PAID
        if tenant.limite_empleados is None and plan == PLAN_PAID:
            pass  # ilimitado
    return tenant


def stripe_configurado():
    """¿Hay clave de Stripe en el entorno? Hoy casi siempre False."""
    from flask import current_app
    return bool(current_app.config.get('STRIPE_SECRET_KEY'))


def crear_checkout_session(tenant, success_url, cancel_url):
    """
    Hueco para Stripe Checkout. Lanza RuntimeError hasta que se configure.
    """
    if esta_exento_de_cobro(tenant):
        raise RuntimeError('Este cliente está exento de cobro.')
    if not stripe_configurado():
        raise RuntimeError(
            'La pasarela de cobro aún no está configurada. '
            'Usa el plan gratuito o pide a soporte que active el premium.'
        )
    # Aquí irá: import stripe; stripe.checkout.Session.create(...)
    raise NotImplementedError('Integración Stripe pendiente de alta fiscal.')


def aplicar_evento_stripe(payload, signature_header):
    """Hueco para el webhook de Stripe. No hacer nada útil todavía."""
    if not stripe_configurado():
        raise RuntimeError('Stripe no configurado.')
    raise NotImplementedError('Webhook Stripe pendiente.')
