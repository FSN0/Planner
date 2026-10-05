# app/auth/routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from app import limiter, db
from app.models import User, _utc_now
from app.services.external_auth_service import (
    can_attempt_external_auth,
    external_auth_allowed_for_user,
    external_auth_enabled_for_tenant,
    log_external_auth_result,
    verify_external_password,
)
from app.services.soltec_sso_service import (
    SoltecSsoError,
    build_portal_sso_redirect_url,
    verify_soltec_sso_token,
)
from app.services.tenant_domain_service import is_marketing_host, normalize_host
from app.services.i18n_service import translate

auth_bp = Blueprint('auth', __name__)


@auth_bp.before_request
def _enforce_auth_module_permissions():
    from app.services.permission_guard import enforce_auth_permissions
    return enforce_auth_permissions()


def _puede_login_web(user):
    """Cualquier perfil activo puede autenticarse; los permisos limitan qué ve."""
    return bool(user and not getattr(user, 'is_deleted', False))


def destino_portal_operario(user):
    """Reexport: ver user_home_service.destino_portal_operario."""
    from app.services.user_home_service import destino_portal_operario as _destino
    return _destino(user)


def _complete_login(user, remember, *, source, success_message=None):
    from app.utils import register_log

    user.auth_source_last = source
    db.session.add(user)
    db.session.flush()

    login_user(user, remember=remember)
    session['tenant_id'] = g.current_tenant.id
    # register_log no hace commit: hay que persistirlo con el resto del login.
    register_log(
        user_id=user.id,
        category='accesos',
        action='Inicio de Sesión',
        detail=(
            f"Login exitoso vía {source} desde IP: {request.remote_addr or 'Desconocida'}"
        ),
    )
    db.session.commit()
    flash(success_message or translate('Inicio de sesión exitoso'), 'success')

    destino = _destino_por_rol(user)
    if destino:
        return redirect(destino)

    logout_user()
    flash(translate('Tu perfil no tiene acceso a la aplicación.'), 'warning')
    return render_template('login.html', **_login_page_context())


def _commit_access_log():
    """Persiste logs de accesos pendientes (register_log no hace commit)."""
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _login_page_context():
    fichaje_activo = False
    try:
        from app.services.fichaje_operario_service import fichaje_operario_activo
        fichaje_activo = fichaje_operario_activo()
    except Exception:
        pass
    prefill = (request.args.get('email') or request.form.get('login') or request.form.get('email') or '').strip()
    return {
        'tenant_name': g.current_tenant.nombre,
        'fichaje_activo': fichaje_activo,
        'prefill_email': prefill,
        'prefill_login': prefill,
    }


def _destino_por_rol(user):
    """A dónde va cada perfil nada más entrar. None si no tiene sitio."""
    from app.services.user_home_service import home_url_for_user
    return home_url_for_user(user)


def _redirect_authenticated_user():
    destino = _destino_por_rol(current_user)
    if destino:
        return redirect(destino)
    logout_user()
    flash(translate('Tu perfil no tiene acceso a la aplicación.'), 'warning')
    return redirect(url_for('auth.login'))


@auth_bp.route('/ticket')
@limiter.limit('10 per minute; 30 per hour')
def signup_ticket():
    """Entrada corta tras confirmar el alta (pestaña del ordenador)."""
    from app.services.signup_service import SignupError, leer_ticket_acceso

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash(translate('Accede desde la URL de tu empresa.'), 'warning')
        return redirect(url_for('main.dashboard'))

    try:
        user_id = leer_ticket_acceso(request.args.get('t') or '', g.current_tenant)
    except SignupError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('auth.login'))

    from sqlalchemy import text
    db.session.execute(text(f'SET search_path TO {g.current_tenant.schema_name}, public'))
    user = User.query.filter_by(id=user_id, is_deleted=False).first()
    if user is None or not user.is_active:
        flash(translate('No se ha podido abrir la sesión. Entra con tu correo y contraseña.'), 'warning')
        return redirect(url_for('auth.login'))

    if current_user.is_authenticated:
        logout_user()

    login_user(user, remember=True)
    session['tenant_id'] = g.current_tenant.id
    try:
        from app.utils import register_log
        register_log(
            user_id=user.id,
            category='accesos',
            action='Inicio de Sesión',
            detail=(
                f'Login por ticket de alta. IP: {request.remote_addr or "Desconocida"}'
            ),
        )
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    destino = _destino_por_rol(user) or url_for('admin.panel')
    return render_template(
        'auth_email_verified_boot.html',
        destino=destino,
        titulo=translate('Entrando en SignaPlan'),
        subtitulo=translate('Preparando tu espacio…'),
    )


@auth_bp.route('/verificar-email')
@limiter.limit('10 per minute; 30 per hour')
def verificar_email():
    """Enlace antiguo al subdominio. El alta nueva confirma en /alta/confirmar."""
    from app.services.email_verification_service import (
        EmailVerificationError,
        confirmar_email,
    )

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash(translate('Accede desde la URL de tu empresa.'), 'warning')
        return redirect(url_for('main.dashboard'))

    token = request.args.get('t') or ''
    try:
        user = confirmar_email(token, g.current_tenant)
    except EmailVerificationError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('auth.login'))

    if current_user.is_authenticated:
        logout_user()

    # login_user lee is_active; el User debe estar fresco en el schema del tenant
    from sqlalchemy import text
    db.session.execute(
        text(f'SET search_path TO {g.current_tenant.schema_name}, public')
    )
    user = User.query.get(user.id)
    if user is None:
        flash(translate('No se ha podido abrir la sesión. Entra con tu correo y contraseña.'), 'warning')
        return redirect(url_for('auth.login'))

    login_user(user, remember=True)
    session['tenant_id'] = g.current_tenant.id
    try:
        from app.utils import register_log
        register_log(
            user_id=user.id,
            category='accesos',
            action='Verificación de correo',
            detail=(
                f'Correo verificado tras alta. IP: {request.remote_addr or "Desconocida"}'
            ),
        )
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    flash(translate('Correo verificado. Bienvenido a SignaPlan.'), 'success')
    try:
        destino = _destino_por_rol(user)
    except Exception:
        destino = None
    # Evitar DetachedInstanceError / sesión sucia en el siguiente request
    try:
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    destino = destino or url_for('admin.panel')
    # Pantalla mínima inmediata: el destino (p.ej. Primeros pasos) puede tardar;
    # así el usuario ve feedback en cuanto abre el enlace del correo.
    return render_template('auth_email_verified_boot.html', destino=destino)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 50 per hour', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return _redirect_authenticated_user()

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        host = normalize_host(request.host)
        if is_marketing_host(host):
            return redirect(url_for('marketing.entrar'))
        if host == 'localhost':
            return redirect(url_for('superadmin.dashboard'))
        flash(translate('Por favor, accede desde la URL específica de tu empresa.'), 'warning')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        if current_user.is_authenticated:
            logout_user()
            session.pop('superadmin_impersonation', None)
            session.pop('impersonator_user_id', None)
            session.pop('impersonated_user_id', None)

        identifier = (request.form.get('login') or request.form.get('email') or '').strip()
        secret = request.form.get('secret') or request.form.get('password') or ''
        remember = True if request.form.get('remember') == 'on' else False

        from app.services.auth_login_service import (
            identifier_looks_like_email,
            login_with_dni_pin,
            login_with_email_password,
        )
        from app.services.pin_auth_service import PinAuthError

        user = None
        login_error = None

        try:
            if identifier_looks_like_email(identifier):
                user = login_with_email_password(identifier, secret)
            else:
                user = login_with_dni_pin(identifier, secret)
        except PinAuthError as exc:
            login_error = str(exc)
        except ValueError as exc:
            login_error = str(exc)

        if user and not login_error:
            if not _puede_login_web(user):
                from app.utils import register_log
                register_log(
                    user_id=user.id,
                    category='accesos',
                    action='Acceso denegado',
                    detail=(
                        f"Intento de login con rol sin acceso web ({user.role}). "
                        f"IP: {request.remote_addr or 'Desconocida'}"
                    ),
                )
                _commit_access_log()
                flash(
                    translate(
                        'Tu perfil no tiene acceso a la aplicación. Contacta con administración.'
                    ),
                    'warning',
                )
                return render_template('login.html', **_login_page_context())

            if not user.is_active:
                flash(
                    translate(
                        'Tu cuenta aún no está activa. Espera la aprobación de RRHH.'
                    ),
                    'warning',
                )
                return render_template('login.html', **_login_page_context())

            from app.services.pin_auth_service import debe_cambiar_pin
            source = 'pin' if not identifier_looks_like_email(identifier) else 'local'
            if source == 'pin' and debe_cambiar_pin(user):
                from app.utils import register_log
                user.auth_source_last = source
                db.session.add(user)
                login_user(user, remember=remember)
                session['tenant_id'] = g.current_tenant.id
                register_log(
                    user_id=user.id,
                    category='accesos',
                    action='Inicio de Sesión',
                    detail=(
                        f"Login exitoso vía {source} (cambio de PIN obligatorio) "
                        f"desde IP: {request.remote_addr or 'Desconocida'}"
                    ),
                )
                db.session.commit()
                flash(translate('Debes cambiar el PIN antes de continuar.'), 'warning')
                return redirect(url_for('empleado.cambiar_pin', obligatorio=1))

            return _complete_login(user, remember, source=source)

        # Email no encontrado localmente → fallback Odoo (Soltec / tenants con auth externo)
        email = identifier.lower() if identifier_looks_like_email(identifier) else ''
        user = User.query.filter_by(email=email).first() if email else None
        external_result = None
        if (
            user
            and secret
            and identifier_looks_like_email(identifier)
            and external_auth_enabled_for_tenant()
            and external_auth_allowed_for_user(user)
            and can_attempt_external_auth(email, request.remote_addr, g.current_tenant.id)
        ):
            external_result = verify_external_password(
                email,
                secret,
                tenant_id=g.current_tenant.id,
            )
            if external_result.decision != 'skipped':
                log_external_auth_result(user, external_result, request.remote_addr)

            if external_result.is_valid:
                user.password_hash = generate_password_hash(secret)
                user.auth_source_last = 'odoo'
                user.odoo_verified_at = _utc_now()
                db.session.add(user)
                db.session.commit()

                if not _puede_login_web(user):
                    from app.utils import register_log
                    register_log(
                        user_id=user.id,
                        category='accesos',
                        action='Acceso denegado',
                        detail=(
                            f"Intento de login vía Odoo con rol sin acceso web ({user.role}). "
                            f"IP: {request.remote_addr or 'Desconocida'}"
                        ),
                    )
                    _commit_access_log()
                    flash(
                        translate(
                            'Tu perfil no tiene acceso a la aplicación. Contacta con administración.'
                        ),
                        'warning',
                    )
                    return render_template('login.html', **_login_page_context())

                if not user.is_active:
                    flash(
                        translate(
                            'Tu cuenta aún no está activa. Espera la aprobación de RRHH.'
                        ),
                        'warning',
                    )
                    return render_template('login.html', **_login_page_context())

                return _complete_login(
                    user,
                    remember,
                    source='odoo',
                    success_message=translate('Inicio de sesión exitoso'),
                )

        if user:
            from app.utils import register_log
            if external_result and external_result.is_unavailable:
                detail = (
                    f"Credenciales locales incorrectas. Fallback Odoo no disponible "
                    f"({external_result.reason}). IP: {request.remote_addr or 'Desconocida'}"
                )
            elif external_result and external_result.is_invalid:
                detail = (
                    f"Credenciales locales incorrectas. Fallback Odoo rechazado. "
                    f"IP: {request.remote_addr or 'Desconocida'}"
                )
            else:
                detail = f"Credenciales incorrectas. IP: {request.remote_addr or 'Desconocida'}"
            register_log(
                user_id=user.id,
                category='accesos',
                action='Intento fallido de login',
                detail=detail,
            )
            _commit_access_log()
        flash(login_error or translate('Credenciales inválidas'), 'danger')

    return render_template('login.html', **_login_page_context())


@auth_bp.route('/sso/soltec', methods=['GET'])
@limiter.limit('20 per minute; 100 per hour')
def sso_soltec():
    from app.utils import register_log

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash(translate('Accede desde la URL de tu empresa.'), 'warning')
        return redirect(url_for('main.dashboard'))

    token = request.args.get('t') or request.args.get('token') or ''
    try:
        claims = verify_soltec_sso_token(token)
    except SoltecSsoError as exc:
        current_app.logger.warning(
            'SSO Soltec rechazado: %s (param_t=%s)',
            exc,
            'si' if (token or '').strip() else 'no',
        )
        register_log(
            user_id=None,
            category='accesos',
            action='SSO Soltec rechazado',
            detail=f"{str(exc)} IP: {request.remote_addr or 'Desconocida'}",
        )
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(translate(str(exc)), 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter(db.func.lower(User.email) == claims['email'].lower()).first()
    if not user:
        current_app.logger.warning(
            'SSO Soltec sin usuario: %s', claims['email']
        )
        register_log(
            user_id=None,
            category='accesos',
            action='SSO Soltec sin usuario',
            detail=(
                f"Email {claims['email']} no existe en Planner. "
                f"IP: {request.remote_addr or 'Desconocida'}"
            ),
        )
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(
            translate('Este correo no tiene usuario en Planner.'),
            'danger',
        )
        return redirect(url_for('auth.login'))

    if not _puede_login_web(user):
        register_log(
            user_id=user.id,
            category='accesos',
            action='SSO Soltec denegado',
            detail=(
                f"Rol sin acceso web ({user.role}). "
                f"IP: {request.remote_addr or 'Desconocida'}"
            ),
        )
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(
            translate(
                'Tu perfil no tiene acceso a la aplicación. Contacta con administración.'
            ),
            'warning',
        )
        return redirect(url_for('auth.login'))

    if not user.is_active:
        flash(
            translate(
                'Tu cuenta aún no está activa. Espera la aprobación de RRHH.'
            ),
            'warning',
        )
        return redirect(url_for('auth.login'))

    if current_user.is_authenticated:
        logout_user()

    return _complete_login(
        user,
        remember=True,
        source='sso_soltec',
        success_message=translate('Inicio de sesión exitoso'),
    )


@auth_bp.route('/sso/portal', methods=['GET'])
@login_required
@limiter.limit('20 per minute; 100 per hour')
def sso_portal():
    """Planner → Portal Soltec (JWT saliente). Solo tenant soltec + SSO ON."""
    from app.utils import register_log
    from app.services.permission_service import user_can

    if not user_can(current_user, 'soltec_portal', 'r'):
        flash(translate('No tienes permiso para abrir el Portal Soltec.'), 'danger')
        return redirect(url_for('main.dashboard'))

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash(translate('Accede desde la URL de tu empresa.'), 'warning')
        return redirect(url_for('main.dashboard'))

    if not _puede_login_web(current_user):
        flash(
            translate(
                'Tu perfil no tiene acceso a la aplicación. Contacta con administración.'
            ),
            'warning',
        )
        return redirect(url_for('main.dashboard'))

    try:
        destino = build_portal_sso_redirect_url(current_user.email)
    except SoltecSsoError as exc:
        current_app.logger.warning('SSO Portal denegado: %s', exc)
        register_log(
            user_id=current_user.id,
            category='accesos',
            action='SSO Portal denegado',
            detail=f"{str(exc)} IP: {request.remote_addr or 'Desconocida'}",
        )
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(translate(str(exc)), 'danger')
        return redirect(url_for('main.dashboard'))

    register_log(
        user_id=current_user.id,
        category='accesos',
        action='SSO Portal salida',
        detail=(
            f"Redirect a Portal para {current_user.email}. "
            f"IP: {request.remote_addr or 'Desconocida'}"
        ),
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(destino)


@auth_bp.route('/tour-volver-admin')
def tour_volver_admin():
    """Tras probar el fichaje en la guía: restaura la sesión del admin."""
    from flask import session
    from app.models import User, ROLE_ADMIN

    admin_id = session.pop('tour_admin_user_id', None)
    next_url = (request.args.get('next') or '').strip()
    logout_user()
    if admin_id:
        admin = User.query.get(admin_id)
        if admin and admin.role == ROLE_ADMIN and not admin.is_deleted:
            login_user(admin, remember=True)
            if getattr(g, 'current_tenant', None):
                session['tenant_id'] = g.current_tenant.id
            if next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for('admin.obras_detailed', tour='fichaje_done'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/stop-impersonate', methods=['POST'])
@login_required
def stop_impersonate():
    """Volver a la cuenta del administrador tras impersonar."""
    from app.services.impersonation_service import detener_impersonacion, impersonacion_activa
    from app.utils import register_log

    if not impersonacion_activa():
        flash(translate('No hay una sesión suplantada activa.'), 'info')
        return redirect(url_for('admin.panel'))

    suplantado = current_user
    admin = detener_impersonacion()
    if not admin:
        flash(translate('No se pudo restaurar la sesión del administrador.'), 'danger')
        return redirect(url_for('auth.login'))

    register_log(
        user_id=admin.id,
        category='accesos',
        action='Impersonación fin',
        detail=f"Volvió desde {suplantado.name} {suplantado.lastname} ({suplantado.email}).",
        target_user_id=suplantado.id,
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    flash(translate('Has vuelto a tu cuenta de administrador.'), 'success')
    return redirect(url_for('admin.personal'))


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    session.pop('superadmin_impersonation', None)
    session.pop('impersonator_user_id', None)
    session.pop('impersonated_user_id', None)
    # logout_user() deja session['_remember'] = 'clear' para que Flask-Login
    # borre remember_token en after_request. No hay que hacer pop de esa clave.
    flash(translate('Sesión cerrada'), 'info')
    from flask import make_response
    from app.services.impersonation_service import clear_remember_cookie
    resp = make_response(redirect(url_for('auth.login')))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return clear_remember_cookie(resp)


@auth_bp.route('/recuperar', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour', methods=['POST'])
def recuperar():
    """Pide el correo y, si existe, envía el enlace de restablecimiento."""
    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash(translate('Accede desde la URL de tu empresa para recuperar la contraseña.'), 'info')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        from app.services.password_reset_service import PasswordResetError, solicitar_reset

        email = request.form.get('email')
        try:
            solicitar_reset(
                email,
                g.current_tenant,
                reset_url_builder=lambda token: url_for(
                    'auth.recuperar_token', token=token, _external=True
                ),
            )
        except PasswordResetError as exc:
            flash(str(exc), 'danger')
            return render_template(
                'auth_recuperar.html',
                tenant_name=g.current_tenant.nombre,
            )
        # Mensaje único: no delata si el correo existe.
        flash(
            translate(
                'Si el correo está registrado, recibirás un enlace para restablecer la contraseña.'
            ),
            'info',
        )
        return redirect(url_for('auth.login'))

    return render_template(
        'auth_recuperar.html',
        tenant_name=g.current_tenant.nombre,
    )


@auth_bp.route('/recuperar/<token>', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 30 per hour', methods=['POST'])
def recuperar_token(token):
    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash(translate('Accede desde la URL de tu empresa.'), 'warning')
        return redirect(url_for('main.dashboard'))

    from app.services.password_reset_service import (
        PasswordResetError,
        aplicar_nueva_password,
        leer_token,
    )

    try:
        leer_token(token, g.current_tenant)
    except PasswordResetError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('auth.recuperar'))

    if request.method == 'POST':
        try:
            aplicar_nueva_password(
                token,
                g.current_tenant,
                request.form.get('password'),
                request.form.get('password2'),
            )
            flash(translate('Contraseña actualizada. Ya puedes iniciar sesión.'), 'success')
            return redirect(url_for('auth.login'))
        except PasswordResetError as exc:
            flash(str(exc), 'danger')

    return render_template(
        'auth_recuperar_nueva.html',
        tenant_name=g.current_tenant.nombre,
        token=token,
    )


# Aquí vivía /auth/register, un alta pública en la que cualquiera que supiese el
# código de una subcontrata podía crearse una cuenta en el tenant de esa empresa.
# Llevaba roto desde que se borró su plantilla y nadie lo echó de menos: las
# personas entran por la sincronización del ERP o las da de alta administración.
# El alta de empresa (crear tenant) está en signaplan.com/alta.


@auth_bp.route('/impersonate')
@limiter.limit('10 per minute; 30 per hour')
def impersonate():
    """Entrada firmada desde /superadmin para gestionar un tenant como su admin."""
    from app.services.superadmin_ops_service import leer_token_impersonacion

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash(translate('Accede desde la URL de la empresa.'), 'warning')
        return redirect(url_for('main.dashboard'))

    token = request.args.get('t') or ''
    try:
        user_id = leer_token_impersonacion(token, g.current_tenant)
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(id=user_id, is_deleted=False).first()
    if user is None or not user.is_active:
        flash(translate('No se ha podido abrir la sesión de soporte.'), 'danger')
        return redirect(url_for('auth.login'))

    if current_user.is_authenticated:
        logout_user()

    login_user(user, remember=False)
    session['tenant_id'] = g.current_tenant.id
    session['superadmin_impersonation'] = True
    flash(
        translate(
            'Has entrado como {name} (soporte SignaPlan).',
            name=f'{user.name} {user.lastname}',
        ),
        'warning',
    )
    destino = _destino_por_rol(user)
    return redirect(destino or url_for('admin.panel'))
