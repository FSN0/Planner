"""Integracion SSO con Soltec Hub (Authentik Forward Auth via Caddy)."""
from __future__ import annotations

from flask import current_app, request, session
from sqlalchemy import func

HUB_SSO_SKIP_AUTO_KEY = "hub_sso_skip_auto"
HUB_SSO_UID_KEY = "hub_authentik_uid"


def _parse_csv_set(value: str | None, default: str) -> set[str]:
    raw = (value if value is not None else default) or ""
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def hub_sso_enabled_for_tenant(tenant) -> bool:
    if not current_app.config.get("HUB_SSO_ENABLED"):
        return False
    if not tenant:
        return False
    allowed = _parse_csv_set(current_app.config.get("HUB_SSO_TENANTS"), "soltec")
    subdominio = (getattr(tenant, "subdominio", None) or "").lower().strip()
    if subdominio and subdominio in allowed:
        return True
    custom_domain = (getattr(tenant, "custom_domain", None) or "").lower().strip()
    if custom_domain and custom_domain in allowed:
        return True
    return False


def hub_url() -> str:
    url = (current_app.config.get("HUB_URL") or "https://apps.soltecgrupo.es").strip()
    return url.rstrip("/")


def mark_hub_sso_skip_auto() -> None:
    """Evita re-login Hub tras cerrar sesion en SignaPlan."""
    session[HUB_SSO_SKIP_AUTO_KEY] = True


def should_skip_hub_sso_auto() -> bool:
    return bool(session.get(HUB_SSO_SKIP_AUTO_KEY))


def clear_hub_sso_skip_auto() -> None:
    session.pop(HUB_SSO_SKIP_AUTO_KEY, None)


def store_hub_authentik_uid(uid: str | None) -> None:
    value = (uid or "").strip()
    if value:
        session[HUB_SSO_UID_KEY] = value
    else:
        session.pop(HUB_SSO_UID_KEY, None)


def get_stored_hub_authentik_uid() -> str:
    return (session.get(HUB_SSO_UID_KEY) or "").strip()


def clear_hub_authentik_uid() -> None:
    session.pop(HUB_SSO_UID_KEY, None)


def is_hub_portal_referer() -> bool:
    """True si la peticion viene del portal Authentik (tile SignaPlan)."""
    referer = (request.referrer or "").strip()
    if not referer:
        return False
    hub = hub_url().lower()
    return hub in referer.lower() or "apps.soltecgrupo.es" in referer.lower()


def hub_proxy_sign_out_path(return_url: str) -> str:
    from urllib.parse import quote

    return f"/outpost.goauthentik.io/sign_out?rd={quote(return_url, safe='')}"


def _parse_hub_groups(raw: str) -> set[str]:
    if not raw:
        return set()
    return {group.strip() for group in raw.split("|") if group.strip()}


def has_authentik_proxy_cookie() -> bool:
    """Presente tras el primer OAuth del outpost Authentik en este dominio."""
    return any(name.startswith("authentik_proxy_") for name in request.cookies)


def get_authentik_identity() -> dict[str, str | set[str]]:
    return {
        "email": (request.headers.get("X-authentik-email") or "").strip(),
        "username": (request.headers.get("X-authentik-username") or "").strip(),
        "name": (request.headers.get("X-authentik-name") or "").strip(),
        "uid": (request.headers.get("X-authentik-uid") or "").strip(),
        "groups": _parse_hub_groups(request.headers.get("X-authentik-groups") or ""),
    }


def hub_identity_lookup_keys(ident: dict[str, str | set[str]]) -> list[str]:
    """Emails/login a probar: username Hub suele coincidir con SignaPlan, email Odoo a veces no."""
    keys: list[str] = []
    seen: set[str] = set()
    for raw in (ident.get("username"), ident.get("email")):
        value = (raw or "").strip()
        if not value:
            continue
        norm = value.lower()
        if norm in seen:
            continue
        seen.add(norm)
        keys.append(value)
    return keys


def find_user_for_hub_identity(ident: dict[str, str | set[str]]):
    from app.models import User

    for key in hub_identity_lookup_keys(ident):
        user = User.query.filter(func.lower(User.email) == key.lower()).first()
        if user:
            return user, key
    return None, None
