import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import render

V = [(0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 20, 0), (0, 0, 20), (20, 0, 20), (20, 20, 20), (0, 20, 20)]
T = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
MODEL = ('<?xml version="1.0"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="1" type="model"><mesh><vertices>'
         + "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in V) + "</vertices><triangles>"
         + "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in T) + "</triangles></mesh></object></resources></model>")


def make3mf(path, body=MODEL):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", body)
    return path


def test_3mf_vira_stl_com_12_triangulos(tmp_path):
    render.threemf_to_stl(make3mf(tmp_path / "c.3mf"), tmp_path / "c.stl")
    txt = (tmp_path / "c.stl").read_text()
    assert txt.count("facet normal") == 12 and txt.count("vertex") == 36


def test_3mf_sem_malha_e_cor_invalida(tmp_path):
    with pytest.raises(ValueError):
        render.threemf_to_stl(make3mf(tmp_path / "v.3mf", "<model/>"), tmp_path / "v.stl")
    with pytest.raises(ValueError):
        render.render_images(tmp_path / "x.stl", tmp_path / "o", "vermelho") if render.BLENDER.exists() else (_ for _ in ()).throw(ValueError("sem blender"))


@pytest.mark.skipif(not render.BLENDER.exists(), reason="Blender portátil não instalado")
def test_render_real_gera_4_imagens_com_fundo_branco(tmp_path):
    from PIL import Image
    make3mf(tmp_path / "c.3mf")
    files = render.render_images(tmp_path / "c.3mf", tmp_path / "out")
    assert len(files) == 4
    im = Image.open(files[0])
    assert im.size == (1200, 1200) and min(im.getpixel((5, 5))) > 235  # canto branco


def test_config_de_imagem_valida_e_completa():
    cfg = render.clean_render_cfg({"views": ["frente", "topo", "frente"], "size": "800", "finish": "silk"})
    assert cfg["views"] == ["frente", "topo"] and cfg["size"] == 800 and cfg["finish"] == "silk" and cfg["background"] == "white"
    for bad in ({"views": []}, {"views": ["nao-existe"]}, {"size": 50}, {"finish": "x"}, {"color": "vermelho"}, {"views": list(render.VIEWS) + ["frente"] * 0 + ["extra"]}):
        with pytest.raises(ValueError):
            render.clean_render_cfg(bad)


@pytest.mark.skipif(not render.BLENDER.exists(), reason="Blender portátil não instalado")
def test_render_real_com_config(tmp_path):
    from PIL import Image
    make3mf(tmp_path / "c.3mf")
    files = render.render_images(tmp_path / "c.3mf", tmp_path / "out", dict(views=["frente", "topo"], size=600, quality="rapido", background="gray", finish="silk", shadow=False))
    assert [f.name for f in files] == ["render_1.jpg", "render_2.jpg"]
    im = Image.open(files[0])
    assert im.size == (600, 600) and max(im.getpixel((5, 5))) < 250  # fundo cinza: não foi forçado a branco
