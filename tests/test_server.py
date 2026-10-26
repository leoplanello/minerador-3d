import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import server


def test_candidates_crescimento(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    server.init()
    with server.db() as c:
        c.execute("INSERT INTO stores(url) VALUES('u')")
        c.execute("INSERT INTO listings(store_id,url,title,price,is_3d) VALUES(1,'l','t',39,1)")
        c.executemany("INSERT INTO snapshots(listing_id,sold,reviews,rank) VALUES(1,?,?,1)", [(100, 50), (100, 53), (500, 60)])
    (cand,) = server.candidates()
    assert (cand["growth"], cand["sold_growth"], cand["history"], cand["snapshots"]) == (10, 400, [50, 53, 60], 3)


def _produto(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    monkeypatch.setattr(server, "PRODUCTS", tmp_path / "products")
    server.init()
    with server.db() as c:
        c.execute("INSERT INTO stores(url) VALUES('u')")
        c.execute("INSERT INTO listings(store_id,url,title) VALUES(1,'l','t')")
        c.execute("INSERT INTO snapshots(listing_id,sold,reviews,rank) VALUES(1,10,5,1)")  # toda leitura grava listing + snapshot juntos
        c.executemany("INSERT INTO steps(listing_id,name) VALUES(1,?)", [(s,) for s in server.STEPS])


def test_modelo_envio_marca_etapa_ok(tmp_path, monkeypatch):
    _produto(tmp_path, monkeypatch)
    server.set_model(1, "../../vaso bonito.3mf", b"dados")  # caminho do nome é descartado
    assert (tmp_path / "products" / "1" / "model" / "vaso bonito.3mf").read_bytes() == b"dados"
    (cand,) = server.candidates()
    assert cand["steps"]["model"] == "ok" and cand["model"]["file_path"] == "products/1/model/vaso bonito.3mf"


def test_modelo_recusa_extensao_vazio_e_link_ruim(tmp_path, monkeypatch):
    _produto(tmp_path, monkeypatch)
    import pytest
    for name, data in [("x.exe", b"a"), ("x.stl", b"")]:
        with pytest.raises(ValueError):
            server.set_model(1, name, data)
    with pytest.raises(ValueError):
        server.set_model_meta(1, "javascript:alert(1)", "")
    server.set_model_meta(1, "https://makerworld.com/x", "CC BY-NC")
    assert server.candidates()[0]["model"]["license_note"] == "CC BY-NC"
    assert server.candidates()[0]["steps"]["model"] == "pending"  # só o arquivo conclui a etapa


def test_fatiar_fluxo_completo(tmp_path, monkeypatch):
    import pytest
    if not server.fatiar.ORCA.exists():
        pytest.skip("OrcaSlicer portátil não instalado")
    _produto(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "ROOT", tmp_path)  # depois do init(), que lê o schema da raiz real
    server.run_slice(1)  # sem modelo ainda
    assert server.candidates()[0]["steps"]["slice"] == "error" and "modelo" in server.candidates()[0]["slice_msg"]
    v = [(x, y, z) for z in (0, 20) for y in (0, 20) for x in (0, 20)]
    f = [(0,2,3),(0,3,1),(4,5,7),(4,7,6),(0,1,5),(0,5,4),(2,6,7),(2,7,3),(0,4,6),(0,6,2),(1,3,7),(1,7,5)]
    stl = "solid c\n" + "".join("facet normal 0 0 0\nouter loop\n" + "".join("vertex %d %d %d\n" % v[i] for i in t) + "endloop\nendfacet\n" for t in f) + "endsolid c\n"
    server.set_model(1, "cubo.stl", stl.encode())
    server.run_slice(1)
    cand = server.candidates()[0]
    assert cand["steps"]["slice"] == "ok" and cand["slice"]["minutes"] > 0 and cand["slice"]["grams"] > 0
    server.set_model(1, "outro.stl", stl.encode())  # modelo novo invalida o fatiamento
    assert server.candidates()[0]["slice"] is None and server.candidates()[0]["steps"]["slice"] == "pending"


def test_custo_margem_e_preco_alvo(tmp_path, monkeypatch):
    import pytest
    _produto(tmp_path, monkeypatch)
    assert server.candidates()[0]["margin"] is None  # sem fatiamento não há margem
    with server.db() as c:
        c.execute("INSERT INTO slices(listing_id,minutes,grams) VALUES(1,120,50)")
    assert server.candidates()[0]["margin"] is None  # anúncio sem preço lido e sem preço-alvo
    server.set_price(1, 39)
    cand = server.candidates()[0]
    assert cand["target_price"] == 39 and cand["steps"]["cost"] == "ok"
    assert cand["margin"]["ml"]["taxas"] != cand["margin"]["shopee"]["taxas"]
    for bad in (1, 99999, "abc"):
        with pytest.raises(ValueError):
            server.set_price(1, bad)
    server.set_costs(dict(embalagem_rs=10, confirmado=1, naoexiste=5))
    c2 = server.get_costs()
    assert c2["embalagem_rs"] == 10 and c2["confirmado"] == 1 and "naoexiste" not in c2
    with pytest.raises(ValueError):
        server.set_costs(dict(frete_rs=-1))


def test_texto_fluxo_e_validacao(tmp_path, monkeypatch):
    import pytest
    _produto(tmp_path, monkeypatch)
    server.run_copy(1)  # sem fatiamento
    assert server.candidates()[0]["steps"]["copy"] == "error" and "fatie" in server.candidates()[0]["copy_msg"]
    with server.db() as c:
        c.execute("INSERT INTO slices(listing_id,minutes,grams) VALUES(1,60,10)")
    server.set_price(1, 39)
    monkeypatch.setattr(server.texto, "generate", lambda p: dict(title="Suporte bonito", description="d" * 90, bullets=["a", "b", "c"], scripts=["s"], keywords=["k"]))
    server.run_copy(1)
    cand = server.candidates()[0]
    assert cand["steps"]["copy"] == "ok" and cand["kit"]["title"] == "Suporte bonito" and cand["kit"]["bullets"] == ["a", "b", "c"]
    with pytest.raises(ValueError):
        server.set_kit(1, dict(title="x", description="y" * 50))
    server.set_business(dict(nome="Loja 3D", prazo_dias="4", lixo="x"))
    assert server.get_business()["nome"] == "Loja 3D" and "lixo" not in server.get_business()
    with pytest.raises(ValueError):
        server.set_business(dict(prazo_dias="abc"))


def test_kit_confirmacao_e_zip(tmp_path, monkeypatch):
    import io
    import json as j
    import zipfile
    import pytest
    _produto(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="faltam etapas"):
        server.confirm_kit(1)
    with server.db() as c:
        c.execute("INSERT INTO slices(listing_id,minutes,grams) VALUES(1,60,10)")
        c.execute("UPDATE steps SET status='ok' WHERE listing_id=1 AND name IN ('model','slice','images')")
    server.set_price(1, 39)
    server.set_kit(1, dict(title="Suporte bonito", description="d" * 90, bullets=["a", "b", "c"], scripts=["s1", "s2"], keywords=["k"]))
    (tmp_path / "products" / "1" / "renders").mkdir(parents=True)
    (tmp_path / "products" / "1" / "renders" / "render_1.jpg").write_bytes(b"jpg")
    server.confirm_kit(1)
    cand = server.candidates()[0]
    assert cand["steps"]["kit"] == "ok" and cand["kit"]["confirmed"] == 1
    names = zipfile.ZipFile(io.BytesIO(server.kit_zip(1))).namelist()
    assert {"anuncio.txt", "roteiros.txt", "dados.json", "imagens/render_1.jpg"} <= set(names)
    server.set_kit(1, dict(title="Outro título", description="d" * 90))  # editar o texto desfaz a confirmação
    assert server.candidates()[0]["steps"]["kit"] == "pending" and server.candidates()[0]["kit"]["confirmed"] == 0


def test_shopee_marcacao_manual_do_link(tmp_path, monkeypatch):
    import pytest
    _produto(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        server.mark_shopee(1, "javascript:x")
    assert server.candidates()[0]["publications"] == {}
    server.mark_shopee(1, "https://shopee.com.br/produto-1")
    cand = server.candidates()[0]
    assert cand["steps"]["shopee"] == "ok" and cand["publications"]["shopee"]["url"].startswith("https://shopee")
    assert not hasattr(server, "run_shopee") and not hasattr(server, "shopee_publish")  # sem automação da Shopee


def test_resume_recoloca_lojas_na_fila(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    started = []
    monkeypatch.setattr(server, "run_store", lambda *a: started.append(a))
    server.init()
    with server.db() as c:
        c.execute("INSERT INTO stores(url, status, profile) VALUES('https://x.mercadolivre.com.br/a','running','user1')")
        c.execute("INSERT INTO stores(url, status, profile) VALUES('https://x.mercadolivre.com.br/b','done','user1')")
    server.resume()
    import time; time.sleep(0.2)  # threads daemon
    assert [a[1] for a in started] == ["https://x.mercadolivre.com.br/a"]
    with server.db() as c:
        assert c.execute("SELECT status FROM stores WHERE url LIKE '%/a'").fetchone()[0] == "pending"


def test_post_com_corpo_invalido_responde_400(tmp_path, monkeypatch):
    import http.client
    import threading
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    server.init()
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        for body in (b"\xff\xfe nao-utf8", b"{quebrado"):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
            c.request("POST", "/api/kit", body)
            assert c.getresponse().status == 400
    finally:
        srv.shutdown()


def test_atualizar_dados_da_loja_nao_apaga_o_que_ja_se_sabia(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    server.init()
    with server.db() as c:
        c.execute("INSERT INTO stores(url,name,logo,sales) VALUES('https://www.mercadolivre.com.br/pagina/x','Antigo','https://l/a.jpg',50)")
    monkeypatch.setattr(server, "read_store_info", lambda url, profile, on_captcha=None: dict(name="PEKO 3D", logo="", followers=3400))
    server.run_store_info([1], "user1")
    with server.db() as c:
        s = dict(c.execute("SELECT * FROM stores WHERE id=1").fetchone())
    assert (s["name"], s["logo"], s["sales"], s["followers"]) == ("PEKO 3D", "https://l/a.jpg", 50, 3400) and s["read_at"]


def test_remover_loja_apaga_tudo_menos_se_publicada(tmp_path, monkeypatch):
    import pytest
    _produto(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "IMAGES", tmp_path / "img")
    with server.db() as c:
        c.execute("INSERT INTO publications(listing_id,channel) VALUES(1,'ml')")
    with pytest.raises(ValueError, match="publicado"):
        server.remove_store(1)
    with server.db() as c:
        c.execute("DELETE FROM publications")
    server.remove_store(1)
    with server.db() as c:
        assert [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("stores", "listings", "snapshots", "steps")] == [0, 0, 0, 0]
    with pytest.raises(ValueError):
        server.remove_store(1)


def test_midia_ordem_ocultar_e_fotos_proprias(tmp_path, monkeypatch):
    import io
    import pytest
    from PIL import Image
    _produto(tmp_path, monkeypatch)
    d = tmp_path / "products" / "1" / "renders"
    d.mkdir(parents=True)
    for n in ("render_1.jpg", "render_2.jpg", "render_10.jpg"):
        Image.new("RGB", (10, 10)).save(d / n)
    buf = io.BytesIO()
    Image.new("RGBA", (3000, 100), (255, 0, 0, 128)).save(buf, "PNG")
    assert server.add_photo(1, buf.getvalue()) == "photo_1.jpg"  # PNG vira JPG e cabe em 2400 px
    assert Image.open(d / "photo_1.jpg").size[0] == 2400
    (c,) = server.candidates()
    assert c["steps"]["images"] == "ok" and c["images"] == ["render_1.jpg", "render_2.jpg", "render_10.jpg", "photo_1.jpg"]  # render_10 depois do 2
    server.set_media(1, ["photo_1.jpg", "render_2.jpg"], ["render_1.jpg"])
    assert server.candidates()[0]["images"] == ["photo_1.jpg", "render_2.jpg", "render_10.jpg"]
    assert [m["hidden"] for m in server.candidates()[0]["media"]] == [False, False, True, False]
    for bad in (["../x.jpg"], ["render_1.png"]):
        with pytest.raises(ValueError):
            server.set_media(1, bad, [])
    with pytest.raises(ValueError):
        server.del_photo(1, "render_1.jpg")  # render não se apaga por aqui
    server.del_photo(1, "photo_1.jpg")
    assert not (d / "photo_1.jpg").exists()
    with pytest.raises(ValueError):
        server.add_photo(1, b"isto nao e imagem")


def test_etapas_running_voltam_a_pendente_ao_reiniciar(tmp_path, monkeypatch):
    _produto(tmp_path, monkeypatch)
    with server.db() as c:
        c.execute("UPDATE steps SET status='running' WHERE name IN ('slice','images')")
    server.resume()
    assert server.candidates()[0]["steps"]["slice"] == "pending" and server.candidates()[0]["steps"]["images"] == "pending"


def test_so_loja_do_mercado_livre_de_verdade():
    p = server.platform_of
    assert p("https://www.mercadolivre.com.br/pagina/x") == "ml" and p("https://lista.mercadolivre.com.br/_CustId_1") == "ml"
    for bad in ("https://shopee.com.br/loja_x", "http://www.mercadolivre.com.br/x", "https://evil.com/?u=mercadolivre.com.br",
                "https://mercadolivre.com.br.evil.com/x"):
        assert p(bad) is None
