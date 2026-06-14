"""Integracion SSO con Soltec Hub (Authentik Forward Auth via Caddy)."""
from __future__ import annotations

from flask import current_app, request


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


def _parse_hub_groups(raw: str) -> set[str]:
    if not raw:
        return set()
    return {group.strip() for group in raw.split("|") if group.strip()}


def get_authentik_identity() -> dict[str, str | set[str]]:
    return {
        "email": (request.headers.get("X-authentik-email") or "").strip(),
        "username": (request.headers.get("X-authentik-username") or "").strip(),
        "name": (request.headers.get("X-authentik-name") or "").strip(),
        "uid": (request.headers.get("X-authentik-uid") or "").strip(),
        "groups": _parse_hub_groups(request.headers.get("X-authentik-groups") or ""),
    }
