# Opt-in a comunicaciones comerciales (LSSI / RGPD art. 6.1.a).
# Casilla aparte, no premarcada; IP + timestamp para prueba de consentimiento.

from datetime import datetime

from flask import has_request_context, request
from sqlalchemy import text

from app import db
from app.models import MarketingLead
from app.services.i18n_service import get_locale, normalize_locale


def client_ip():
    """IP del cliente (respeta X-Forwarded-For si hay proxy de confianza)."""
    if not has_request_context():
        return None
    forwarded = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    if forwarded:
        return forwarded[:64]
    return (request.remote_addr or '')[:64] or None


def record_lead(
    *,
    email,
    source,
    nombre=None,
    empresa=None,
    mensaje=None,
    marketing_consent=False,
):
    """
    Guarda un lead. Si marketing_consent=False igual registramos el contacto
    (trazabilidad), pero no sirve para campañas.
    """
    email = (email or '').strip().lower()[:120]
    if not email or '@' not in email:
        return None

    ahora = datetime.utcnow() if marketing_consent else None
    ip = client_ip() if marketing_consent else None

    db.session.execute(text('SET search_path TO public'))
    lead = MarketingLead(
        email=email,
        nombre=(nombre or '').strip()[:120] or None,
        empresa=(empresa or '').strip()[:160] or None,
        source=(source or 'unknown')[:40],
        locale=normalize_locale(get_locale()),
        mensaje=(mensaje or '').strip()[:4000] or None,
        marketing_consent=bool(marketing_consent),
        marketing_consent_at=ahora,
        marketing_consent_ip=ip,
        created_at=datetime.utcnow(),
    )
    db.session.add(lead)
    db.session.commit()
    return lead


def consent_fields(acepta_comunicaciones, source='alta'):
    """Dict listo para SignupReservation / Tenant si hay opt-in."""
    if not acepta_comunicaciones:
        return {
            'marketing_consent_at': None,
            'marketing_consent_ip': None,
            'marketing_consent_source': None,
        }
    return {
        'marketing_consent_at': datetime.utcnow(),
        'marketing_consent_ip': client_ip(),
        'marketing_consent_source': (source or 'alta')[:40],
    }
