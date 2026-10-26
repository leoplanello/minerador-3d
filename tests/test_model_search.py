import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "mine"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import model_search as ms


def test_licenca_comercial():
    assert ms.commercial_ok("Creative Commons – Attribution – Noncommercial") is False
    assert ms.commercial_ok("Creative Commons Attribution") is True
    assert ms.commercial_ok("GNU General Public License v2.0") is True
    assert ms.commercial_ok("") is None and ms.commercial_ok("Licença própria") is None


def test_busca_printables_monta_resultado(monkeypatch):
    item = dict(id="7", name="Porta chaves", slug="porta-chaves", downloadCount=10, likesCount=2, license=dict(name="CC BY-NC"),
                user=dict(publicUsername="ana"), image=dict(filePath="media/prints/7/a.jpg"))
    monkeypatch.setattr(ms, "_gql", lambda q, v: dict(result=dict(items=[item])))
    (r,) = ms.search_printables("porta chaves")
    assert r["url"] == "https://www.printables.com/model/7-porta-chaves" and r["thumb"] == "https://media.printables.com/media/prints/7/a.jpg"
    assert r["commercial"] is False and r["author"] == "ana" and r["downloads"] == 10


def test_links_de_modelo_unicos_e_com_titulo():
    anchors = [dict(href="https://makerworld.com/pt/models/123-suporte?from=search", alt="Suporte de mesa", img="https://x/a.jpg", text=""),
               dict(href="https://makerworld.com/pt/models/123-suporte", alt="Suporte de mesa", img="", text=""),  # repetido
               dict(href="https://makerworld.com/pt/models/999-sem-titulo", alt="", img="", text=""),  # sem título: ignora
               dict(href="https://makerworld.com/pt/u/fulano", alt="x", img="", text="x"),
               dict(href="https://makerworld.com/pt/models/456-gancho", alt="", img="", text="Gancho de parede\n1,2 mil downloads")]
    got = ms.extract_model_links("makerworld", anchors)
    assert [(g["id"], g["title"], g["url"]) for g in got] == [("123", "Suporte de mesa", "https://makerworld.com/pt/models/123-suporte"),
                                                              ("456", "Gancho de parede", "https://makerworld.com/pt/models/456-gancho")]
    assert [g["id"] for g in ms.extract_model_links("thingiverse", [dict(href="https://www.thingiverse.com/thing:42", alt="Vaso", img="", text="")])] == ["42"]


def test_zip_devolve_o_3mf_preferido():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("leia-me.txt", "oi")
        z.writestr("pasta/grande.stl", b"a" * 500)
        z.writestr("pasta/peca.3mf", b"b" * 50)
    assert ms.unzip_model("modelo.zip", buf.getvalue()) == ("peca.3mf", b"b" * 50)
    assert ms.unzip_model("x.stl", b"dados") == ("x.stl", b"dados")
    vazio = io.BytesIO()
    with zipfile.ZipFile(vazio, "w") as z:
        z.writestr("a.txt", "x")
    with pytest.raises(ValueError):
        ms.unzip_model("v.zip", vazio.getvalue())


def test_download_so_aceita_dominio_do_printables(monkeypatch):
    monkeypatch.setattr(ms, "_gql", lambda q, v: dict(getDownloadLink=dict(output=dict(link="https://evil.example.com/a.stl"))))
    with pytest.raises(ValueError):
        ms.printables_download("1", "2")
    with pytest.raises(ValueError):
        ms.printables_download("1; drop", "2")


def test_servidor_guarda_modelo_e_licenca_do_printables(tmp_path, monkeypatch):
    import server
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    monkeypatch.setattr(server, "PRODUCTS", tmp_path / "products")
    server.init()
    with server.db() as c:
        c.execute("INSERT INTO stores(url) VALUES('u')")
        c.execute("INSERT INTO listings(store_id,url,title) VALUES(1,'l','t')")
        c.execute("INSERT INTO snapshots(listing_id,sold,reviews,rank) VALUES(1,1,1,1)")
        c.executemany("INSERT INTO steps(listing_id,name) VALUES(1,?)", [(s,) for s in server.STEPS])
    monkeypatch.setattr(server.model_search, "printables_download", lambda m, f: ("pecinha.stl", b"solid x"))
    server.get_printables_model(1, "7", "9", "Porta chaves", "https://www.printables.com/model/7-x", "Creative Commons Attribution Noncommercial")
    (cand,) = server.candidates()
    assert cand["steps"]["model"] == "ok" and cand["model"]["source_url"].endswith("7-x")
    assert "NÃO permite uso comercial" in cand["model"]["license_note"]
