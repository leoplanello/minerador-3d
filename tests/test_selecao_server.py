import json
import struct
import sys
import threading
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
