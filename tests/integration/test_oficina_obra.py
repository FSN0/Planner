# tests/integration/test_oficina_obra.py
#
# Obra «Oficina» opcional: se crea al activar la config y aparece al fichar.

from sqlalchemy import text

from app.models import Obra
from app.services.oficina_obra_service import (
    CODIGO_OFICINA,
    NOMBRE_OFICINA,
    buscar_obra_oficina,
    sincronizar_obra_oficina,
)
from app.services.fichaje_operario_service import obras_seleccionables
import pytest


@pytest.fixture
def oficina_ctx(session, tenant_soltec, company_internal, user_operario, obra_activa):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    yield session


class TestOficinaObra:

    def test_activar_crea_la_obra(self, oficina_ctx):
        obra = sincronizar_obra_oficina(True)
        oficina_ctx.commit()

        assert obra is not None
        assert obra.codigo == CODIGO_OFICINA
        assert obra.nombre == NOMBRE_OFICINA
        assert obra.is_deleted is False
        assert buscar_obra_oficina() is not None

    def test_desactivar_archiva_la_obra(self, oficina_ctx):
        sincronizar_obra_oficina(True)
        oficina_ctx.commit()
        sincronizar_obra_oficina(False)
        oficina_ctx.commit()

        assert buscar_obra_oficina() is None
        archivada = Obra.query.filter_by(codigo=CODIGO_OFICINA).first()
        assert archivada is not None
        assert archivada.is_deleted is True

    def test_aparece_al_fichar_cuando_esta_activa(
        self, oficina_ctx, user_operario, obra_activa
    ):
        sincronizar_obra_oficina(True)
        oficina_ctx.execute(
            text(
                'INSERT INTO configuracion_global (clave, valor) VALUES '
                "('obra_oficina_activa', 'True') "
                'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
            )
        )
        oficina_ctx.commit()

        _planificadas, otras = obras_seleccionables(user_operario.id)
        assert cualquier_oficina(otras)
        assert otras[0].codigo == CODIGO_OFICINA

    def test_no_aparece_si_esta_apagada(self, oficina_ctx, user_operario):
        sincronizar_obra_oficina(True)
        sincronizar_obra_oficina(False)
        oficina_ctx.execute(
            text(
                'INSERT INTO configuracion_global (clave, valor) VALUES '
                "('obra_oficina_activa', 'False') "
                'ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor'
            )
        )
        oficina_ctx.commit()

        _planificadas, otras = obras_seleccionables(user_operario.id)
        assert not cualquier_oficina(otras)


def cualquier_oficina(obras):
    return any(o.codigo == CODIGO_OFICINA for o in obras)
