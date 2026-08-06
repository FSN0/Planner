# app/marketing/routes.py
#
# Web pública en signaplan.com: landing, alta de empresa y textos legales.

from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app import limiter
from app.services.tenant_domain_service import is_marketing_host, normalize_host

marketing_bp = Blueprint('marketing', __name__)

LEGAL_PAGES = {
    'aviso-legal': {
        'title': 'Aviso legal',
        'template': 'marketing/legal_aviso.html',
    },
    'privacidad': {
        'title': 'Política de privacidad',
        'template': 'marketing/legal_privacidad.html',
    },
    'cookies': {
        'title': 'Política de cookies',
        'template': 'marketing/legal_cookies.html',
    },
    'encargado': {
        'title': 'Encargo de tratamiento',
        'template': 'marketing/legal_encargado.html',
    },
    'condiciones': {
        'title': 'Condiciones de uso',
        'template': 'marketing/legal_condiciones.html',
    },
}


def _legal_entity():
    """Datos del titular. Sobreescribibles por env sin tocar plantillas."""
    import os
    return {
        'razon_social': (
            os.environ.get('LEGAL_RAZON_SOCIAL') or 'Francisco Navarro Hernández'
        ).strip(),
        'nif': (os.environ.get('LEGAL_NIF') or '18461268L').strip(),
        'domicilio': (
            os.environ.get('LEGAL_DOMICILIO') or 'Calle La Ermita 23, Teruel'
        ).strip(),
        'email': (
            os.environ.get('LEGAL_EMAIL')
            or 'paconavarro.fsn@gmail.com'
        ).strip(),
    }


def _require_marketing():
    if not is_marketing_host(normalize_host(request.host)):
        abort(404)


def render_landing():
    return render_template(
        'marketing/landing.html',
        current_year=datetime.utcnow().year,
    )


@marketing_bp.route('/alta', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour', methods=['POST'])
def alta():
    _require_marketing()
    from app.services.signup_service import SignupError, registrar_empresa

    if request.method == 'POST':
        try:
            admin_email = (request.form.get('admin_email') or '').strip().lower()
            tenant, email_enviado = registrar_empresa(
                nombre_empresa=request.form.get('nombre_empresa'),
                subdominio=request.form.get('subdominio'),
                admin_email=admin_email,
                admin_password=request.form.get('admin_password'),
                admin_password2=request.form.get('admin_password2'),
                acepta_privacidad=bool(request.form.get('acepta_privacidad')),
                acepta_condiciones=bool(request.form.get('acepta_condiciones')),
            )
            if not email_enviado:
                flash(
                    'Tu espacio se ha creado, pero no hemos podido enviar el correo '
                    'de verificación. Revisa la configuración de correo del servidor '
                    'o contacta con soporte.',
                    'warning',
                )
            return render_template(
                'marketing/alta_pendiente.html',
                current_year=datetime.utcnow().year,
                email=admin_email,
                subdomain=tenant.subdominio,
                base_domain=_alta_base_domain(),
            )
        except SignupError as exc:
            flash(str(exc), 'danger')
        except Exception:
            flash(
                'No se ha podido crear la cuenta. Prueba otro subdominio o contacta con soporte.',
                'danger',
            )

    return render_template(
        'marketing/alta.html',
        current_year=datetime.utcnow().year,
        form=request.form if request.method == 'POST' else {},
        base_domain=_alta_base_domain(),
    )


def _alta_base_domain():
    host = normalize_host(request.host)
    if host in ('localhost', '127.0.0.1', 'web') or host.endswith('.localhost'):
        return 'localhost'
    return 'signaplan.com'


@marketing_bp.route('/entrar', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 40 per hour', methods=['POST'])
def entrar():
    """
    Resolver de acceso: correo → tenant(s) con login web.
    La contraseña se pide siempre en el host del tenant.
    """
    _require_marketing()
    from app.services.signup_service import url_acceso_tenant
    from app.services.tenant_email_lookup_service import buscar_tenants_por_email
    from urllib.parse import quote

    if request.method == 'GET':
        return render_template(
            'marketing/entrar.html',
            current_year=datetime.utcnow().year,
            email=request.args.get('email') or '',
        )

    email = (request.form.get('email') or '').strip().lower()
    if not email or '@' not in email:
        flash('Indica un correo válido.', 'danger')
        return render_template(
            'marketing/entrar.html',
            current_year=datetime.utcnow().year,
            email=email,
        )

    matches = buscar_tenants_por_email(email)
    if not matches:
        flash(
            'No encontramos una empresa activa con acceso web para ese correo. '
            'Si acabas de darte de alta, prueba el enlace del correo o contacta con soporte.',
            'warning',
        )
        return render_template(
            'marketing/entrar.html',
            current_year=datetime.utcnow().year,
            email=email,
        )

    def _login_url(tenant):
        path = f'/auth/login?email={quote(email, safe="")}'
        return url_acceso_tenant(tenant, path=path)

    if len(matches) == 1:
        return redirect(_login_url(matches[0]['tenant']))

    items = [
        {
            'tenant': m['tenant'],
            'user_name': m['user_name'],
            'login_url': _login_url(m['tenant']),
        }
        for m in matches
    ]
    return render_template(
        'marketing/entrar_selector.html',
        current_year=datetime.utcnow().year,
        email=email,
        matches=items,
        base_domain=_alta_base_domain(),
    )


@marketing_bp.route('/legal/<slug>')
def legal(slug):
    _require_marketing()
    page = LEGAL_PAGES.get(slug)
    if not page:
        abort(404)
    return render_template(
        page['template'],
        current_year=datetime.utcnow().year,
        page_title=page['title'],
        legal=_legal_entity(),
    )
