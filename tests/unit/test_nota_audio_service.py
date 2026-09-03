"""Tests de matching para notas por voz."""
from types import SimpleNamespace

from app.services.nota_audio_service import (
    allowed_audio_file,
    match_obras_from_queries,
    match_obras_from_text,
    match_persons_from_names,
)


def _obra(id_, nombre, codigo=None):
    return SimpleNamespace(id=id_, nombre=nombre, codigo=codigo)


def _company(is_internal=True):
    return SimpleNamespace(is_internal=is_internal)


def _user(id_, name, lastname='', *, internal=True):
    return SimpleNamespace(
        id=id_,
        name=name,
        lastname=lastname,
        is_deleted=False,
        active=True,
        company_rel=_company(internal),
    )


class TestNotaAudioFormats:
    def test_allowed_extensions(self):
        assert allowed_audio_file('reunion.m4a') is True
        assert allowed_audio_file('nota.MP3') is True
        assert allowed_audio_file('documento.pdf') is False


class TestObraMatching:
    def test_detects_full_obra_name_in_transcript(self):
        obras = [_obra(1, 'Hospital Teruel Norte'), _obra(2, 'Colegio Madrid Centro')]
        text = 'Hoy en Hospital Teruel Norte faltan baldosas.'
        matches = match_obras_from_text(text, obras)
        assert len(matches) == 1
        assert matches[0].obra_id == 1

    def test_detects_obra_by_codigo(self):
        obras = [_obra(3, 'Reforma nave industrial norte', codigo='OB-2024-15')]
        text = 'Seguimos con OB-2024-15 la semana que viene.'
        matches = match_obras_from_text(text, obras)
        assert any(m.obra_id == 3 for m in matches)

    def test_place_name_alone_does_not_link_all_obras(self):
        obras = [
            _obra(1, 'CENTRO SALUD CATARROJA FASE 2'),
            _obra(2, 'REFORMA SONEPAR CATARROJA'),
            _obra(3, 'ESPAI BARRAQUES CATARROJA'),
            _obra(4, 'VARIOS'),
            _obra(5, 'Oficina'),
        ]
        matches = match_obras_from_queries(['Catarroja', 'VARIOS', 'Oficina'], obras)
        linked = [m for m in matches if m.obra_id]
        assert linked == []

    def test_specific_obra_query_links_one(self):
        obras = [
            _obra(1, 'CENTRO SALUD CATARROJA FASE 2'),
            _obra(2, 'REFORMA SONEPAR CATARROJA'),
        ]
        matches = match_obras_from_queries(['Centro Salud Catarroja Fase 2'], obras)
        linked = [m for m in matches if m.obra_id]
        assert len(linked) == 1
        assert linked[0].obra_id == 1

    def test_ambiguous_obra_suggests_candidates(self):
        obras = [
            _obra(1, 'FASE 2 CATARROJA CLIMA'),
            _obra(2, 'FASE 2 CATARROJA ELECTRICIDAD'),
        ]
        matches = match_obras_from_queries(['Fase 2 Catarroja'], obras)
        assert matches
        assert matches[0].obra_id is None
        assert matches[0].ambiguous is True
        assert len(matches[0].candidates) >= 2


class TestPersonMatching:
    def test_unique_full_name_linked(self):
        users = [
            _user(10, 'Manolo', 'García'),
            _user(11, 'Pedro', 'López'),
        ]
        matches = match_persons_from_names(['Manolo García'], users)
        assert len(matches) == 1
        assert matches[0].user_id == 10
        assert matches[0].ambiguous is False

    def test_ambiguous_first_name_suggests(self):
        users = [
            _user(20, 'Manolo', 'Pérez'),
            _user(21, 'Manolo', 'López'),
        ]
        matches = match_persons_from_names(['Manolo'], users)
        assert len(matches) == 1
        assert matches[0].user_id is None
        assert matches[0].ambiguous is True
        assert len(matches[0].candidates) >= 2

    def test_unique_jairo_inverted_storage_links(self):
        # Ficha tipo apellidos + nombre en lastname
        users = [
            _user(40, 'CARO ORTEGA', 'JAIRO'),
            _user(41, 'Pedro', 'López'),
        ]
        matches = match_persons_from_names(['Jairo'], users)
        assert len(matches) == 1
        assert matches[0].user_id == 40
        assert matches[0].ambiguous is False

    def test_unique_internal_vicente_links(self):
        users = [
            _user(50, 'Vicente', 'Pons', internal=True),
            _user(51, 'Juan Vicente', 'Ruiz', internal=False),
            _user(52, 'Pedro', 'Vicente', internal=False),
        ]
        matches = match_persons_from_names(['Vicente'], users)
        assert len(matches) == 1
        assert matches[0].user_id == 50

    def test_elena_does_not_match_helena(self):
        users = [_user(30, 'Helena', 'Morales')]
        matches = match_persons_from_names(['Elena'], users)
        assert matches[0].user_id is None

    def test_dedupes_jairo_variants(self):
        users = [_user(40, 'Jairo', 'Cano')]
        matches = match_persons_from_names(['Jairo', 'Jairo Cano'], users)
        assert len(matches) == 1
        assert matches[0].user_id == 40
