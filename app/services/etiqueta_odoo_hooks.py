"""Hooks de sincronización de etiquetas hacia Odoo (APARCADOS).

Diseño acordado (aún sin implementar escritura):
- Dirección: solo SignaPlan → Odoo.
- Borrar/absorber aquí → borrar/mover también en Odoo cuando exista el campo.
- Cambios hechos en Odoo no se importan a SignaPlan.
- El campo destino en Odoo todavía no existe; estas funciones son no-op
  a propósito para no escribir en ningún sitio.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


def notify_etiqueta_created(etiqueta) -> None:
    _logger.debug('etiqueta_odoo: create skipped id=%s', getattr(etiqueta, 'id', None))


def notify_etiqueta_renamed(etiqueta, *, old_name: str) -> None:
    _logger.debug(
        'etiqueta_odoo: rename skipped id=%s %s→%s',
        getattr(etiqueta, 'id', None), old_name, getattr(etiqueta, 'nombre', None),
    )


def notify_etiqueta_deleted(etiqueta) -> None:
    _logger.debug('etiqueta_odoo: delete skipped id=%s', getattr(etiqueta, 'id', None))


def notify_etiqueta_absorbed(source, target) -> None:
    _logger.debug(
        'etiqueta_odoo: absorb skipped %s→%s',
        getattr(source, 'id', None), getattr(target, 'id', None),
    )
