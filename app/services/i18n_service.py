# app/services/i18n_service.py
#
# Idioma de la plataforma: cookie / preferencia de usuario / país / Accept-Language.
# Catálogo propio para no depender de compilar .mo en cada despliegue.

from __future__ import annotations

from flask import g, has_request_context, request, session

from app.services.i18n_catalog_app import APP_UI_EN, APP_UI_FR, APP_UI_PT

SUPPORTED_LOCALES = ('es', 'en', 'pt', 'fr')
DEFAULT_LOCALE = 'es'

MONTHS_ES = (
    '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
)
WEEKDAYS_SHORT_ES = ('DOM', 'LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB')

LOCALE_LABELS = {
    'es': 'Español',
    'en': 'English',
    'pt': 'Português',
    'fr': 'Français',
}

# País (ISO) → idioma por defecto al entrar.
COUNTRY_LOCALE = {
    'ES': 'es', 'MX': 'es', 'AR': 'es', 'CO': 'es', 'CL': 'es', 'PE': 'es',
    'EC': 'es', 'UY': 'es', 'PY': 'es', 'BO': 'es', 'CR': 'es', 'PA': 'es',
    'GT': 'es', 'HN': 'es', 'SV': 'es', 'NI': 'es', 'DO': 'es', 'VE': 'es',
    'PT': 'pt', 'BR': 'pt',
    'FR': 'fr', 'BE': 'fr', 'LU': 'fr', 'MC': 'fr',
    'US': 'en', 'GB': 'en', 'IE': 'en', 'CA': 'en', 'AU': 'en', 'NZ': 'en',
    'DE': 'en', 'NL': 'en', 'IT': 'en', 'AT': 'en', 'CH': 'en', 'SE': 'en',
    'NO': 'en', 'DK': 'en', 'FI': 'en', 'PL': 'en', 'CZ': 'en', 'RO': 'en',
}

# Claves de marketing / UI compartida. Ampliar según se traduzca el producto.
_CATALOG = {
    'es': {
        'nav.features': 'Funciones',
        'nav.access': 'Acceso clientes',
        'nav.integrations': 'Integraciones',
        'nav.signup': 'Crear cuenta',
        'nav.cta': 'Empezar gratis',
        'nav.lang': 'Idioma',
        'hero.brand': 'SignaPlan',
        'hero.headline': 'Quién va a cada obra. Quién ficha. Qué coche está libre.',
        'hero.sub': (
            'Cuadrante de personal, fichaje en el tajo y flota en la misma herramienta. '
            'Para constructoras PYME: no es un ERP de presupuestos. Alta sin tarjeta.'
        ),
        'hero.cta_primary': 'Crear cuenta gratuita',
        'hero.cta_secondary': 'Ver cómo encaja',
        'hero.proof': 'Sin tarjeta · Espacio propio en minutos',
        'suite.title': 'No es solo fichaje. Es el conjunto.',
        'suite.sub': (
            'Planificación, fichaje y flota en la misma herramienta: '
            'menos ir y venir entre apps y más control del día a día en obra.'
        ),
        'suite.plan.title': 'Cuadrante de personal',
        'suite.plan.body': 'Quién va a cada tajo cada día. No es un Gantt ni un ERP: es el tablero de peones.',
        'suite.clock.title': 'Fichaje en obra',
        'suite.clock.body': 'DNI + PIN en el móvil. Pausas, conforme del trabajador e informe listo para inspección.',
        'suite.fleet.title': 'Flota y coches libres',
        'suite.fleet.body': 'Asignación de vehículos alineada con ausencias y el cuadrante de personal.',
        'erp.title': 'Integraciones con tu ERP',
        'erp.body': (
            'Conectamos SignaPlan con Odoo y otros ERPs como proyecto a medida: '
            'personal, obras, ausencias o fichajes según tu sistema. '
            'Cuéntanos qué usáis y lo diseñamos juntos.'
        ),
        'erp.cta': 'Hablar de una integración',
        'legal.title': 'Registro de jornada con trazabilidad',
        'legal.body': (
            'Libro append-only con cadena de hashes, pausas, conforme digital del trabajador '
            'y PDF/CSV con huella. Documentación laboral sin Excel eterno.'
        ),
        'access.title': '¿Ya eres cliente?',
        'access.body': (
            'Cada empresa tiene su propia URL. Si no la recuerdas o no te llegó el correo '
            'de verificación, pide el acceso con tu email.'
        ),
        'access.example': 'tuempresa.signaplan.com',
        'access.cta': 'Entrar / recuperar acceso',
        'cta.title': 'Pon el día a día de obra en orden',
        'cta.body': 'Empieza gratis. Si quieres una demo con tu equipo, escríbenos.',
        'cta.mail': 'Hablar con nosotros',
        'nav.login': 'Entrar',
        'footer.login': 'Entrar',
        'footer.contact': 'Contacto',
        'footer.legal': 'Aviso legal',
        'footer.privacy': 'Privacidad',
        'footer.cookies': 'Cookies',
        'footer.terms': 'Condiciones',
        'footer.dpa': 'Encargo de tratamiento',
        'alta.title': 'Crea tu espacio SignaPlan',
        'pref.language_saved': 'Idioma actualizado.',
        'role.admin': 'Admin',
        'role.jefe_obra': 'Jefe de obra',
        'role.operario': 'Operario',
        'role.laboral': 'Laboral',
        'role.rrhh': 'RRHH',
    },
    'en': {
        'nav.features': 'Features',
        'nav.access': 'Customer access',
        'nav.integrations': 'Integrations',
        'nav.signup': 'Create account',
        'nav.cta': 'Start free',
        'nav.lang': 'Language',
        'hero.brand': 'SignaPlan',
        'hero.headline': 'Plan the site. Clock in on the field. Run the fleet.',
        'hero.sub': (
            'One platform for crew scheduling, mobile time clock with an immutable '
            'working-time ledger, and vehicles — built for construction day-to-day.'
        ),
        'hero.cta_primary': 'Create free account',
        'hero.cta_secondary': 'See how it fits',
        'hero.proof': 'No card · Your own workspace in minutes',
        'suite.title': 'Not just time clocking. The full stack.',
        'suite.sub': (
            'Scheduling, time clocking and fleet in one place — '
            'less switching between apps, more control of the site day.'
        ),
        'suite.plan.title': 'Site planner',
        'suite.plan.body': 'Who goes where each day. A clear board for office and site managers.',
        'suite.clock.title': 'On-site clocking',
        'suite.clock.body': 'ID + PIN on the phone. Breaks, worker confirmation and inspection-ready reports.',
        'suite.fleet.title': 'Fleet & free cars',
        'suite.fleet.body': 'Vehicle assignment aligned with leave and the crew schedule.',
        'erp.title': 'ERP integrations',
        'erp.body': (
            'We connect SignaPlan to Odoo and other ERPs as a custom project: '
            'people, sites, leave or time clocking to match your system. '
            'Tell us what you use and we will design it with you.'
        ),
        'erp.cta': 'Talk about an integration',
        'legal.title': 'Working-time record with traceability',
        'legal.body': (
            'Append-only ledger with hash chain, breaks, digital worker confirmation '
            'and PDF/CSV fingerprint. Labour documentation without endless spreadsheets.'
        ),
        'access.title': 'Already a customer?',
        'access.body': (
            'Each company has its own URL. If you forgot it or never got the verification '
            'email, request access with your address.'
        ),
        'access.example': 'yourcompany.signaplan.com',
        'access.cta': 'Sign in / recover access',
        'cta.title': 'Get the site day under control',
        'cta.body': 'Start free. Want a guided demo with your team? Email us.',
        'cta.mail': 'Talk to us',
        'nav.login': 'Sign in',
        'footer.login': 'Sign in',
        'footer.contact': 'Contact',
        'footer.legal': 'Legal notice',
        'footer.privacy': 'Privacy',
        'footer.cookies': 'Cookies',
        'footer.terms': 'Terms',
        'footer.dpa': 'Data processing',
        'alta.title': 'Create your SignaPlan workspace',
        'pref.language_saved': 'Language updated.',
    },
    'pt': {
        'nav.features': 'Funções',
        'nav.access': 'Acesso clientes',
        'nav.integrations': 'Integrações',
        'nav.signup': 'Criar conta',
        'nav.cta': 'Começar grátis',
        'nav.lang': 'Idioma',
        'hero.brand': 'SignaPlan',
        'hero.headline': 'Planeie a obra. Registe o ponto no campo. Controle a frota.',
        'hero.sub': (
            'Uma plataforma para planeamento de equipas, ponto móvel com registo de jornada '
            'inalterável e veículos — feita para o dia a dia da construção.'
        ),
        'hero.cta_primary': 'Criar conta gratuita',
        'hero.cta_secondary': 'Ver como encaixa',
        'hero.proof': 'Sem cartão · O seu espaço em minutos',
        'suite.title': 'Não é só ponto. É o conjunto.',
        'suite.sub': (
            'Planeamento, ponto e frota na mesma ferramenta: '
            'menos ir e vir entre apps e mais controlo do dia a dia na obra.'
        ),
        'suite.plan.title': 'Planeador de obra',
        'suite.plan.body': 'Quem vai a cada frente cada dia. Quadro claro para escritório e chefes.',
        'suite.clock.title': 'Ponto na obra',
        'suite.clock.body': 'Documento + PIN no telemóvel. Pausas, conforme do trabalhador e relatório para inspeção.',
        'suite.fleet.title': 'Frota e carros livres',
        'suite.fleet.body': 'Atribuição de veículos alinhada com ausências e o quadro de pessoal.',
        'erp.title': 'Integrações com o seu ERP',
        'erp.body': (
            'Ligamos o SignaPlan ao Odoo e a outros ERPs como projeto à medida: '
            'pessoal, obras, ausências ou ponto conforme o seu sistema. '
            'Diga-nos o que usam e desenhamos juntos.'
        ),
        'erp.cta': 'Falar de uma integração',
        'legal.title': 'Registo de jornada com rastreabilidade',
        'legal.body': (
            'Livro append-only com cadeia de hashes, pausas, conforme digital '
            'e PDF/CSV com impressão digital. Documentação laboral sem Excel eterno.'
        ),
        'access.title': 'Já é cliente?',
        'access.body': (
            'Cada empresa tem o seu URL. Se não o lembrar ou não recebeu o email '
            'de verificação, peça o acesso com o seu endereço.'
        ),
        'access.example': 'suaempresa.signaplan.com',
        'access.cta': 'Entrar / recuperar acesso',
        'cta.title': 'Organize o dia a dia da obra',
        'cta.body': 'Comece grátis. Quer uma demo com a sua equipa? Escreva-nos.',
        'cta.mail': 'Falar connosco',
        'nav.login': 'Entrar',
        'footer.login': 'Entrar',
        'footer.contact': 'Contacto',
        'footer.legal': 'Aviso legal',
        'footer.privacy': 'Privacidade',
        'footer.cookies': 'Cookies',
        'footer.terms': 'Condições',
        'footer.dpa': 'Encarregado do tratamento',
        'alta.title': 'Crie o seu espaço SignaPlan',
        'pref.language_saved': 'Idioma atualizado.',
    },
    'fr': {
        'nav.features': 'Fonctions',
        'nav.access': 'Accès clients',
        'nav.integrations': 'Intégrations',
        'nav.signup': 'Créer un compte',
        'nav.cta': 'Commencer gratuitement',
        'nav.lang': 'Langue',
        'hero.brand': 'SignaPlan',
        'hero.headline': 'Planifiez le chantier. Pointez sur le terrain. Gérez la flotte.',
        'hero.sub': (
            'Une plateforme pour le planning des équipes, le pointage mobile avec registre '
            'inaltérable et les véhicules — pensée pour le quotidien du BTP.'
        ),
        'hero.cta_primary': 'Créer un compte gratuit',
        'hero.cta_secondary': 'Voir comment ça s’intègre',
        'hero.proof': 'Sans carte · Votre espace en quelques minutes',
        'suite.title': 'Pas seulement le pointage. L’ensemble.',
        'suite.sub': (
            'Planning, pointage et flotte dans le même outil : '
            'moins d’allers-retours entre apps, plus de contrôle du quotidien sur chantier.'
        ),
        'suite.plan.title': 'Planning de chantier',
        'suite.plan.body': 'Qui va où chaque jour. Un tableau clair pour le bureau et les chefs.',
        'suite.clock.title': 'Pointage sur site',
        'suite.clock.body': 'Pièce d’identité + PIN sur le téléphone. Pauses, accord du salarié et rapport d’inspection.',
        'suite.fleet.title': 'Flotte et véhicules libres',
        'suite.fleet.body': 'Affectation des véhicules alignée sur les absences et le planning.',
        'erp.title': 'Intégrations avec votre ERP',
        'erp.body': (
            'Nous connectons SignaPlan à Odoo et à d’autres ERP en projet sur mesure : '
            'personnel, chantiers, absences ou pointage selon votre système. '
            'Dites-nous ce que vous utilisez, nous le concevons avec vous.'
        ),
        'erp.cta': 'Parler d’une intégration',
        'legal.title': 'Registre du temps de travail traçable',
        'legal.body': (
            'Registre append-only avec chaîne de hachage, pauses, confirmation numérique '
            'et PDF/CSV empreinté. Documentation sociale sans Excel éternel.'
        ),
        'access.title': 'Déjà client ?',
        'access.body': (
            'Chaque entreprise a sa propre URL. Si vous l’avez oubliée ou n’avez pas reçu '
            'l’e-mail de vérification, demandez l’accès avec votre adresse.'
        ),
        'access.example': 'votreentreprise.signaplan.com',
        'access.cta': 'Se connecter / récupérer l’accès',
        'cta.title': 'Mettez le chantier sous contrôle',
        'cta.body': 'Commencez gratuitement. Envie d’une démo avec votre équipe ? Écrivez-nous.',
        'cta.mail': 'Nous contacter',
        'nav.login': 'Connexion',
        'footer.login': 'Connexion',
        'footer.contact': 'Contact',
        'footer.legal': 'Mentions légales',
        'footer.privacy': 'Confidentialité',
        'footer.cookies': 'Cookies',
        'footer.terms': 'Conditions',
        'footer.dpa': 'Sous-traitance',
        'alta.title': 'Créez votre espace SignaPlan',
        'pref.language_saved': 'Langue mise à jour.',
    },
}

# Panel: msgid = texto español de las plantillas.
_CATALOG['en'].update(APP_UI_EN)
_CATALOG['pt'].update(APP_UI_PT)
_CATALOG['fr'].update(APP_UI_FR)


def normalize_locale(value):
    if not value:
        return None
    code = str(value).strip().lower().replace('_', '-')
    primary = code.split('-', 1)[0]
    if primary in SUPPORTED_LOCALES:
        return primary
    return None


def locale_from_accept_language(header):
    if not header:
        return None
    for part in header.split(','):
        tag = part.split(';', 1)[0].strip()
        loc = normalize_locale(tag)
        if loc:
            return loc
    return None


def locale_from_country(country_code):
    if not country_code:
        return None
    return COUNTRY_LOCALE.get(str(country_code).strip().upper())


def detect_request_locale(user=None):
    """
    Orden: ?lang → cookie → sesión → preferencia usuario → país → Accept-Language → es.
    """
    if has_request_context():
        q = normalize_locale(request.args.get('lang'))
        if q:
            return q
        cookie = normalize_locale(request.cookies.get('signaplan_lang'))
        if cookie:
            return cookie
        sess = normalize_locale(session.get('locale'))
        if sess:
            return sess

    if user is not None and getattr(user, 'is_authenticated', False):
        pref = normalize_locale(getattr(user, 'locale', None))
        if pref:
            return pref

    if has_request_context():
        country = (
            request.headers.get('CF-IPCountry')
            or request.headers.get('X-Appengine-Country')
            or request.headers.get('CloudFront-Viewer-Country')
        )
        from_country = locale_from_country(country)
        if from_country:
            return from_country
        from_accept = locale_from_accept_language(request.headers.get('Accept-Language'))
        if from_accept:
            return from_accept

    return DEFAULT_LOCALE


def get_locale():
    if has_request_context() and getattr(g, 'locale', None):
        return g.locale
    return DEFAULT_LOCALE


def translate(key, locale=None):
    """
    Traduce una clave (nav.features) o un msgid en español de plantilla (Tablero).
    Si falta la traducción, cae al español / al propio texto.
    """
    if key is None:
        return ''
    key = str(key)
    loc = normalize_locale(locale) or get_locale()
    bag = _CATALOG.get(loc) or {}
    if key in bag:
        return bag[key]
    if loc != DEFAULT_LOCALE:
        es_bag = _CATALOG.get(DEFAULT_LOCALE) or {}
        if key in es_bag:
            return es_bag[key]
    return key


def role_label(role):
    """Etiqueta de rol según idioma activo."""
    key = f'role.{role}' if role else ''
    labeled = translate(key)
    if labeled != key:
        return labeled
    return (role or '').replace('_', ' ').title()


def _(key):
    return translate(key)


def frontend_catalog(locale=None):
    """Catálogo ligero expuesto al frontend para JS y scripts inline."""
    loc = normalize_locale(locale) or get_locale()
    bag = dict(_CATALOG.get(DEFAULT_LOCALE) or {})
    if loc != DEFAULT_LOCALE:
        bag.update(_CATALOG.get(loc) or {})
    return bag


def month_name(month, locale=None):
    """Nombre de mes 1–12 en el idioma activo (msgid español capitalizado)."""
    try:
        m = int(month)
    except (TypeError, ValueError):
        return ''
    if m < 1 or m > 12:
        return ''
    return translate(MONTHS_ES[m], locale)


def weekday_short(dt, locale=None):
    """Abreviatura de día (DOM/LUN…) según idioma. dt.weekday(): lun=0."""
    idx = (dt.weekday() + 1) % 7
    return translate(WEEKDAYS_SHORT_ES[idx], locale)


_PAIR_CACHE = {}


def _translation_pairs(locale):
    """Pares (español, traducido) ordenados de más largo a más corto.

    Short catalog keys (buttons, labels) are excluded here so the HTML
    document pass cannot corrupt longer phrases; translate()/_() still use them.
    """
    loc = normalize_locale(locale) or DEFAULT_LOCALE
    if loc == DEFAULT_LOCALE:
        return []
    cached = _PAIR_CACHE.get(loc)
    if cached is not None:
        return cached
    bag = dict(_CATALOG.get(DEFAULT_LOCALE) or {})
    bag.update(_CATALOG.get(loc) or {})
    # Solo frases cuyo msgid es texto español visible (no claves tipo nav.x)
    pairs = []
    for src, dst in bag.items():
        if not src or not dst or src == dst:
            continue
        if '.' in src and src.split('.', 1)[0] in (
            'nav', 'hero', 'suite', 'erp', 'legal', 'access', 'cta', 'footer', 'alta',
            'pref', 'role',
        ):
            continue
        pairs.append((src, dst))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    # HTML auto-replace must not use short tokens: they corrupt longer phrases
    # (e.g. "Todas"->"Toutes" inside "Todas las obras"; "Desde" inside hints).
    MIN_HTML_LEN = 14
    long_srcs = [s for s, _ in pairs if len(s) >= MIN_HTML_LEN]
    filtered = []
    for src, dst in pairs:
        if len(src) < MIN_HTML_LEN:
            continue
        # skip if this src is a proper substring of a longer catalog phrase
        if any(src != other and src in other for other in long_srcs):
            continue
        filtered.append((src, dst))
    pairs = filtered
    _PAIR_CACHE[loc] = pairs
    return pairs

def translate_html_document(html, locale=None):
    """
    Sustituye textos de interfaz en español dentro del HTML renderizado.

    Así no hace falta envolver a mano cada plantilla: menús, títulos, logs,
    botones y etiquetas pasan al idioma activo. No toca JSON de APIs.
    Nombres de obra / datos que mete el usuario no están en el catálogo → no se tocan.
    """
    import re

    loc = normalize_locale(locale) or get_locale()
    if loc == DEFAULT_LOCALE or not html:
        return html

    pairs = _translation_pairs(loc)
    if not pairs:
        return html

    # No tocar lógica JS ni CSS: protegemos <script>…</script> y <style>…</style>.
    placeholders = []

    def _park(match):
        placeholders.append(match.group(0))
        return f'<!--SP_I18N_{len(placeholders) - 1}-->'

    protected = re.sub(
        r'(?is)<(script|style)\b[^>]*>.*?</\1>',
        _park,
        html,
    )

    # Siempre límites de palabra: evita «Nombre» → «Name» dentro de «Nombres».
    boundary = r'A-Za-zÁÉÍÓÚÜáéíóúüÑñ0-9'
    for src, dst in pairs:
        if src not in protected:
            continue
        protected = re.sub(
            rf'(?<![{boundary}]){re.escape(src)}(?![{boundary}])',
            dst,
            protected,
        )

    def _restore(match):
        idx = int(match.group(1))
        return placeholders[idx]

    return re.sub(r'<!--SP_I18N_(\d+)-->', _restore, protected)


def set_locale_cookie(response, locale):
    loc = normalize_locale(locale) or DEFAULT_LOCALE
    response.set_cookie(
        'signaplan_lang',
        loc,
        max_age=365 * 24 * 3600,
        samesite='Lax',
        secure=False,
        path='/',
    )
    return response
