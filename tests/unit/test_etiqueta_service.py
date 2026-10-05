"""Etiquetas: normalización y texto de búsqueda."""
from types import SimpleNamespace

from app.services.etiqueta_service import (
    company_search_tag_text,
    normalize_color,
    user_search_tag_text,
)


def test_normalize_color_blank_is_none():
    assert normalize_color(None) is None
    assert normalize_color('#ffffff') is None
    assert normalize_color('white') is None
    assert normalize_color('#22c55e') == '#22c55e'


def test_user_search_includes_company_tags():
    emp_tag = SimpleNamespace(nombre='Frigorista')
    co_tag = SimpleNamespace(nombre='Gas')
    company = SimpleNamespace(etiquetas=[co_tag])
    user = SimpleNamespace(etiquetas=[emp_tag], company_rel=company)
    text = user_search_tag_text(user)
    assert 'Frigorista' in text
    assert 'Gas' in text


def test_company_search_only_own():
    co = SimpleNamespace(etiquetas=[SimpleNamespace(nombre='Electricidad')])
    assert company_search_tag_text(co) == 'Electricidad'
