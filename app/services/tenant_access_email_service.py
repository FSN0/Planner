# app/services/tenant_access_email_service.py
#
# Envío de enlaces de acceso a empresas (flujo /entrar) sin enumerar tenants
# en la página pública. Si el correo no está verificado, incluye también el
# enlace de verificación.

from sqlalchemy import text
from urllib.parse import quote

from app import db
from app.models import User
from app.services.email_service import send_email
from app.services.email_verification_service import generar_token
from app.services.signup_service import url_acceso_tenant


def _enlace_verificacion(tenant, email):
    """Genera URL de verificación si el user existe y no está verificado."""
    try:
        db.session.execute(text(f'SET search_path TO {tenant.schema_name}, public'))
        user = User.query.filter_by(email=email, is_deleted=False).first()
        if not user or getattr(user, 'email_verified', False):
            return None
        token = generar_token(user, tenant)
        return url_acceso_tenant(
            tenant, path=f'/auth/verificar-email?t={quote(token, safe="")}'
        )
    except Exception:
        return None


def enviar_enlaces_acceso(email, matches):
    """
    Envía al correo la lista de empresas donde puede entrar.
    matches: lista de dicts {tenant, user_name, email_verified?} de buscar_tenants_por_email.
    Devuelve True si el correo salió.
    """
    email = (email or '').strip().lower()
    if not email or not matches:
        return False

    lineas = []
    items_html = []
    try:
        for m in matches:
            tenant = m['tenant']
            path = f'/auth/login?email={quote(email, safe="")}'
            url = url_acceso_tenant(tenant, path=path)
            nombre = tenant.nombre or tenant.subdominio
            verified = m.get('email_verified', True)
            verify_url = None
            if not verified:
                verify_url = _enlace_verificacion(tenant, email)

            bloque = f'- {nombre}\n  Entrar: {url}'
            html_extra = ''
            if verify_url:
                bloque += f'\n  Verificar correo: {verify_url}'
                html_extra = (
                    f'<br><a href="{verify_url}">Verificar correo</a> '
                    f'<span style="color:#64748b">(pendiente)</span>'
                )
            lineas.append(bloque)
            items_html.append(
                f'<li><strong>{nombre}</strong><br>'
                f'<a href="{url}">Entrar en la empresa</a>{html_extra}</li>'
            )
    finally:
        try:
            db.session.execute(text('SET search_path TO public'))
        except Exception:
            pass

    texto = (
        f'Hola,\n\n'
        f'Has solicitado acceso a SignaPlan con {email}.\n'
        f'Estas son las empresas donde puedes entrar:\n\n'
        + '\n\n'.join(lineas)
        + '\n\nSi no has pedido este correo, ignóralo.\n'
    )
    html = (
        f'<p>Hola,</p>'
        f'<p>Has solicitado acceso a <strong>SignaPlan</strong> con '
        f'<strong>{email}</strong>.</p>'
        f'<p>Estas son las empresas donde puedes entrar:</p>'
        f'<ul>{"".join(items_html)}</ul>'
        f'<p>Si no has pedido este correo, ignóralo.</p>'
    )
    return bool(send_email(
        'Tu acceso a SignaPlan',
        [email],
        texto,
        html_body=html,
    ))
