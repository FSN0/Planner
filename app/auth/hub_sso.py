from datetime import date

from flask import Blueprint, flash, g, redirect, request, session, url_for
from flask_login import current_user, login_user, logout_user

from app import csrf
from app.auth.routes import LOGIN_BLOCKED_ROLES
from app.services.hub_sso_service import (
    clear_hub_authentik_uid,
    clear_hub_sso_skip_auto,
    find_user_for_hub_identity,
    get_authentik_identity,
    get_stored_hub_authentik_uid,
    has_authentik_proxy_cookie,
    hub_identity_lookup_keys,
    hub_proxy_sign_out_path,
    hub_sso_enabled_for_tenant,
    is_hub_portal_referer,
    should_skip_hub_sso_auto,
    store_hub_authentik_uid,
)

hub_sso_bp = Blueprint("hub_sso", __name__)

# Authentik devuelve a / tras el primer OAuth; reenviar a /sso/hub si ya hay cookie proxy.
_HUB_SSO_ENTRY_PATHS = frozenset({"/", "/auth/login"})


def _login_local():
    return redirect(url_for("auth.login", local=1))


def _redirect_hub_proxy_refresh():
    """Renueva cookie proxy Authentik (impersonacion admin en el Hub)."""
    return_url = url_for("hub_sso.sso_hub", reauth=1, _external=True)
    return redirect(hub_proxy_sign_out_path(return_url))


def _should_refresh_hub_proxy() -> bool:
    if request.args.get("reauth"):
        return False
    if not is_hub_portal_referer():
        return False
    return has_authentik_proxy_cookie()


def _auto_redirect_hub_sso_entry():
    if request.method != "GET":
        return None
    if request.path == "/sso/hub" or request.path.startswith("/outpost.goauthentik.io"):
        return None
    if request.args.get("local"):
        return None
    if should_skip_hub_sso_auto():
        return None
    if current_user.is_authenticated:
        return None
    tenant = getattr(g, "current_tenant", None)
    if not tenant or not hub_sso_enabled_for_tenant(tenant):
        return None
    if not has_authentik_proxy_cookie():
        return None
    path = request.path.rstrip("/") or "/"
    if path not in _HUB_SSO_ENTRY_PATHS:
        return None
    return redirect(url_for("hub_sso.sso_hub"))


def register_hub_sso_auto_redirect(app):
    @app.before_request
    def _hub_sso_auto_redirect_after_tenant():
        return _auto_redirect_hub_sso_entry()


def _redirect_authenticated_user():
    if current_user.role == "admin":
        return redirect(url_for("admin.panel"))
    if current_user.role == "jefe_obra":
        return redirect(url_for("jefe.obras_detailed", selected_date=date.today()))
    logout_user()
    flash("Tu perfil no tiene acceso a la aplicacion.", "warning")
    return _login_local()


def _redirect_after_login(user):
    if user.role == "admin":
        return redirect(url_for("admin.panel"))
    if user.role == "jefe_obra":
        return redirect(url_for("jefe.obras_detailed", selected_date=date.today()))
    logout_user()
    flash("Tu perfil no tiene acceso a la aplicacion.", "warning")
    return _login_local()


@hub_sso_bp.route("/sso/hub")
def sso_hub():
    clear_hub_sso_skip_auto()
    tenant = getattr(g, "current_tenant", None)
    if not tenant or not hub_sso_enabled_for_tenant(tenant):
        flash("El inicio de sesion con Hub no esta disponible para esta organizacion.", "warning")
        return _login_local()

    if _should_refresh_hub_proxy():
        logout_user()
        clear_hub_authentik_uid()
        return _redirect_hub_proxy_refresh()

    ident = get_authentik_identity()
    lookup_keys = hub_identity_lookup_keys(ident)
    header_uid = (ident.get("uid") or "").strip()
    stored_uid = get_stored_hub_authentik_uid()

    if not lookup_keys:
        flash(
            "No se detecto sesion del Hub. Entra primero en el Hub de aplicaciones "
            "o usa email y contrasena.",
            "warning",
        )
        return _login_local()

    user, matched_key = find_user_for_hub_identity(ident)
    if not user:
        flash(
            "Usuario no registrado en SignaPlan. "
            f"El Hub identifico «{lookup_keys[0]}»; usa el mismo email en SignaPlan "
            "o entra con email y contrasena.",
            "warning",
        )
        return _login_local()
    email = matched_key

    if current_user.is_authenticated:
        same_user = current_user.id == user.id
        same_hub_uid = not header_uid or not stored_uid or header_uid == stored_uid
        if same_user and same_hub_uid:
            store_hub_authentik_uid(header_uid)
            return _redirect_authenticated_user()
        logout_user()

    if user.role in LOGIN_BLOCKED_ROLES:
        from app.utils import register_log

        register_log(
            user_id=user.id,
            category="accesos",
            action="Acceso denegado",
            detail=(
                f"Intento de login Hub con rol sin acceso ({user.role}). "
                f"IP: {request.remote_addr or 'Desconocida'}"
            ),
        )
        flash(
            "Tu perfil no tiene acceso a la aplicacion. Contacta con administracion.",
            "warning",
        )
        return _login_local()

    if not user.is_active:
        flash("Tu cuenta aun no esta activa. Espera la aprobacion de RRHH.", "warning")
        return _login_local()

    login_user(user, remember=True)
    session["tenant_id"] = tenant.id
    store_hub_authentik_uid(header_uid)
    from app.utils import register_log

    register_log(
        user_id=user.id,
        category="accesos",
        action="Inicio de Sesion",
        detail=(
            f"Login Hub exitoso ({email}, uid={ident.get('uid') or 'n/a'}). "
            f"IP: {request.remote_addr or 'Desconocida'}"
        ),
    )
    flash("Inicio de sesion exitoso", "success")
    return _redirect_after_login(user)


csrf.exempt(sso_hub)
