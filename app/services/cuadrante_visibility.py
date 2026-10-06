"""Quién entra en el cuadrante: el interruptor, no el rol."""
from __future__ import annotations

from app.models import ROLE_ADMIN_SUBCONTRATA, ROLE_OPERARIO, User


def query_cuadrante():
    return User.query.filter(
        User.visible_en_cuadrante.is_(True),
        User.active.is_(True),
        User.is_deleted.is_(False),
        User.hiring_state.is_(None),
    )


def ids_cuadrante():
    return [uid for (uid,) in query_cuadrante().with_entities(User.id).all()]


def es_rol_de_campo(role: str | None) -> bool:
    return role in (ROLE_OPERARIO, ROLE_ADMIN_SUBCONTRATA)
