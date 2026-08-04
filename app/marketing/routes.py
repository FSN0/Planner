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
        'razon_social': (os.environ.get('LEGAL_RAZON_SOCIAL') or 'SignaPlan').strip(),
        'nif': (os.environ.get('LEGAL_NIF') or '').strip(),
        'domicilio': (os.environ.get('LEGAL_DOMICILIO') or '').strip(),
        'email': (os.environ.get('LEGAL_EMAIL') or 'info@signaplan.com').strip(),
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
    from app.services.signup_service import (
        SignupError,
        registrar_empresa,
        url_entrada_automatica,
    )

    if request.method == 'POST':
        try:
            admin_email = request.form.get('admin_email')
            tenant = registrar_empresa(
                nombre_empresa=request.form.get('nombre_empresa'),
                subdominio=request.form.get('subdominio'),
                admin_email=admin_email,
                admin_password=request.form.get('admin_password'),
                admin_password2=request.form.get('admin_password2'),
                acepta_privacidad=bool(request.form.get('acepta_privacidad')),
                acepta_condiciones=bool(request.form.get('acepta_condiciones')),
            )
            # Salto al subdominio ya autenticado (la cookie de marketing no vale allí).
            return redirect(url_entrada_automatica(tenant, admin_email))
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
