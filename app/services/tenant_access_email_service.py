# app/services/tenant_access_email_service.py
#
# Envío de enlaces de acceso a empresas (flujo /entrar) sin enumerar tenants
# en la página pública.

from app.services.email_service import send_email
from app.services.signup_service import url_acceso_tenant
from app.services.i18n_service import translate, get_locale, DEFAULT_LOCALE
from app.services.notification_dispatch_service import event_allows_send
from urllib.parse import quote


def enviar_enlaces_acceso(email, matches):
    """
    Envía al correo la lista de empresas donde puede entrar.
    matches: lista de dicts {tenant, user_name, ...} de buscar_tenants_por_email.
    Devuelve True si el correo salió.
    """
    email = (email or '').strip().lower()
    if not email or not matches:
        return False
    if not event_allows_send('tenant_access_link'):
        return False

    lineas = []
    items_html = []
    loc = get_locale() or DEFAULT_LOCALE
    for m in matches:
        tenant = m['tenant']
        path = f'/auth/login?email={quote(email, safe="")}'
        url = url_acceso_tenant(tenant, path=path)
        nombre = tenant.nombre or tenant.subdominio
        lineas.append(translate('- {nombre}\n  Entrar: {url}', loc, nombre=nombre, url=url))
        items_html.append(
            translate(
                '<li><strong>{nombre}</strong><br>'
                '<a href="{url}">Entrar en la empresa</a></li>',
                loc,
                nombre=nombre,
                url=url,
            )
        )

    texto = translate(
        'Hola,\n\n'
        'Has solicitado acceso a SignaPlan con {email}.\n'
        'Estas son las empresas donde puedes entrar:\n\n'
        '{lineas}\n\n'
        'Si no has pedido este correo, ignóralo.\n',
        loc,
        email=email,
        lineas='\n\n'.join(lineas),
    )
    html = translate(
        '<p>Hola,</p>'
        '<p>Has solicitado acceso a <strong>SignaPlan</strong> con '
        '<strong>{email}</strong>.</p>'
        '<p>Estas son las empresas donde puedes entrar:</p>'
        '<ul>{items}</ul>'
        '<p>Si no has pedido este correo, ignóralo.</p>',
        loc,
        email=email,
        items=''.join(items_html),
    )
    return bool(send_email(
        translate('Tu acceso a SignaPlan', loc),
        [email],
        texto,
        html_body=html,
    ))
