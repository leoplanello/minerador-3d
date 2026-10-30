import struct
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import estudio  # noqa: E402
from PIL import Image  # noqa: E402

MODEL = '<?xml version="1.0" encoding="UTF-8"?>\n<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter">\n<resources>\n' \
        '<object id="1" type="model"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/><vertex x="0" y="10" z="0"/></vertices>' \
        '<triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>\n' \
        '<object id="2" type="model"><components><component p:path="/3D/3dmodel.model" objectid="1" transform="1 0 0 0 1 0 0 0 1 100 0 0"/></components></object>\n' \
        '</resources>\n<build><item objectid="2" transform="1 0 0 0 1 0 0 0 1 0 5 0"/></build></model>'


def _3mf(tmp_path, xml=MODEL):
    arquivo = tmp_path / "peca.3mf"
    with zipfile.ZipFile(arquivo, "w") as z:
        z.writestr("3D/3dmodel.model", xml)
    return arquivo


def test_3mf_monta_componente_com_transformacao_do_item(tmp_path):
    src = _3mf(tmp_path)
    dst = tmp_path / "peca.stl"
    assert estudio.modelo_para_stl(src, dst) == 1
    dados = dst.read_bytes()
    n = struct.unpack("<I", dados[80:84])[0]
    assert n == 1
    vals = struct.unpack("<12f", dados[84 + 0:84 + 48])
    # normal (3) + três vértices: (0,0,0)+(100,0,0)+(0,5,0)... vértice 1 = (10,0,0) -> (110,5,0)
    v1 = vals[3:6]
    v2 = vals[6:9]
    v3 = vals[9:12]
    assert v1 == pytest.approx((100, 5, 0)) and v2 == pytest.approx((110, 5, 0)) and v3 == pytest.approx((100, 15, 0))


def test_3mf_sem_peca_recusa(tmp_path):
    xml = '<?xml version="1.0"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources/><build/></model>'
    with pytest.raises(ValueError):
        estudio.modelo_para_stl(_3mf(tmp_path, xml), tmp_path / "x.stl")


def test_sobre_branco_troca_transparencia_por_branco(tmp_path):
    arquivo = tmp_path / "foto.png"
    im = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    im.putpixel((1, 1), (200, 0, 0, 255))  # peça opaca
    im.save(arquivo)
    estudio.sobre_branco(arquivo)
    out = Image.open(arquivo)
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (255, 255, 255)
    assert out.getpixel((1, 1)) == (200, 0, 0)


def test_sobre_branco_mantem_sombra_semitransparente(tmp_path):
    arquivo = tmp_path / "sombra.png"
    Image.new("RGBA", (2, 2), (0, 0, 0, 128)).save(arquivo)
    estudio.sobre_branco(arquivo)
    r, g, b = Image.open(arquivo).getpixel((0, 0))
    assert r == g == b and 100 < r < 160  # cinza claro, não preto nem branco puro


def test_gerar_recusa_sem_blender(tmp_path, monkeypatch):
    monkeypatch.setattr(estudio, "_blender", lambda: tmp_path / "nao-existe" / "blender.exe")
    with pytest.raises(ValueError, match="Blender"):
        estudio.gerar(_3mf(tmp_path), tmp_path / "saida")


def test_medida_sai_em_centimetros_com_virgula():
    assert estudio._cm(135) == "13,5 cm"
    assert estudio._cm(139.2) == "13,9 cm"


def test_cotas_nao_cobrem_o_produto(tmp_path):
    """Textos das cotas ficam fora da silhueta do produto (que é um retângulo de teste no centro da imagem)."""
    origem, destino = tmp_path / "base.png", tmp_path / "cotas.png"
    Image.new("RGB", (960, 960), (255, 255, 255)).save(origem)
    medidas = dict(cantos={"000": [300, 800], "100": [700, 820], "010": [320, 300], "001": [300, 300], "110": [760, 700], "101": [740, 300],
                           "011": [300, 250], "111": [740, 250]},
                   silhueta={"esq": [300, 500], "dir": [700, 600], "topo": [500, 200], "base": [500, 800]},
                   dimensoes_mm=[135, 131, 139], tamanho=960)
    estudio.cotas_2d(origem, medidas, destino)
    out = Image.open(destino)
    assert out.size == (960, 960)
    miolo = out.crop((350, 260, 650, 760)).convert("L")
    pretos = sum(1 for px in miolo.getdata() if px < 60)
    assert pretos == 0  # nenhuma linha ou texto dentro da área do produto
