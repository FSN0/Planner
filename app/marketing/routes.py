# app/marketing/routes.py
#
# Web pública en signaplan.com: landing, alta de empresa y textos legales.

from datetime import datetime

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app import limiter
from app.marketing.seo_articles import get_article, list_articles
from app.marketing.seo_solutions import get_solution, list_solutions
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
            or 'info@signaplan.com'
        ).strip(),
    }


def _contact_email():
    """Buzón comercial público (no el correo personal del titular legal)."""
    import os
    return (
        os.environ.get('CONTACT_EMAIL')
        or os.environ.get('MAIL_DEFAULT_SENDER')
        or os.environ.get('MAIL_USERNAME')
        or 'info@signaplan.com'
    ).strip()


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
                    'de verificación. Puedes reenviarlo desde esta página o desde tu panel.',
                    'warning',
                )
            from app.services.signup_service import url_acceso_tenant
            return render_template(
                'marketing/alta_pendiente.html',
                current_year=datetime.utcnow().year,
                email=admin_email,
                subdomain=tenant.subdominio,
                base_domain=_alta_base_domain(),
                email_enviado=email_enviado,
                login_url=url_acceso_tenant(tenant, path='/auth/login'),
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
    Resolver de acceso: el usuario indica su correo y, si hay empresas,
    recibe los enlaces por email (sin enumerarlas en pantalla).
    """
    _require_marketing()
    from app.services.tenant_access_email_service import enviar_enlaces_acceso
    from app.services.tenant_email_lookup_service import buscar_tenants_por_email

    mensaje_generico = (
        'Si hay una cuenta con ese correo, te hemos enviado un email con el acceso '
        'a tu empresa (y el enlace de verificación si aún no lo confirmaste). '
        'Revisa la bandeja de entrada y el spam.'
    )

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
    if matches:
        try:
            enviar_enlaces_acceso(email, matches)
        except Exception:
            pass
    flash(mensaje_generico, 'info')
    return render_template(
        'marketing/entrar.html',
        current_year=datetime.utcnow().year,
        email=email,
    )


@marketing_bp.route('/reenviar-verificacion', methods=['POST'])
@limiter.limit('3 per minute; 10 per hour')
def reenviar_verificacion():
    """Reenvío desde marketing (post-alta) sin estar logueado en el tenant."""
    _require_marketing()
    from sqlalchemy import text

    from app import db
    from app.models import Tenant
    from app.services.email_verification_service import (
        EmailVerificationError,
        reenviar_verificacion as _reenviar,
    )

    email = (request.form.get('email') or '').strip().lower()
    subdomain = (request.form.get('subdomain') or '').strip().lower()
    if not email or not subdomain:
        flash('Faltan datos para reenviar la verificación.', 'danger')
        return redirect(url_for('marketing.alta'))

    tenant = Tenant.query.filter_by(subdominio=subdomain, is_active=True).first()
    if not tenant:
        # Mismo mensaje genérico: no delatar existencia
        flash(
            'Si la cuenta existe y el correo está pendiente, te hemos enviado un nuevo enlace.',
            'info',
        )
        return redirect(url_for('marketing.alta'))

    try:
        db.session.execute(text(f'SET search_path TO {tenant.schema_name}, public'))
        _reenviar(tenant, email=email)
        flash(
            'Si el correo está pendiente de verificación, te hemos enviado un nuevo enlace. '
            'Revisa también spam.',
            'info',
        )
    except EmailVerificationError as exc:
        flash(str(exc), 'danger')
    except Exception:
        flash('No se ha podido reenviar el correo ahora. Prueba más tarde.', 'danger')

    from app.services.signup_service import url_acceso_tenant
    return render_template(
        'marketing/alta_pendiente.html',
        current_year=datetime.utcnow().year,
        email=email,
        subdomain=tenant.subdominio,
        base_domain=_alta_base_domain(),
        email_enviado=True,
        login_url=url_acceso_tenant(tenant, path='/auth/login'),
    )


@marketing_bp.route('/contacto', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour', methods=['POST'])
def contacto():
    """Formulario de contacto → info@signaplan.com (buzón comercial)."""
    _require_marketing()
    from app.services.email_service import send_email

    destino = _contact_email()
    form = {}

    if request.method == 'POST':
        # Honeypot: si viene relleno, fingimos éxito
        if (request.form.get('website') or '').strip():
            flash('Mensaje enviado. Te responderemos lo antes posible.', 'success')
            return redirect(url_for('marketing.contacto'))

        form = {
            'nombre': (request.form.get('nombre') or '').strip()[:120],
            'email': (request.form.get('email') or '').strip().lower()[:120],
            'empresa': (request.form.get('empresa') or '').strip()[:160],
            'mensaje': (request.form.get('mensaje') or '').strip()[:4000],
        }
        if not form['nombre'] or '@' not in form['email'] or len(form['mensaje']) < 10:
            flash('Completa nombre, un correo válido y un mensaje (mín. 10 caracteres).', 'danger')
        else:
            asunto = f"Contacto SignaPlan — {form['nombre']}"
            if form['empresa']:
                asunto += f" ({form['empresa']})"
            texto = (
                f"Nombre: {form['nombre']}\n"
                f"Email: {form['email']}\n"
                f"Empresa: {form['empresa'] or '—'}\n\n"
                f"{form['mensaje']}\n"
            )
            html = (
                f"<p><strong>Nombre:</strong> {form['nombre']}<br>"
                f"<strong>Email:</strong> <a href=\"mailto:{form['email']}\">{form['email']}</a><br>"
                f"<strong>Empresa:</strong> {form['empresa'] or '—'}</p>"
                f"<p>{form['mensaje'].replace(chr(10), '<br>')}</p>"
            )
            ok = send_email(asunto, [destino], texto, html_body=html)
            if ok:
                flash('Mensaje enviado. Te responderemos lo antes posible.', 'success')
                return redirect(url_for('marketing.contacto'))
            flash(
                'No hemos podido enviar el mensaje ahora. Escríbenos a '
                f'{destino} o inténtalo más tarde.',
                'danger',
            )

    return render_template(
        'marketing/contacto.html',
        current_year=datetime.utcnow().year,
        form=form,
        contact_email=destino,
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


@marketing_bp.route('/recursos/')
def recursos_index():
    _require_marketing()
    legal = _legal_entity()
    return render_template(
        'marketing/recursos_index.html',
        current_year=datetime.utcnow().year,
        articles=list_articles(),
        contact_email=legal.get('email'),
    )


@marketing_bp.route('/recursos/<slug>')
def recurso(slug):
    _require_marketing()
    article = get_article(slug)
    if not article:
        abort(404)
    legal = _legal_entity()
    return render_template(
        'marketing/recursos_articulo.html',
        current_year=datetime.utcnow().year,
        slug=slug,
        article=article,
        contact_email=legal.get('email'),
    )


@marketing_bp.route('/soluciones/')
def soluciones_index():
    _require_marketing()
    legal = _legal_entity()
    return render_template(
        'marketing/soluciones_index.html',
        current_year=datetime.utcnow().year,
        solutions=list_solutions(),
        contact_email=legal.get('email'),
    )


@marketing_bp.route('/soluciones/<slug>')
def solucion(slug):
    _require_marketing()
    solution = get_solution(slug)
    if not solution:
        abort(404)
    legal = _legal_entity()
    related = [s for s in list_solutions() if s['slug'] != slug][:3]
    return render_template(
        'marketing/soluciones_articulo.html',
        current_year=datetime.utcnow().year,
        slug=slug,
        solution=solution,
        related=related,
        contact_email=legal.get('email'),
    )


@marketing_bp.route('/robots.txt')
def robots_txt():
    # Público en marketing host; en tenants no hace daño servir lo mismo.
    sitemap = url_for('marketing.sitemap_xml', _external=True)
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /auth/\n"
        "Disallow: /superadmin\n"
        "Disallow: /api/\n"
        "Disallow: /sync\n"
        f"Sitemap: {sitemap}\n"
    )
    return Response(body, mimetype='text/plain')


@marketing_bp.route('/sitemap.xml')
def sitemap_xml():
    _require_marketing()
    base = request.url_root.rstrip('/')
    urls = [
        ('/', '1.0', 'weekly'),
        ('/alta', '0.8', 'monthly'),
        ('/entrar', '0.6', 'monthly'),
        ('/contacto', '0.7', 'monthly'),
        ('/soluciones/', '0.9', 'weekly'),
        ('/recursos/', '0.7', 'weekly'),
    ]
    for slug in LEGAL_PAGES:
        urls.append((f'/legal/{slug}', '0.3', 'yearly'))
    for s in list_solutions():
        urls.append((f"/soluciones/{s['slug']}", '0.85', 'monthly'))
    for a in list_articles():
        urls.append((f"/recursos/{a['slug']}", '0.65', 'monthly'))

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, prio, freq in urls:
        parts.append('  <url>')
        parts.append(f'    <loc>{base}{path}</loc>')
        parts.append(f'    <changefreq>{freq}</changefreq>')
        parts.append(f'    <priority>{prio}</priority>')
        parts.append('  </url>')
    parts.append('</urlset>')
    return Response('\n'.join(parts) + '\n', mimetype='application/xml')
