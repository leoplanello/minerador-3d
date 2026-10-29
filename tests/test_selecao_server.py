import json
import struct
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import server


def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    monkeypatch.setattr(server, "PRODUCTS", tmp_path / "products")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    server.init()
    with server.db() as c:
        c.execute("INSERT INTO stores(url) VALUES('u')")
        for i, (titulo, preco, vendidos) in enumerate([("Suporte Parede Roteador Modem Preto", 30.0, 300), ("Organizador Colorido Para Montar Com Parafusos", 25.0, 900),
                                                         ("Suporte Roteador Modem Parede Vertical", 45.0, 40)], 1):
            c.execute("INSERT INTO listings(store_id,url,title,price,is_3d) VALUES(1,?,?,?,1)", (f"l{i}", titulo, preco))
            c.execute("INSERT INTO snapshots(listing_id,sold,reviews,rank) VALUES(?,?,5,1)", (i, vendidos))


def stl(path, x, y, z):
    v = [(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
    t = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * 80 + struct.pack("<I", 12) + b"".join(struct.pack("<12fH", 0, 0, 0, *v[a], *v[b], *v[c], 0) for a, b, c in t))


def test_reprovado_no_filtro_vai_para_o_fim_com_o_motivo(tmp_path, monkeypatch):
    banco(tmp_path, monkeypatch)
    rows = server.candidates()
    por_id = {r["id"]: r for r in rows}
    assert por_id[2]["filtros"]["status"] == "reprovado" and any("montagem" in m for m in por_id[2]["filtros"]["reasons"])
    assert por_id[1]["filtros"]["status"] == "pendente" and rows[-1]["id"] == 2  # o reprovado fica por último mesmo vendendo mais
    server.put_setting("filters", selecao_filtros(allow_assembly=True, max_colors=3))
    assert {r["id"]: r["filtros"]["status"] for r in server.candidates()}[2] == "pendente"


def selecao_filtros(**kw):
    return server.selecao.clean_filters(kw)


def test_modelo_grande_reprova_e_avaliacao_guarda_as_medidas(tmp_path, monkeypatch):
    banco(tmp_path, monkeypatch)
    stl(tmp_path / "products/1/model/grande.stl", 300, 140, 115)
    with server.db() as c:
        c.execute("INSERT INTO models(listing_id,file_path) VALUES(1,'products/1/model/grande.stl')")
    monkeypatch.setattr(server.fatiar, "check_support", lambda model, out: dict(support=False, lines=0, minutes=60, grams=10))
    d = server.eval_filters(1)
    assert d["status"] == "ok" and d["stats"]["dims"] == [300, 140, 115] and d["support"] is False
    f = {r["id"]: r for r in server.candidates()}[1]["filtros"]
    assert f["status"] == "reprovado" and "não cabe" in f["reasons"][0] and f["stats"]["dims"] == [300, 140, 115]


def test_suporte_reprova_e_falha_do_teste_nao_derruba(tmp_path, monkeypatch):
    banco(tmp_path, monkeypatch)
    stl(tmp_path / "products/1/model/m.stl", 50, 50, 50)
    with server.db() as c:
        c.execute("INSERT INTO models(listing_id,file_path) VALUES(1,'products/1/model/m.stl')")
        c.execute("INSERT INTO slices(listing_id,minutes,grams) VALUES(1,90,20)")
    monkeypatch.setattr(server.fatiar, "check_support", lambda model, out: dict(support=True, lines=50, minutes=120, grams=25))
    server.eval_filters(1)
    assert server.candidates()[0]["filtros"]["reasons"] == ["precisa de suporte de impressão"] or {r["id"]: r for r in server.candidates()}[1]["filtros"]["reasons"] == ["precisa de suporte de impressão"]
    monkeypatch.setattr(server.fatiar, "check_support", lambda model, out: (_ for _ in ()).throw(ValueError("sem fatiador")))
    d = server.eval_filters(1)
    assert d["support"] is None and "indisponível" in d["msg"] and d["stats"]["dims"] == [50, 50, 50]


def test_vendas_por_dia_pela_data_de_publicacao(tmp_path, monkeypatch):
    banco(tmp_path, monkeypatch)
    from datetime import date, timedelta
    server.set_created(1, (date.today() - timedelta(days=100)).isoformat())
    server.set_created(3, (date.today() - timedelta(days=20)).isoformat())
    por_id = {r["id"]: r for r in server.candidates()}
    assert por_id[1]["per_day"] == 3.0 and por_id[1]["champion"] is True and por_id[1]["age_days"] == 100
    assert por_id[3]["per_day"] == 2.0 and por_id[2]["per_day"] is None and por_id[2]["champion"] is False
    for ruim in ("2999-01-01", "ontem", "2026-13-40"):
        with pytest.raises(ValueError):
            server.set_created(1, ruim)
    server.set_created(1, "")  # limpar vale
    assert {r["id"]: r for r in server.candidates()}[1]["per_day"] is None


def test_api_de_filtros_e_similares(tmp_path, monkeypatch):
    banco(tmp_path, monkeypatch)
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        get = lambda p: json.load(urllib.request.urlopen(base + p, timeout=10))

        def post(p, d):
            try:
                return json.load(urllib.request.urlopen(urllib.request.Request(base + p, json.dumps(d).encode()), timeout=10))
            except urllib.error.HTTPError as e:
                return json.load(e) | {"http": e.code}
        v = get("/api/filtros")["values"]
        assert v["printer"] == "Bambu Lab A1 Mini" and v["max_hours"] == 4
        assert post("/api/filtros", dict(v, max_hours=2.5, stock_colors=["Preto"]))["ok"] and get("/api/filtros")["values"]["max_hours"] == 2.5
        assert post("/api/filtros", dict(v, printer="Outra"))["http"] == 400
        assert post("/api/listing/created", dict(id=1, created="2024-01-01"))["ok"] and post("/api/listing/created", dict(id=1, created="amanha"))["http"] == 400
        sim = get("/api/similares?id=1")
        assert [r["id"] for r in sim["rows"]] == [1, 3] or {r["id"] for r in sim["rows"]} == {1, 3}
        assert sim["price"] == dict(min=45.0, median=45.0, max=45.0, n=1)
        try:
            get("/api/similares?id=99")
            raise AssertionError("devia dar 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()


def test_tese_proposta_guarda_dor_similares_e_faixa_dos_parecidos(tmp_path, monkeypatch):
    banco(tmp_path, monkeypatch)
    from PIL import Image
    monkeypatch.setattr(server, "IMAGES", tmp_path / "img")
    (tmp_path / "img").mkdir()
    Image.new("RGB", (50, 50)).save(tmp_path / "img" / "1.img", format="PNG")
    visto = {}
    monkeypatch.setattr(server.selecao, "propose_thesis", lambda title, photo, titles: visto.update(titles=titles) or dict(dor="liberar a mesa", similares=[dict(nome="Suporte de modem", busca="suporte modem")]))
    server.propose_tese(1)
    t = {r["id"]: r for r in server.candidates()}[1]["tese"]
    assert t["status"] == "ok" and t["dor"] == "liberar a mesa" and t["proposta"] is True
    assert (t["faixa_min"], t["faixa_max"]) == (45.0, 45.0) and visto["titles"] == ["Suporte Roteador Modem Parede Vertical"]  # só o parecido entra, sem o próprio produto
    monkeypatch.setattr(server.selecao, "propose_thesis", lambda *a: (_ for _ in ()).throw(ValueError("sem Claude")))
    server.propose_tese(1)
    t = server.get_setting("tese:1")
    assert t["status"] == "error" and "sem Claude" in t["msg"] and t["dor"] == "liberar a mesa"  # o erro não apaga o que já estava
    (tmp_path / "img" / "1.img").unlink()
    server.propose_tese(1)
    assert "sem a foto" in server.get_setting("tese:1")["msg"]


def test_funil_familias_e_desempenho(tmp_path, monkeypatch):
    banco(tmp_path, monkeypatch)
    ov = server.selecao_overview()
    assert [f["members"] for f in ov["families"]] == [[1, 3]] and list(ov["limites"]["abrir"]) == [5, 10]
    assert {c["id"] for c in ov["candidatos"]} == {1, 2, 3}
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        def post(p, d):
            try:
                return json.load(urllib.request.urlopen(urllib.request.Request(base + p, json.dumps(d).encode()), timeout=10))
            except urllib.error.HTTPError as e:
                return json.load(e) | {"http": e.code}
        r = post("/api/funil", dict(lista=[1, 2, 3], escolhidos=[1, 3]))
        assert r["ok"] and len(r["avisos"]) == 2
        assert post("/api/funil", dict(lista=[1, 99]))["http"] == 400
        assert post("/api/funil/leitura", dict(id=1))["http"] == 400  # sem publicação no ML e sem número informado
        assert post("/api/funil/leitura", dict(id=1, sold=0, price=30))["ok"]
        pts = server.get_setting("perf:1")
        pts[0]["ts"] = "2026-10-01T10:00:00"
        server.put_setting("perf:1", pts)
        assert post("/api/funil/leitura", dict(id=1, sold=12, price=30))["ok"]
        linha = {r["id"]: r for r in server.selecao_overview()["linhas"]}[1]
        assert linha["escolhido"] and linha["desempenho"]["suggestion"] in ("mantem", "sai") and linha["desempenho"]["days"] >= 14 and linha["leituras"][-1]["sold"] == 12
        assert {r["id"] for r in server.selecao_overview()["linhas"]} == {1, 2, 3}
    finally:
        srv.shutdown()


def test_api_da_sala_virtual(tmp_path, monkeypatch):
    banco(tmp_path, monkeypatch)
    stl(tmp_path / "products/1/model/m.stl", 40, 30, 20)
    with server.db() as c:
        c.execute("INSERT INTO models(listing_id,file_path) VALUES(1,'products/1/model/m.stl')")
    vistos = []

    def falso(model, outdir, cena, preview=False, title=""):
        vistos.append((Path(model).name, cena["ambiente"], cena["colocacao"], preview))
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "render_1.jpg").write_bytes(b"\xff\xd8jpg")
        return outdir / "render_1.jpg"
    monkeypatch.setattr(server.renderizar, "render_cena", falso)
    monkeypatch.setattr(server.polyhaven, "ensure", lambda: {})
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    b = f"http://127.0.0.1:{srv.server_port}"
    try:
        def post(p, d, raw=None):
            try:
                return json.load(urllib.request.urlopen(urllib.request.Request(b + p, raw if raw is not None else json.dumps(d).encode()), timeout=20))
            except urllib.error.HTTPError as e:
                return json.load(e) | {"http": e.code}
        d = json.load(urllib.request.urlopen(b + "/api/cena?id=1", timeout=10))
        assert d["cena"]["ambiente"] == "sala" and "quarto" in d["ambientes"] and d["previa"] is False and d["modelo_enviado"] is None
        r = post("/api/cena/previa", dict(id=1, cena=dict(ambiente="cozinha", colocacao="prateleira")))
        assert r["ok"] and r["url"].startswith("/products/1/cena/previa.jpg") and vistos[-1] == ("m.stl", "cozinha", "prateleira", True)
        assert urllib.request.urlopen(b + "/products/1/cena/previa.jpg", timeout=10).read().startswith(b"\xff\xd8")
        assert json.load(urllib.request.urlopen(b + "/api/cena?id=1", timeout=10))["cena"]["ambiente"] == "cozinha"  # lembra a última escolha
        assert post("/api/cena/previa", dict(id=1, cena=dict(ambiente="praia")))["http"] == 400
        assert post("/api/cena/previa", dict(id=99, cena={}))["http"] == 400
        # modelo enviado só para a cena: não troca o do produto
        up = post("/api/cena/modelo?id=1&name=../../meu%20vaso.stl", None, raw=b"\0" * 80 + struct.pack("<I", 0))
        assert up["ok"] and up["arquivo"] == "modelo.stl" and (tmp_path / "products/1/cena/modelo.stl").is_file()
        assert post("/api/cena/modelo?id=1&name=x.exe", None, raw=b"abc")["http"] == 400
        post("/api/cena/previa", dict(id=1, cena=dict(modelo="enviado")))
        assert vistos[-1][0] == "modelo.stl"
        assert server.get_setting("cena:1")["modelo"] == "enviado"
        r = post("/api/cena/render", dict(id=1, cena=dict(ambiente="sala", colocacao="mesa")))
        assert r["ok"]
        for _ in range(100):
            if server.CENA_JOBS[1]["status"] != "running":
                break
            time.sleep(0.05)
        assert server.CENA_JOBS[1]["status"] == "ok" and (tmp_path / "products/1/renders/cena_1.jpg").is_file() and vistos[-1][3] is False
        assert "cena_1.jpg" in [m["name"] for m in server.media_files(1)]  # a imagem entra na galeria do produto
    finally:
        srv.shutdown()


def test_api_da_sala_editavel_gera_abre_adiciona_e_renderiza_do_blend(tmp_path, monkeypatch):
    banco(tmp_path, monkeypatch)
    stl(tmp_path / "products/1/model/m.stl", 40, 30, 20)
    with server.db() as c:
        c.execute("INSERT INTO models(listing_id,file_path) VALUES(1,'products/1/model/m.stl')")
    feitos = []

    def gerar_falso(model, blend, cena, title=""):
        feitos.append(("gerar", Path(model).name, cena["ambiente"]))
        Path(blend).write_bytes(b"BLENDER-gerado")
        return blend

    def render_falso(blend, outdir, camera="cena", preview=False, engine=None):
        feitos.append(("render", camera, preview))
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "render_1.jpg").write_bytes(b"\xff\xd8blend")
        return outdir / "render_1.jpg"

    def frames_falso(blend, outdir, n, engine="EEVEE", res=(1080, 1920), **kw):
        feitos.append(("frames", n))
        outdir.mkdir(parents=True, exist_ok=True)
        out = [outdir / f"render_{i}.jpg" for i in range(1, n + 1)]
        for f in out:
            f.write_bytes(b"\xff\xd8")
        return out
    r = server.renderizar
    monkeypatch.setattr(r, "gerar_blend", gerar_falso)
    monkeypatch.setattr(r, "render_blend", render_falso)
    monkeypatch.setattr(r, "render_blend_frames", frames_falso)
    monkeypatch.setattr(r, "blend_layout", lambda blend, saida: Path(saida).write_text(json.dumps(dict(objetos=[dict(id="peca", tipo="peca"), dict(id="cam-cena", tipo="camera")])), encoding="utf-8"))
    adicionados = []
    monkeypatch.setattr(r, "blend_adicionar", lambda blend, itens: adicionados.extend(itens))
    monkeypatch.setattr(server.polyhaven, "ensure", lambda: {})
    monkeypatch.setattr(server.sala, "baixar_modelo", lambda asset, *a, **k: tmp_path / f"{asset}.gltf")
    aberto = []
    monkeypatch.setattr(server.sala.proc, "popen", lambda cmd, **kw: aberto.append((cmd, kw)) or type("P", (), {"poll": lambda s: None, "wait": lambda s: None})())
    monkeypatch.setattr(r, "BLENDER", Path(sys.executable))
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    b = f"http://127.0.0.1:{srv.server_port}"

    def post(p, d, raw=None):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(b + p, raw if raw is not None else json.dumps(d).encode()), timeout=20))
        except urllib.error.HTTPError as e:
            return json.load(e) | {"http": e.code}

    def espera():
        for _ in range(200):
            if server.CENA_JOBS[1]["status"] != "running":
                break
            time.sleep(0.05)
        return server.CENA_JOBS[1]
    try:
        assert json.load(urllib.request.urlopen(b + "/api/cena?id=1", timeout=10))["sala"]["existe"] is False
        assert post("/api/cena/sala/abrir", dict(id=1))["http"] == 400  # sem sala ainda
        assert post("/api/cena/sala/gerar", dict(id=1, cena=dict(ambiente="quarto")))["ok"]
        j = espera(); assert j["status"] == "ok" and feitos[0] == ("gerar", "m.stl", "quarto"), j
        s = json.load(urllib.request.urlopen(b + "/api/cena?id=1", timeout=10))["sala"]
        assert s["existe"] and [o["id"] for o in s["objetos"]] == ["peca"] and s["aberto"] is False
        assert post("/api/cena/sala/gerar", dict(id=1, cena={}))["ok"] and espera()["status"] == "error"  # já existe: só com Refazer
        # com sala.blend, a prévia, a imagem final e o vídeo saem do arquivo
        assert post("/api/cena/previa", dict(id=1, cena=dict(camera="close")))["ok"] and feitos[-1] == ("render", "cena_close", True)
        assert post("/api/cena/render", dict(id=1, cena={}))["ok"] and espera()["status"] == "ok" and feitos[-1] == ("render", "cena", False)
        assert post("/api/cena/video", dict(id=1, cena={}, segundos=3))["ok"]
        assert espera()["status"] in ("ok", "error") and feitos[-1] == ("frames", 72)
        # importar modelo próprio e catálogo
        assert post("/api/cena/sala/importar?id=1&name=virus.exe", None, raw=b"x")["http"] == 400
        up = post("/api/cena/sala/importar?id=1&name=../meu%20vaso.glb", None, raw=b"glTF" * 4)
        assert up["fonte"] == "arquivo:modelos/meu vaso.glb"
        assert post("/api/cena/sala/adicionar", dict(id=1, itens=[{"fonte": up["fonte"]}, {"fonte": "polyhaven:cadeira_01"}]))["ok"] and espera()["status"] == "ok"
        assert [i["fonte"] for i in adicionados] == ["arquivo:modelos/meu vaso.glb", "polyhaven:cadeira_01"]
        assert post("/api/cena/sala/adicionar", dict(id=1, itens=[{"fonte": "arquivo:../fora.glb"}]))["ok"] and espera()["status"] == "error"
        assert post("/api/cena/sala/adicionar", dict(id=1, itens=[]))["http"] == 400
        # abrir: processo com janela; enquanto aberto, não deixa abrir de novo, adicionar nem refazer
        assert post("/api/cena/sala/abrir", dict(id=1))["ok"] and aberto[0][1] == dict(show=True) and aberto[0][0][1].endswith("sala.blend") and "blender_painel.py" in aberto[0][0][3]
        assert json.load(urllib.request.urlopen(b + "/api/cena?id=1", timeout=10))["sala"]["aberto"] is True
        assert post("/api/cena/sala/abrir", dict(id=1))["http"] == 400
        assert post("/api/cena/sala/adicionar", dict(id=1, itens=[{"fonte": "polyhaven:x"}]))["ok"] and espera()["status"] == "error"
        assert post("/api/cena/sala/gerar", dict(id=1, cena={}, refazer=True))["ok"] and espera()["status"] == "error"
        assert (tmp_path / "products/1/cena/sala.blend").read_bytes() == b"BLENDER-gerado"  # nada foi apagado
    finally:
        server.sala.ABERTOS.clear()
        srv.shutdown()
