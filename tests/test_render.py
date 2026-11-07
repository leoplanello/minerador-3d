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
    files = render.render_images(tmp_path / "c.3mf", tmp_path / "out", dict(views=["frente", "lado", "cima", "tras"]))
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


def test_enquadramento_e_giro():
    cfg = render.clean_render_cfg({"fill": "perto", "turn": "90"})
    assert cfg["fill"] == "perto" and cfg["turn"] == 90 and render.clean_render_cfg({})["fill"] == "medio"
    for bad in ({"fill": "x"}, {"turn": 360}, {"turn": -1}):
        with pytest.raises(ValueError):
            render.clean_render_cfg(bad)


def test_cenario_em_uso_automatico_pelo_titulo():
    auto = render.clean_render_cfg({})
    assert render.scene_for(auto, "Suporte Parede Vertical Compativel Roteador") == "parede"
    assert render.scene_for(auto, "Porta Chaves De Parede Com Porta Treco") == "parede"
    assert render.scene_for(auto, "Suporte de Mesa para Celular") == "mesa"
    assert render.scene_for(auto, "Vaso Decorativo Geométrico") == "mesa"
    assert render.scene_for(render.clean_render_cfg({"contexto": "mesa"}), "Suporte Parede") == "mesa"
    with pytest.raises(ValueError):
        render.clean_render_cfg({"contexto": "praia"})


@pytest.mark.skipif(not render.BLENDER.exists(), reason="Blender portátil não instalado")
@pytest.mark.parametrize("cenario", ["parede", "mesa"])
def test_render_real_em_uso_nao_vira_fundo_branco(tmp_path, cenario):
    from PIL import Image
    make3mf(tmp_path / "c.3mf")
    files = render.render_images(tmp_path / "c.3mf", tmp_path / "out", dict(views=["frente", "uso"], size=600, quality="rapido", contexto=cenario))
    studio, uso = (Image.open(f).convert("RGB") for f in files)
    assert min(studio.getpixel((5, 5))) > 235  # a foto principal continua com fundo branco
    assert min(uso.getpixel((5, 5))) < 245 or min(uso.getpixel((590, 590))) < 245  # o cenário tem cor e sombra, não é branco puro


def test_trajetoria_da_camera_abre_e_fecha_suave():
    p = render.camera_path(25)
    assert len(p) == 25 and p[0][2] == 0 and p[-1][2] == 1 and p[0][0] > p[-1][0]
    ts = [t for _, _, t in p]
    assert ts == sorted(ts) and ts[1] - ts[0] < ts[12] - ts[11]  # começa devagar
    assert render.camera_path(1)[0][2] == 0


def test_objeto_que_a_peca_segura_pelo_titulo():
    assert render.prop_for("Porta Chaves De Parede Com Porta Treco") == "chaves"
    assert render.prop_for("Suporte Parede Vertical Roteador Modem") == "modem"  # bloco em escala, com a peça de cada lado
    assert render.prop_for("Vaso Decorativo") == ""
    assert "uso_medio" in render.VIEWS and "uso_aberto" in render.VIEWS and render.RENDER_DEFAULT["views"][0] == "frente"


def test_ambiente_pelo_tipo_de_produto():
    auto = render.clean_render_cfg({})
    assert render.room_for(auto, "Porta Chaves De Parede Com Porta Treco") == "entrada"
    assert render.room_for(auto, "Suporte Parede Vertical Compativel Roteador Modem Ajustavel") == "escritorio"
    assert render.room_for(auto, "Vaso Decorativo Geométrico") == "sala"
    assert render.room_for(render.clean_render_cfg({"ambiente": "sala"}), "Porta Chaves") == "sala"
    with pytest.raises(ValueError):
        render.clean_render_cfg({"ambiente": "praia"})
    c = render.room_cfg(auto, "Suporte Roteador Modem")
    assert c["objeto"] == "modem" and c["montagem"] == "sobre_movel" and c["sala"] is render.polyhaven.ROOMS["escritorio"]
    assert render.room_cfg(auto, "Porta Chaves")["montagem"] == "parede_alta"


def test_todo_ambiente_so_usa_ativos_registrados():
    ph = render.polyhaven
    assert len(ph.ROOMS) >= 3
    for nome, r in ph.ROOMS.items():
        usados = [r["wall"][0], r["floor"][0], r["hdri"][0], r["support"][0]] + [i[0] for i in r["items"]] + [e[0] for e in r["extras"]]
        assert all(a in ph.ASSETS for a in usados), nome  # o que a cena usa é baixado e tem origem e licença registradas


def test_acabamento_das_fotos_em_uso_escurece_a_borda(tmp_path):
    from PIL import Image
    p = tmp_path / "a.jpg"
    Image.new("RGB", (400, 400), (200, 200, 200)).save(p)
    render.finish_photo(p)
    im = Image.open(p).convert("L")
    centro = sum(im.crop((190, 190, 210, 210)).getdata()) / 400
    borda = sum(im.crop((0, 0, 20, 20)).getdata()) / 400
    assert borda < centro - 15 and abs(centro - 200) < 20  # vinheta: canto mais escuro, centro quase igual


def test_sala_virtual_valida_os_controles():
    c = render.clean_cena({})
    assert c == render.CENA_DEFAULT | dict(escala_pct=100.0)
    c = render.clean_cena(dict(ambiente="oficina", colocacao="prateleira", escala_pct="150", giro="90", camera="orbital", luz="noite", referencia="caneca", lixo="x"))
    assert c["ambiente"] == "oficina" and c["escala_pct"] == 150.0 and c["giro"] == 90 and "lixo" not in c
    assert set(render.CENA_CHOICES["ambiente"]) >= {"sala", "entrada", "escritorio", "quarto", "cozinha", "oficina"}
    for ruim in (dict(ambiente="praia"), dict(colocacao="teto"), dict(escala_pct=5), dict(escala_pct=900), dict(giro=360), dict(giro="x"), dict(luz="alvorada"), dict(camera="drone"), dict(referencia="carro")):
        with pytest.raises(ValueError):
            render.clean_cena(ruim)
    az = [a for a, _, _ in render.orbit_path(21)]
    assert az[0] == -70 and az[-1] == 70 and az == sorted(az) and az[1] - az[0] < az[11] - az[10]  # meia volta, devagar no começo
    assert render.cena_cfg(c)["sala"] is render.polyhaven.ROOMS["oficina"] and render.cena_cfg(c)["objeto"] == ""


@pytest.mark.skipif(not render.BLENDER.exists() or not render.polyhaven.available(), reason="Blender portátil ou ativos do Poly Haven ausentes")
@pytest.mark.parametrize("colocacao", ["chao", "mesa", "parede", "prateleira"])
def test_sala_virtual_previa_real_em_cada_colocacao(tmp_path, colocacao):
    from PIL import Image
    make3mf(tmp_path / "c.3mf")
    f = render.render_cena(tmp_path / "c.3mf", tmp_path / "o", dict(ambiente="quarto", colocacao=colocacao, referencia="moeda", luz="tarde"), preview=True)
    im = Image.open(f)
    assert im.size == (640, 640)
    px = [im.getpixel((x, y)) for x in range(0, 640, 64) for y in range(0, 640, 64)]
    assert min(max(p) for p in px) < 250 and max(max(p) for p in px) > 40  # é uma cena com cor e luz, não fundo branco nem preto


def test_volta_completa_fecha_o_loop_com_passo_constante():
    ang = render.giro_path(8)
    passo = ang[1] - ang[0]
    assert ang[0] == 0 and abs(ang[-1] - (360 - passo)) < 1e-9  # o último quadro fica um passo antes do 360: o próximo é o primeiro
    assert all(abs((b - a) - passo) < 1e-9 for a, b in zip(ang, ang[1:]))  # velocidade constante: sem começo nem fim lento


def test_modo_do_giro_por_ambiente_e_colocacao():
    assert render.giro_modo(dict(ambiente="estudio")) == "camera"
    assert render.giro_modo(dict(ambiente="sala", colocacao="mesa")) == "peca"
    assert render.giro_modo(dict(ambiente="quarto", colocacao="chao")) == "peca"
    assert render.giro_modo(dict(ambiente="sala", colocacao="parede")) == ""  # peça na parede: sem volta completa (arco de meia volta)
    assert render.clean_cena({"ambiente": "estudio"})["ambiente"] == "estudio"
    assert render.cena_cfg(render.clean_cena({"ambiente": "estudio"}))["sala"] == dict(estudio=True)


def test_quadros_do_video_pedem_o_giro_certo(monkeypatch, tmp_path):
    import json
    import types
    seen = []

    def fake(args, **kw):  # o Blender de mentira: lê a configuração e cria os quadros pedidos
        cfg = json.loads(Path(args[-2]).read_text(encoding="utf-8"))
        seen.append(cfg)
        for i in range(1, len(cfg["views"]) + 1):
            (Path(args[-3]) / f"render_{i}.jpg").write_bytes(b"x")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    blender = tmp_path / "blender.exe"
    blender.write_bytes(b"")
    monkeypatch.setattr(render, "BLENDER", blender)
    monkeypatch.setattr(render.proc, "run", fake)
    stl = make3mf(tmp_path / "c.3mf")
    render.render_frames(stl, tmp_path / "e", 8, cena=dict(ambiente="estudio"))
    render.render_frames(stl, tmp_path / "m", 8, cena=dict(ambiente="sala", colocacao="mesa"))
    render.render_frames(stl, tmp_path / "p", 8, cena=dict(ambiente="sala", colocacao="parede"))
    estudio, mesa, parede = seen
    assert estudio["modo_giro"] == "camera" and [v[1] for v in estudio["views"]] == render.giro_path(8)  # a câmera dá a volta
    assert mesa["modo_giro"] == "peca" and [v[4] for v in mesa["views"]] == render.giro_path(8)  # a câmera fica, a peça gira no t
    assert parede["modo_giro"] == "" and [v[1] for v in parede["views"]][0] == -70  # parede: arco de meia volta, como antes
    assert len(estudio["views"]) == 8 and all(v[0] == "cena_orbital" for v in estudio["views"] + mesa["views"])


@pytest.mark.skipif(not render.BLENDER.exists(), reason="Blender portátil não instalado")
def test_estudio_real_mantem_a_peca_inteira_em_todo_o_giro(tmp_path):
    from PIL import Image, ImageChops
    make3mf(tmp_path / "c.3mf")
    frames = render.render_frames(tmp_path / "c.3mf", tmp_path / "out", 4, engine="EEVEE", res=(270, 480), title="Peça", cfg=dict(quality="rapido"),
                                  cena=dict(ambiente="estudio", colocacao="chao"))
    for f in frames:
        im = Image.open(f).convert("RGB")
        w, h = im.size
        fundo = im.getpixel((w // 2, 4))  # o topo do quadro é o fundo liso
        mascara = ImageChops.difference(im, Image.new("RGB", im.size, fundo)).convert("L").point(lambda v: 255 if v > 60 else 0)
        caixa = mascara.getbbox()
        assert caixa is not None, f"sem peça no quadro: {f.name}"
        assert caixa[0] > 0.05 * w and caixa[2] < 0.95 * w and caixa[1] > 0.05 * h and caixa[3] < 0.95 * h, f"peça cortada: {f.name} {caixa}"
