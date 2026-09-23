"""Valoraciones 0–5: actitud y conocimiento."""
from __future__ import annotations

from typing import Any, Optional, Tuple


SCORE_MIN = 0
SCORE_MAX = 5


def parse_dimension(raw: Any) -> Optional[int]:
    """Parsea una dimensión opcional (None / '' → None). Valida rango 0–5."""
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError('La puntuación debe ser un número entero') from exc
    if value < SCORE_MIN or value > SCORE_MAX:
        raise ValueError(f'La puntuación debe estar entre {SCORE_MIN} y {SCORE_MAX}')
    return value


def parse_reason(raw: Any) -> str:
    """Motivo obligatorio (texto no vacío)."""
    if raw is None:
        raise ValueError('El motivo es obligatorio')
    text = str(raw).strip()
    if not text:
        raise ValueError('El motivo es obligatorio')
    return text


def parse_rating_payload(data: dict) -> Tuple[Optional[int], Optional[int], float, str]:
    """
    Extrae actitud/conocimiento/motivo del JSON.
    Al menos una dimensión debe venir informada; el motivo es obligatorio.
    Devuelve (actitud, conocimiento, media, motivo).
    """
    data = data or {}
    actitud = parse_dimension(data.get('actitud'))
    conocimiento = parse_dimension(data.get('conocimiento'))
    if actitud is None and conocimiento is None:
        raise ValueError('Indica al menos actitud o conocimiento')
    motivo = parse_reason(data.get('reason'))
    return actitud, conocimiento, composite_score(actitud, conocimiento), motivo


def composite_score(actitud: Optional[int], conocimiento: Optional[int]) -> float:
    """Media de las dimensiones presentes (1 decimal)."""
    vals = [v for v in (actitud, conocimiento) if v is not None]
    if not vals:
        raise ValueError('Indica al menos actitud o conocimiento')
    return round(sum(vals) / len(vals), 1)


def rating_is_v2(rating) -> bool:
    """True si la valoración usa el esquema actitud/conocimiento."""
    return getattr(rating, 'actitud', None) is not None or getattr(rating, 'conocimiento', None) is not None


def rating_display_score(rating) -> float:
    """Nota a mostrar: media de dimensiones (v2) o score legacy."""
    if rating_is_v2(rating):
        return composite_score(rating.actitud, rating.conocimiento)
    return float(rating.score) if rating.score is not None else 0.0


def reputation_tone(score: Optional[float]) -> str:
    """Tono visual para paneles (escala 0–5)."""
    if score is None:
        return 'slate'
    if score >= 4.0:
        return 'green'
    if score <= 2.0:
        return 'red'
    return 'amber'


def ratings_visible_to_viewer(ratings, viewer) -> list:
    """Filtra valoraciones v2 activas visibles según alcance de valoraciones."""
    from app.services.panel_scope_service import rating_visible_to_user, valoraciones_visible_author_ids

    if not ratings:
        return []
    allowed = valoraciones_visible_author_ids(viewer)
    out = []
    for r in ratings:
        if not getattr(r, 'is_active', True):
            continue
        if not rating_is_v2(r):
            continue
        if allowed is not None and not rating_visible_to_user(viewer, r):
            continue
        out.append(r)
    return out


def reputation_for_viewer(worker, viewer) -> tuple[float, int]:
    """(media, count) de valoraciones v2 visibles para el viewer."""
    if worker is None or not hasattr(worker, 'ratings_received'):
        return 0.0, 0
    visible = ratings_visible_to_viewer(worker.ratings_received, viewer)
    if not visible:
        return 0.0, 0
    total = sum(rating_display_score(r) for r in visible)
    return round(total / len(visible), 1), len(visible)


def apply_valoraciones_author_filter(query, viewer):
    """Aplica filtro de autor a un query de Rating según alcance del viewer."""
    from app.models import Rating
    from app.services.panel_scope_service import valoraciones_visible_author_ids

    allowed = valoraciones_visible_author_ids(viewer)
    if allowed is None:
        return query
    if not allowed:
        return query.filter(Rating.id.is_(None))
    return query.filter(Rating.created_by_id.in_(list(allowed)))
