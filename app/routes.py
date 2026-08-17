# app/routes.py
from datetime import date

from flask import Blueprint, redirect, url_for, request, flash, g
from flask_login import login_required, current_user, logout_user
from app import db
from app.models import ROLE_OPERARIO, ROLE_RRHH, ROLE_LABORAL
from app.services.tenant_domain_service import is_marketing_host, normalize_host
from app.services.i18n_service import translate
from app.marketing.routes import render_landing

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def dashboard():
    if is_marketing_host(normalize_host(request.host)):
        return render_landing()

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        return redirect(url_for('superadmin.dashboard'))

    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))

    if current_user.role == 'jefe_obra':
        return redirect(url_for('jefe.panel'))
    if current_user.role == 'admin':
        return redirect(url_for('admin.panel'))
    if current_user.role in (ROLE_LABORAL, ROLE_RRHH):
        return redirect(url_for('admin.panel_laboral'))
    if current_user.role == ROLE_OPERARIO:
        if getattr(current_user, 'web_access', False):
            return redirect(url_for('empleado.inicio'))
        logout_user()
        flash(translate('Tu perfil no tiene acceso a la aplicación.'), 'warning')
        return redirect(url_for('auth.login'))
    return redirect(url_for('auth.login'))


@main_bp.route('/preferencias/idioma', methods=['GET', 'POST'])
def update_user_locale():
    """Cambia idioma (cookie + sesión; si hay login, también en el usuario)."""
    from flask import make_response, session
    from app.services.i18n_service import (
        normalize_locale,
        set_locale_cookie,
        translate,
        DEFAULT_LOCALE,
    )

    if request.method == 'POST':
        raw = request.form.get('locale') or request.form.get('lang')
    else:
        raw = request.args.get('lang')

    locale = normalize_locale(raw) or DEFAULT_LOCALE
    session['locale'] = locale
    session.modified = True

    if current_user.is_authenticated:
        try:
            current_user.locale = locale
            db.session.commit()
        except Exception:
            db.session.rollback()

    dest = request.referrer or url_for('main.dashboard')
    if request.method == 'GET' and request.args.get('next'):
        nxt = request.args.get('next')
        if nxt.startswith('/'):
            dest = nxt

    # Evitar bucles si el referrer es la propia ruta de idioma.
    if dest and '/preferencias/idioma' in dest:
        dest = url_for('main.dashboard')

    if current_user.is_authenticated or request.method == 'POST':
        flash(translate('pref.language_saved', locale), 'success')

    resp = make_response(redirect(dest))
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return set_locale_cookie(resp, locale)
