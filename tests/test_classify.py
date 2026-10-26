import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "mine"))
from classify import is_3d, parse_material, parse_price, parse_reviews, parse_sold, score


def test_parse_sold():
    assert parse_sold("Novo | +100 vendidos") == 100
    assert parse_sold("3 vendidos") == 3
    assert parse_sold("+1 mil vendidos") == 1000
    assert parse_sold("nada") == 0


def test_parse_others():
    assert parse_price("por R$ 1.234,50 no pix") == 1234.5
    assert parse_price("R$ 39") == 39.0
    assert parse_price("(612)\nR$\n22\n,\n90\nR$\n19\n,\n24\n15% OFF") == 19.24
    assert parse_reviews("4.8 (1.204 avaliações)") == 1204
    assert parse_material("Marca\nX\nMaterial\nPLA Biodegradável\nCor\nPreto") == "PLA Biodegradável"


def test_is_3d():
    assert is_3d("PLA", "") == 1
    assert is_3d("", "feito com impressão 3D") == 1
    assert is_3d("Acrílico", "suporte") == 0
    assert is_3d("ABS", "organizador de mesa") == 0  # ABS sozinho pode ser injetado
    assert is_3d("ABS", "peça em filamento") == 1


def test_score():
    assert score(100, 50, 39, 0, 1) == 0
    assert score(100, 50, 39, 1, 1) > score(100, 50, 99, 1, 1)
    assert score(100, 50, 39, 1, 1) > score(5, 2, 39, 1, 1)
