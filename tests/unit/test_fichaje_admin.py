"""Altas y correcciones admin de marcas (ledger append-only)."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.models import EVENTO_ENTRADA, EVENTO_SALIDA
from app.services.fichaje_admin_service import (
    FichajeAdminError,
    corregir_marca,
    registrar_marca_manual,
)


def test_registrar_marca_exige_motivo():
    with pytest.raises(FichajeAdminError):
        registrar_marca_manual(
            user_id=1,
            tipo=EVENTO_ENTRADA,
            ocurrido_en_local='2026-08-06 08:00',
            motivo='x',
            autor_id=2,
        )


def test_registrar_marca_ok_flujo():
    trabajador = SimpleNamespace(id=7, role='operario')
    evento = SimpleNamespace(id=99, secuencia=3, user_id=7, fecha_laboral=None, motivo='ok')

    with patch('app.services.fichaje_admin_service._asegurar_trabajador', return_value=trabajador), \
         patch('app.services.fichaje_admin_service._asegurar_obra', return_value=None), \
         patch('app.services.fichaje_admin_service._parse_local_datetime', return_value=datetime(2026, 8, 6, 6, 0)), \
         patch('app.services.fichaje_admin_service.utc_to_local', return_value=datetime(2026, 8, 6, 8, 0)), \
         patch('app.services.fichaje_admin_service.registrar_evento', return_value=evento) as reg, \
         patch('app.services.fichaje_admin_service.proyectar_dia') as proy, \
         patch('app.services.fichaje_admin_service.db') as mock_db:
        mock_db.session = MagicMock()
        out = registrar_marca_manual(
            user_id=7,
            tipo=EVENTO_ENTRADA,
            ocurrido_en_local='2026-08-06 08:00',
            motivo='Olvido de fichaje en obra',
            autor_id=2,
            obra_id=None,
        )
        assert out is evento
        assert reg.called
        assert proy.called


def test_corregir_marca_anula_y_crea():
    original = SimpleNamespace(
        id=10,
        tipo=EVENTO_SALIDA,
        user_id=7,
        obra_id=3,
        ocurrido_en=datetime(2026, 8, 6, 15, 0),
        fecha_laboral=datetime(2026, 8, 6).date(),
    )
    nuevo = SimpleNamespace(id=11, secuencia=5, user_id=7, fecha_laboral=original.fecha_laboral, motivo='corr')

    with patch('app.services.fichaje_admin_service.FichajeEvento') as FE, \
         patch('app.services.fichaje_admin_service.esta_anulado', return_value=False), \
         patch('app.services.fichaje_admin_service._asegurar_obra', return_value=None), \
         patch('app.services.fichaje_admin_service.anular_evento') as anul, \
         patch('app.services.fichaje_admin_service.registrar_evento', return_value=nuevo) as reg, \
         patch('app.services.fichaje_admin_service.proyectar_dia'), \
         patch('app.services.fichaje_admin_service.db') as mock_db:
        mock_db.session = MagicMock()
        FE.query.filter_by.return_value.first.return_value = original
        out = corregir_marca(
            evento_id=10,
            motivo='Hora incorrecta consultada con el trabajador',
            autor_id=2,
            nuevo_ocurrido_en_local='2026-08-06 16:00',
        )
        assert out is nuevo
        assert anul.called
        assert reg.called
