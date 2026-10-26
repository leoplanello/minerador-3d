"""Páginas reais do Mercado Livre salvas em tests/fixtures; quebram aqui se o ML mudar o formato."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts" / "mine"))
from classify import parse_reviews, parse_sold
from store_reader import extract_links


def hrefs(name):
    return json.loads((HERE / "fixtures" / f"{name}_hrefs.json").read_text(encoding="utf-8"))


def test_pagina_tem_anuncios():
    links = extract_links(hrefs("pagina"))
    assert len(links) >= 5
    assert all("/up/MLBU" in u or "MLB" in u for u in links)


def test_custid_tem_anuncios():
    assert len(extract_links(hrefs("custid"))) >= 5


def test_anuncio_up_parsers():
    text = (HERE / "fixtures" / "anuncio_up.txt").read_text(encoding="utf-8")
    assert parse_sold(text) == 1000
    assert parse_reviews(text) == 128
