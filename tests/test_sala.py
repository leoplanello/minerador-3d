import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "mine"))
import server  # noqa: E402,F401  (põe scripts/mine no caminho)
import polyhaven  # noqa: E402
import render  # noqa: E402
import sala  # noqa: E402

BLENDER_OK = render.BLENDER.exists() and polyhaven.available()
STL = "solid t\n" + "".join(f"facet normal 0 0 1\nouter loop\nvertex {a}\nvertex {b}\nvertex {c}\nendloop\nendfacet\n" for a, b, c in [
    ("0 0 0", "40 0 0", "40 40 0"), ("0 0 0", "40 40 0", "0 40 0"), ("0 0 30", "40 40 30", "40 0 30"), ("0 0 30", "0 40 30", "40 40 30"),
    ("0 0 0", "40 0 30", "40 0 0"), ("0 0 0", "0 0 30", "40 0 30"), ("40 0 0", "40 40 30", "40 40 0"), ("40 0 0", "40 0 30", "40 40 30"),
    ("40 40 0", "0 40 30", "0 40 0"), ("40 40 0", "40 40 30", "0 40 30"), ("0 40 0", "0 0 30", "0 0 0"), ("0 40 0", "0 40 30", "0 0 30")]) + "endsolid t\n"


def test_caminho_fora_da_pasta_da_sala_e_recusado(tmp_path):
    assert sala.dentro(tmp_path, "modelos/a.stl") == (tmp_path / "modelos" / "a.stl").resolve()
    for ruim in ("../x.stl", "modelos/../../x.stl", str(Path(tmp_path).parent / "x.stl")):
        with pytest.raises(ValueError):
            sala.dentro(tmp_path, ruim)


def test_guardar_modelo_valida_formato_tamanho_e_converte_3mf(tmp_path):
    with pytest.raises(ValueError):
        sala.guardar_modelo(tmp_path, "virus.exe", b"x")
    with pytest.raises(ValueError):
        sala.guardar_modelo(tmp_path, "vazio.stl", b"")
    with pytest.raises(ValueError):
        sala.guardar_modelo(tmp_path, "grande.stl", b"xx", max_bytes=1)
    assert sala.guardar_modelo(tmp_path, "../fora/peça boa.stl", STL.encode()) == "modelos/peça boa.stl"
    from test_render import make3mf
    make3mf(tmp_path / "c.3mf")
    assert sala.guardar_modelo(tmp_path, "cubo.3mf", (tmp_path / "c.3mf").read_bytes()) == "modelos/cubo.stl"
    assert (tmp_path / "modelos" / "cubo.stl").read_text().count("facet normal") == 12


def test_catalogo_do_poly_haven_usa_a_api_e_valida_a_categoria():
    sala._cache.clear()
    chamadas = []

    def get(url):
        chamadas.append(url)
        return json.dumps({"b_chair": {"name": "Chair", "categories": ["furniture"], "dimensions": [500, 500, 900]}, "a_desk": {"name": "Desk", "categories": ["furniture"]}}).encode()
    itens = sala.catalogo("furniture", get)
    assert [i["nome"] for i in itens] == ["Chair", "Desk"] and itens[0]["dimensoes_mm"] == [500, 500, 900]
    sala.catalogo("furniture", get)
    assert len(chamadas) == 1 and "t=models" in chamadas[0]  # segunda chamada vem do cache
    with pytest.raises(ValueError):
        sala.catalogo("../../x", get)


def test_baixar_modelo_confere_md5_e_registra_a_origem(tmp_path):
    api = {f"{polyhaven.API}/files/cadeira_01": json.dumps({"gltf": {"1k": {"gltf": {"url": "https://x/cadeira_01.gltf", "md5": "aa", "include": {"textures/c.jpg": {"url": "https://x/c.jpg", "md5": "bb"}}}}}}).encode(),
           f"{polyhaven.API}/info/cadeira_01": json.dumps({"name": "Cadeira", "authors": {"Fulano": "All"}}).encode()}
    baixados = []
    fetch = lambda url, md5, dst: (baixados.append((url, md5)), dst.parent.mkdir(parents=True, exist_ok=True), dst.write_text("x"))  # noqa: E731
    g = sala.baixar_modelo("cadeira_01", tmp_path, api.__getitem__, fetch)
    assert g == tmp_path / "cadeira_01" / "cadeira_01.gltf" and len(baixados) == 2
    reg = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))["cadeira_01"]
    assert reg["license"] == "CC0 1.0" and reg["authors"] == ["Fulano"]
    sala.baixar_modelo("cadeira_01", tmp_path, api.__getitem__, fetch)  # já em disco: não baixa de novo
    assert len(baixados) == 2
    with pytest.raises(ValueError):
        sala.baixar_modelo("../x", tmp_path)


def test_abrir_exige_sala_abre_com_janela_e_nao_abre_duas_vezes(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "BLENDER", Path(sys.executable))
    with pytest.raises(ValueError, match="gere a sala"):
        sala.abrir(7, tmp_path, popen=lambda *a, **k: None)
    (tmp_path / "sala.blend").write_bytes(b"BLENDER")
    chamadas = []

    class P:
        def poll(self):
            return None

        def wait(self):
            return 0
    monkeypatch.setattr(render, "blend_layout", lambda *a: None)
    sala.abrir(7, tmp_path, popen=lambda cmd, **kw: chamadas.append((cmd, kw)) or P())
    assert chamadas[0][0][1].endswith("sala.blend") and chamadas[0][0][2] == "--python" and chamadas[0][0][3].endswith("blender_painel.py") and chamadas[0][1] == dict(show=True)
    assert sala.estado(7, tmp_path)["aberto"] is True
    with pytest.raises(ValueError, match="já está aberta"):
        sala.abrir(7, tmp_path, popen=lambda *a, **k: P())
    with pytest.raises(ValueError, match="feche o Blender"):
        sala.adicionar(7, tmp_path, [{"fonte": "polyhaven:x"}])
    with pytest.raises(ValueError, match="feche o Blender"):
        sala.gerar(tmp_path, "m.stl", {}, refazer=True)
    sala.ABERTOS.clear()


def test_adicionar_recusa_fonte_invalida_e_caminho_fora_da_pasta(tmp_path):
    (tmp_path / "sala.blend").write_bytes(b"BLENDER")
    for fonte in ("x:y", "arquivo:../fora.stl", "arquivo:modelos/nao-existe.stl"):
        with pytest.raises(ValueError):
            sala.adicionar(9, tmp_path, [{"fonte": fonte}])


@pytest.mark.skipif(not BLENDER_OK, reason="Blender portátil ou ativos do Poly Haven ausentes")
def test_sala_editavel_real_gera_edita_adiciona_e_renderiza(tmp_path):
    stl = tmp_path / "peca.stl"
    stl.write_text(STL)
    cena = dict(ambiente="escritorio", colocacao="mesa", luz="dia")
    blend = sala.gerar(tmp_path, stl, cena, "Suporte")
    assert blend.is_file() and not list(tmp_path.glob("*.novo.blend"))
    lay = {o["id"]: o for o in json.loads((tmp_path / "layout.json").read_text(encoding="utf-8"))["objetos"]}
    assert {"peca", "cam-cena", "cam-cena_frontal", "cam-cena_close", "Luz da janela", "parede-sala", "piso-sala"} <= set(lay)
    assert lay["peca"]["tipo"] == "peca" and lay["wooden_table_02"]["tipo"] == "movel" and lay["wooden_table_02"]["fonte"] == "polyhaven:wooden_table_02"  # cada móvel é um objeto só
    assert lay["dining_chair_02"]["pos"][0] == pytest.approx(650, abs=1) and lay["dining_chair_02"]["pos"][2] == pytest.approx(0, abs=1)  # em mm, base no piso

    antes = render.render_blend(blend, tmp_path / "antes", "cena", preview=True)
    move = tmp_path / "mover.py"
    move.write_text("import bpy\no = bpy.data.objects['peca']\no.location.x += 120\nbpy.ops.wm.save_mainfile()\n")
    subprocess.run([str(render.BLENDER), "-b", str(blend), "-P", str(move)], check=True, capture_output=True)  # o mesmo que o Leonardo faz com G e Ctrl+S
    depois = render.render_blend(blend, tmp_path / "depois", "cena", preview=True)
    from PIL import Image, ImageChops
    diff = ImageChops.difference(Image.open(antes).convert("L"), Image.open(depois).convert("L")).point(lambda v: 255 if v > 40 else 0)
    assert diff.getbbox() is not None and sum(diff.histogram()[255:]) > 300  # a mudança feita no arquivo aparece na imagem

    sala.adicionar(5, tmp_path, [{"fonte": "polyhaven:alarm_clock_01", "nome": "relogio"}])  # modelo do catálogo (já baixado pela sala)
    sala.guardar_modelo(tmp_path, "meu.stl", STL.encode())
    sala.adicionar(5, tmp_path, [{"fonte": "arquivo:modelos/meu.stl"}])
    lay = {o["id"]: o for o in json.loads((tmp_path / "layout.json").read_text(encoding="utf-8"))["objetos"]}
    assert lay["relogio"]["tipo"] == "movel" and lay["meu"]["fonte"] == "arquivo:modelos/meu.stl" and "peca" in lay

    frames = render.render_blend_frames(blend, tmp_path / "orb", 3, res=(320, 480))
    assert [f.name for f in frames] == ["render_1.jpg", "render_2.jpg", "render_3.jpg"]
    a, b = (Image.open(f).convert("L") for f in (frames[0], frames[2]))
    assert ImageChops.difference(a, b).getbbox() is not None  # a câmera se move em volta da peça
