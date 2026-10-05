"""Encola el envío del informe PDF al autor (sin bloquear HTTP ni el job de audio)."""
from __future__ import annotations

from flask import current_app, g


def enqueue_informe_reunion_autor(nota_id: int) -> None:
    schema = getattr(getattr(g, 'current_tenant', None), 'schema_name', None)
    if not schema:
        current_app.logger.warning(
            'Informe reunión: sin tenant en contexto (nota_id=%s)', nota_id,
        )
        return
    try:
        from app.celery_worker import send_nota_reunion_informe_task
        send_nota_reunion_informe_task.delay(schema, nota_id)
    except Exception as exc:
        current_app.logger.warning(
            'Informe reunión: no se pudo encolar (nota_id=%s): %s', nota_id, exc,
        )
