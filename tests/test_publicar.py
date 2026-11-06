"""Cartão 'Pronto para publicar': campos para copiar, kit na ordem certa, abrir arquivos e marcação manual."""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import server


def _produto(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "PRODUCTS", tmp_path / "products")
    def sem_internet(title):
        raise ValueError("sem conexão")
    monkeypatch.setattr(server.ml, "categories", sem_internet)  # sem internet: a categoria fica vazia, sem erro
    server.init()
    with server.db() as c:
        c.execute("INSERT INTO stores(url) VALUES('u')")
        c.execute("INSERT INTO listings(store_id,url,title,price) VALUES(1,'l','Suporte para celular',39)")
        c.execute("INSERT INTO snapshots(listing_id,sold,reviews,rank) VALUES(1,10,5,1)")
        c.executemany("INSERT INTO steps(listing_id,name) VALUES(1,?)", [(s,) for s in server.STEPS])
        c.execute("INSERT INTO models(listing_id,source_url,license_note,file_path) VALUES(1,'https://makerworld.com/m/1','CC-BY','products/1/model/suporte.3mf')")
        c.execute("INSERT INTO slices(listing_id,minutes,grams,file_path) VALUES(1,120,40,'products/1/slice/suporte.gcode.3mf')")
        c.execute("UPDATE steps SET status='ok' WHERE listing_id=1 AND name IN ('model','slice','images')")
    server.set_price(1, 39)
    server.set_kit(1, dict(title="Suporte para celular", description="d" * 90, bullets=["a", "b"], scripts=["s1"], keywords=["suporte"]))
    d = tmp_path / "products" / "1"
    (d / "renders").mkdir(parents=True)
    (d / "renders" / "photo_1.jpg").write_bytes(b"foto")
    (d / "renders" / "render_1.jpg").write_bytes(b"render")
    (d / "model").mkdir()
    (d / "model" / "suporte.3mf").write_bytes(b"3mf")
    (d / "slice").mkdir()
    (d / "slice" / "suporte.gcode.3mf").write_bytes(b"sliced")


def test_pack_traz_campos_preco_minimo_creditos_e_ordem(tmp_path, monkeypatch):
    _produto(tmp_path, monkeypatch)
    p = server.publicar_pack(1)
    assert p["titulo"] == "Suporte para celular" and p["bullets"] == ["a", "b"] and p["palavras_chave"] == ["suporte"]
    assert p["preco"] == 39 and p["preco_minimo"] and p["preco_minimo"] > 0
    assert "CC-BY" in p["creditos"] and "makerworld" in p["creditos"]
    assert p["categorias"] == []  # sem internet, a categoria fica para escolher no cadastro
    assert p["imagens"] == ["01-foto-real-photo_1.jpg", "02-ambiente-3d-render_1.jpg"]
    assert p["tempo_min"] == 120 and p["gramas"] == 40 and p["modelo"] and p["fatia"] and not p["confirmado"]


def test_pack_exige_texto(tmp_path, monkeypatch):
    _produto(tmp_path, monkeypatch)
    with server.db() as c:
        c.execute("DELETE FROM kits")
    with pytest.raises(ValueError, match="texto"):
        server.publicar_pack(1)


def test_pasta_do_kit_com_nomes_ordenados_e_zip_com_video(tmp_path, monkeypatch):
    _produto(tmp_path, monkeypatch)
    (tmp_path / "products" / "1" / "kit").mkdir()
    (tmp_path / "products" / "1" / "kit" / "video.mp4").write_bytes(b"mp4")
    opened = []
    monkeypatch.setattr(server.proc, "popen", lambda args, **kw: opened.append(args))
    server.abrir_arquivo(1, "pasta")
    pasta = tmp_path / "products" / "1" / "publicar"
    assert opened == [["explorer", str(pasta)]]
    assert sorted(f.name for f in pasta.iterdir()) == ["01-foto-real-photo_1.jpg", "02-ambiente-3d-render_1.jpg", "video-anuncio.mp4"]
    names = zipfile.ZipFile(io.BytesIO(server.kit_zip(1))).namelist()
    assert {"imagens/01-foto-real-photo_1.jpg", "video-anuncio.mp4"} <= set(names)


def test_abrir_modelo_e_bambu_so_do_produto(tmp_path, monkeypatch):
    _produto(tmp_path, monkeypatch)
    opened = []
    monkeypatch.setattr(server.proc, "popen", lambda args, **kw: opened.append(args))
    monkeypatch.setattr(server.fatiar, "SLICER", tmp_path / "bambu.exe")
    with pytest.raises(ValueError, match="Bambu"):
        server.abrir_arquivo(1, "bambu")
    (tmp_path / "bambu.exe").write_bytes(b"exe")
    server.abrir_arquivo(1, "modelo")
    server.abrir_arquivo(1, "bambu")
    assert opened[0] == ["explorer", str(tmp_path / "products/1/model/suporte.3mf")]
    assert opened[1][1] == str(tmp_path / "products/1/slice/suporte.gcode.3mf")
    with pytest.raises(ValueError, match="abrir o quê"):
        server.abrir_arquivo(1, "../../etc")


def test_marcacao_manual_do_mercado_livre_com_link(tmp_path, monkeypatch):
    _produto(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="canal"):
        server.mark_publicado(1, "olx", "https://olx.com.br/x")
    with pytest.raises(ValueError, match="https"):
        server.mark_publicado(1, "ml", "javascript:x")
    server.mark_publicado(1, "ml", "https://produto.mercadolivre.com.br/MLB-1")
    cand = server.candidates()[0]
    assert cand["steps"]["ml"] == "ok" and cand["publications"]["ml"]["url"].endswith("MLB-1")
    assert server.publicar_pack(1)["publicado"]["url"].endswith("MLB-1")
    server.mark_shopee(1, "https://shopee.com.br/produto-1")  # o caminho da Shopee continua igual
    assert server.candidates()[0]["steps"]["shopee"] == "ok"
