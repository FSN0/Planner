# app/marketing/routes.py
#
# Web pública en signaplan.com: landing, alta de empresa y textos legales.

from datetime import datetime

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from app import limiter
from app.marketing.seo_articles import get_article, list_articles
from app.marketing.seo_solutions import get_solution, list_solutions
from app.services.i18n_service import get_locale, marketing_path, translate
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
    """Datos del titular. Sobreescribibles por env sin tocar plantillas.

    En fase beta gratuita no publicamos la dirección postal del prestador:
    LSSI exige contactar con el prestador (nombre + NIF + email), y con el
    email de contacto se cumple. Cuando se contrate una dirección
    profesional (apartado de Correos o similar) se rellena LEGAL_DOMICILIO
    por env y aparece automáticamente en Aviso Legal y en el Encargo de
    Tratamiento sin tocar plantillas.
    """
    import os
    return {
        'razon_social': (
            os.environ.get('LEGAL_RAZON_SOCIAL') or 'Francisco Navarro Hernández'
        ).strip(),
        'nif': (os.environ.get('LEGAL_NIF') or '18461268L').strip(),
        'domicilio': (os.environ.get('LEGAL_DOMICILIO') or '').strip(),
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


def _mkt_redirect(endpoint, **values):
    """Redirect that keeps /en /pt /fr so Google and the user stay on the same language."""
    return redirect(marketing_path(url_for(endpoint, **values), get_locale()))


def render_landing():
    return render_template(
        'marketing/landing.html',
        current_year=datetime.utcnow().year,
    )


def _pendiente_page(email, subdomain, email_enviado, reserva=None):
    html = render_template(
        'marketing/alta_pendiente.html',
        current_year=datetime.utcnow().year,
        email=email,
        subdomain=subdomain,
        base_domain=_alta_base_domain(),
        email_enviado=email_enviado,
        estado_url=url_for('marketing.alta_estado'),
    )
    resp = make_response(html)
    if reserva is not None:
        from app.services.signup_service import attach_wait_cookie
        attach_wait_cookie(resp, reserva)
    return resp


@marketing_bp.route('/alta', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour', methods=['POST'])
def alta():
    _require_marketing()
    from app.services.signup_service import SignupError, registrar_empresa

    if request.method == 'POST':
        try:
            admin_email = (request.form.get('admin_email') or '').strip().lower()
            reserva, email_enviado = registrar_empresa(
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
                    translate(
                        'Hemos reservado el subdominio, pero no hemos podido enviar el correo '
                        'de confirmación. Reenvíalo desde esta página.'
                    ),
                    'warning',
                )
            return _pendiente_page(
                admin_email, reserva.subdominio, email_enviado, reserva=reserva
            )
        except SignupError as exc:
            flash(str(exc), 'danger')
        except Exception:
            flash(
                translate(
                    'No se ha podido crear la cuenta. Prueba otro subdominio o contacta con soporte.'
                ),
                'danger',
            )

    return render_template(
        'marketing/alta.html',
        current_year=datetime.utcnow().year,
        form=request.form if request.method == 'POST' else {},
        base_domain=_alta_base_domain(),
    )


@marketing_bp.route('/alta/estado')
@limiter.limit('30 per minute')
def alta_estado():
    """Poll de la pestaña «Revisa tu correo»: no provisiona, no filtra emails."""
    _require_marketing()
    from app.services.signup_service import COOKIE_NAME, estado_reserva, reserva_desde_cookie

    reserva = reserva_desde_cookie(request.cookies.get(COOKIE_NAME))
    return jsonify(estado_reserva(reserva))


@marketing_bp.route('/alta/confirmar', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 30 per hour')
def alta_confirmar():
    """
    GET: muestra el botón (los prefetches de Outlook no deben crear el tenant).
    POST: crea el espacio. En el ordenador entra en esta pestaña; en el móvil
    deja que siga la pestaña de espera del PC.
    """
    _require_marketing()
    from app.services.signup_service import (
        SignupError,
        confirmar_reserva,
        es_cliente_movil,
        inspeccionar_reserva,
        url_ticket_tenant,
        _tenant_de_reserva,
    )

    token = (request.values.get('t') or '').strip()
    if not token:
        flash(translate('Falta el enlace de confirmación.'), 'danger')
        return _mkt_redirect('marketing.alta')

    def _entrar_si_escritorio(reserva, tenant):
        """En el PC el enlace abre el espacio aquí; en el móvil sigue la pestaña de espera."""
        if tenant is None or es_cliente_movil():
            return None
        try:
            return redirect(url_ticket_tenant(reserva, tenant))
        except SignupError:
            return None

    def _confirmar_view(reserva, tenant=None, creating=False):
        ready = tenant is not None
        ticket_url = url_ticket_tenant(reserva, tenant) if ready else ''
        auto_open = bool(ticket_url) and not es_cliente_movil()
        return render_template(
            'marketing/alta_confirmar.html',
            current_year=datetime.utcnow().year,
            token=token,
            subdomain=reserva.subdominio,
            base_domain=_alta_base_domain(),
            ready=ready,
            creating=creating,
            ticket_url=ticket_url,
            auto_open=auto_open,
        )

    if request.method == 'GET':
        try:
            reserva = inspeccionar_reserva(token)
        except SignupError as exc:
            flash(str(exc), 'danger')
            return _mkt_redirect('marketing.alta')
        if reserva.status == 'ready':
            tenant = _tenant_de_reserva(reserva)
            entra = _entrar_si_escritorio(reserva, tenant)
            if entra is not None:
                return entra
            return _confirmar_view(reserva, tenant)
        if reserva.status == 'provisioning':
            return _confirmar_view(reserva, creating=True)
        return _confirmar_view(reserva)

    try:
        reserva, tenant = confirmar_reserva(token)
    except SignupError as exc:
        flash(str(exc), 'danger')
        return _mkt_redirect('marketing.alta')
    entra = _entrar_si_escritorio(reserva, tenant)
    if entra is not None:
        return entra
    return _confirmar_view(reserva, tenant, creating=tenant is None)


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

    mensaje_generico = translate(
        'Si hay una cuenta o una alta pendiente con ese correo, te hemos enviado un email. '
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
        flash(translate('Indica un correo válido.'), 'danger')
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
    try:
        from app.services.signup_service import reenviar_reservas_por_email
        reenviar_reservas_por_email(email)
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
    """Reenvío desde la pantalla de espera, sin tenant creado todavía."""
    _require_marketing()
    from app.services.signup_service import COOKIE_NAME, reenviar_confirmacion, reserva_desde_cookie

    email = (request.form.get('email') or '').strip().lower()
    subdomain = (request.form.get('subdomain') or '').strip().lower()
    if not email or not subdomain:
        flash(translate('Faltan datos para reenviar la confirmación.'), 'danger')
        return _mkt_redirect('marketing.alta')

    try:
        reenviar_confirmacion(email, subdomain)
    except Exception:
        pass
    flash(
        translate(
            'Si el correo está pendiente de confirmación, te hemos enviado un nuevo enlace. '
            'Revisa también spam.'
        ),
        'info',
    )
    reserva = reserva_desde_cookie(request.cookies.get(COOKIE_NAME))
    return _pendiente_page(email, subdomain, True, reserva=reserva)


DEMO_YOUTUBE_ID = 'HPKfP7fK2IQ'


@marketing_bp.route('/demo')
def demo():
    _require_marketing()
    return render_template(
        'marketing/demo.html',
        current_year=datetime.utcnow().year,
        youtube_id=DEMO_YOUTUBE_ID,
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
            flash(translate('Mensaje enviado. Te responderemos lo antes posible.'), 'success')
            return _mkt_redirect('marketing.contacto')

        form = {
            'nombre': (request.form.get('nombre') or '').strip()[:120],
            'email': (request.form.get('email') or '').strip().lower()[:120],
            'empresa': (request.form.get('empresa') or '').strip()[:160],
            'mensaje': (request.form.get('mensaje') or '').strip()[:4000],
        }
        if not form['nombre'] or '@' not in form['email'] or len(form['mensaje']) < 10:
            flash(translate('Completa nombre, un correo válido y un mensaje (mín. 10 caracteres).'), 'danger')
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
            ok = False
            from app.services.notification_dispatch_service import event_allows_send
            if event_allows_send('marketing_contact'):
                ok = send_email(asunto, [destino], texto, html_body=html)
            if ok:
                flash(translate('Mensaje enviado. Te responderemos lo antes posible.'), 'success')
                return _mkt_redirect('marketing.contacto')
            flash(
                translate(
                    'No hemos podido enviar el mensaje ahora. Escríbenos a {email} o inténtalo más tarde.',
                    email=destino,
                ),
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
        legal_slug=slug,
        legal=_legal_entity(),
    )


@marketing_bp.route('/recursos/')
def recursos_index():
    _require_marketing()
    legal = _legal_entity()
    return render_template(
        'marketing/recursos_index.html',
        current_year=datetime.utcnow().year,
        articles=list_articles(get_locale()),
        contact_email=legal.get('email'),
    )


@marketing_bp.route('/recursos/<slug>')
def recurso(slug):
    _require_marketing()
    article = get_article(slug, get_locale())
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
        solutions=list_solutions(get_locale()),
        contact_email=legal.get('email'),
    )


@marketing_bp.route('/soluciones/<slug>')
def solucion(slug):
    _require_marketing()
    solution = get_solution(slug, get_locale())
    if not solution:
        abort(404)
    legal = _legal_entity()
    related = [s for s in list_solutions(get_locale()) if s['slug'] != slug][:3]
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
    from app.services.seo_origin_service import marketing_url
    sitemap = marketing_url('/sitemap.xml')
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /auth/\n"
        "Disallow: /superadmin\n"
        "Disallow: /api/\n"
        "Disallow: /sync\n"
        "Disallow: /preferencias/\n"
        f"Sitemap: {sitemap}\n"
    )
    return Response(body, mimetype='text/plain')


@marketing_bp.route('/sitemap.xml')
def sitemap_xml():
    _require_marketing()
    from app.services.i18n_service import SUPPORTED_LOCALES, DEFAULT_LOCALE, marketing_path
    from app.services.seo_origin_service import marketing_origin

    base = marketing_origin()
    paths = [
        ('/', '1.0', 'weekly', None),
        ('/alta', '0.8', 'monthly', None),
        ('/entrar', '0.6', 'monthly', None),
        ('/contacto', '0.7', 'monthly', None),
        ('/demo', '0.9', 'monthly', None),
        ('/soluciones/', '0.9', 'weekly', None),
        ('/recursos/', '0.7', 'weekly', None),
    ]
    for slug in LEGAL_PAGES:
        paths.append((f'/legal/{slug}', '0.3', 'yearly', None))
    for s in list_solutions():
        paths.append((f"/soluciones/{s['slug']}", '0.85', 'monthly', s.get('updated')))
    for a in list_articles():
        paths.append((f"/recursos/{a['slug']}", '0.65', 'monthly', a.get('updated')))

    def loc_url(path, locale):
        return base + marketing_path(path, locale)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '        xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    for path, prio, freq, lastmod in paths:
        for locale in SUPPORTED_LOCALES:
            parts.append('  <url>')
            parts.append(f'    <loc>{loc_url(path, locale)}</loc>')
            if lastmod:
                parts.append(f'    <lastmod>{lastmod}</lastmod>')
            parts.append(f'    <changefreq>{freq}</changefreq>')
            parts.append(f'    <priority>{prio}</priority>')
            for alt in SUPPORTED_LOCALES:
                parts.append(
                    f'    <xhtml:link rel="alternate" hreflang="{alt}" '
                    f'href="{loc_url(path, alt)}"/>'
                )
            parts.append(
                f'    <xhtml:link rel="alternate" hreflang="x-default" '
                f'href="{loc_url(path, DEFAULT_LOCALE)}"/>'
            )
            parts.append('  </url>')
    parts.append('</urlset>')
    return Response('\n'.join(parts) + '\n', mimetype='application/xml')
