"""Heurísticas anti-spam para el formulario público /contacto."""

from __future__ import annotations

import re
import time
from typing import Optional

# Dominios casi nunca legítimos en un contacto B2B de obra.
_SPAM_HOSTS = (
    'telegra.ph',
    'telegraph.com',
    't.me/',
    'bit.ly/',
    'tinyurl.com',
    'goo.gl/',
    'ow.ly/',
    'rebrand.ly',
    'cutt.ly',
    'rb.gy',
    'is.gd',
    'buff.ly',
)

_URL_RE = re.compile(r'https?://[^\s<>"\']+', re.I)
_MONEY_HOOK_RE = re.compile(
    r'(\$\s*[\d,.]+|\b\d[\d,.]*\s*(usd|eur|€)\b).{0,40}'
    r'(earn|grab|profit|income|month|today|crypto|bitcoin|investment)',
    re.I | re.S,
)
_EARN_HOOK_RE = re.compile(
    r'\b(earn|make|grab|get)\b.{0,40}\b(money|cash|profit|\$|million|usd)\b',
    re.I | re.S,
)
_PROMO_RE = re.compile(
    r'\b(rolls[- ]?royce|lamborghini|ferrari|crypto|forex|nft|'
    r'work from home|passive income|double your|guaranteed profit)\b',
    re.I,
)

# Tiempo mínimo entre render del form y POST (bots suelen ser instantáneos).
_MIN_FORM_SECONDS = 2.5
_MAX_FORM_SECONDS = 60 * 60 * 6  # 6h: tokens viejos = sospechosos pero no bloquear por reloj mal


def looks_like_spam(
    *,
    nombre: str = '',
    email: str = '',
    empresa: str = '',
    mensaje: str = '',
    form_ts: Optional[str] = None,
) -> bool:
    """True si el envío encaja con spam típico de telegra.ph / crypto / ganancia fácil."""
    blob = f'{nombre}\n{email}\n{empresa}\n{mensaje}'.lower()

    if any(host in blob for host in _SPAM_HOSTS):
        return True

    urls = _URL_RE.findall(mensaje or '')
    if len(urls) >= 2:
        return True
    if len(urls) == 1 and (_MONEY_HOOK_RE.search(mensaje) or _EARN_HOOK_RE.search(mensaje) or _PROMO_RE.search(mensaje)):
        return True
    if _MONEY_HOOK_RE.search(mensaje) or (_EARN_HOOK_RE.search(mensaje) and _PROMO_RE.search(mensaje)):
        return True
    if _PROMO_RE.search(mensaje) and urls:
        return True

    # Nombre tipo "EdwardRew" / "JohnSmith99" sin espacios + mensaje con URL
    nombre_l = (nombre or '').strip()
    if urls and nombre_l and ' ' not in nombre_l and re.search(r'[A-Z].*[A-Z]', nombre_l):
        return True

    if form_ts is not None and _timing_is_spam(form_ts):
        return True

    return False


def _timing_is_spam(form_ts: str) -> bool:
    try:
        started = float(form_ts)
    except (TypeError, ValueError):
        return True
    age = time.time() - started
    if age < _MIN_FORM_SECONDS:
        return True
    if age > _MAX_FORM_SECONDS or age < 0:
        return True
    return False


def new_form_ts() -> str:
    return str(time.time())
