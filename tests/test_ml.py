import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import ml
import server

CAND = dict(kit=dict(title="Suporte de headset"), target_price=39.0)


def test_build_item_formato_da_api():
    it = ml.build_item(CAND, "MLB123", {"BRAND": "Genérica", "MODEL": " "}, ["P1", "P2"], quantity=5, days="3")
    assert it["title"] == "Suporte de headset" and it["price"] == 39.0 and it["currency_id"] == "BRL" and it["condition"] == "new"
    assert it["pictures"] == [{"id": "P1"}, {"id": "P2"}] and it["attributes"] == [{"id": "BRAND", "value_name": "Genérica"}]  # vazio some
    assert it["sale_terms"] == [{"id": "MANUFACTURING_TIME", "value_name": "3 dias"}] and it["shipping"]["mode"] == "me2"


def test_credenciais_e_codigo(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "SECRETS", tmp_path / "s.json")
    with pytest.raises(ValueError):
        ml.save_credentials("abc", "x")
    with pytest.raises(ValueError):
        ml.auth_url()
    ml.save_credentials("1234567890", "AbCdEfGhIjKlMnOp")
    assert ml.status() == dict(configured=True, connected=False, user_id=None)
    assert "client_id=1234567890" in ml.auth_url() and "redirect_uri=http%3A%2F%2Flocalhost%3A8765" in ml.auth_url()
    sent = {}
    monkeypatch.setattr(ml, "_token", lambda form: sent.update(form))
    ml.exchange_code("http://localhost:8765/api/ml/callback?code=TG-abc-123&state=x")
    assert sent["code"] == "TG-abc-123"
    ml.exchange_code("TG-xyz-9")
    assert sent["code"] == "TG-xyz-9"
    with pytest.raises(ValueError):
        ml.exchange_code("lixo")
    with pytest.raises(ValueError, match="conecte"):
        ml.call("GET", "/users/me")


def test_publicar_exige_kit_confirmado_e_grava(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    monkeypatch.setattr(server, "PRODUCTS", tmp_path / "products")
    server.init()
    with server.db() as c:
        c.execute("INSERT INTO stores(url) VALUES('u')")
        c.execute("INSERT INTO listings(store_id,url,title,price,is_3d,status) VALUES(1,'l','t',39,1,'approved')")
        c.execute("INSERT INTO snapshots(listing_id,sold,reviews,rank) VALUES(1,10,5,1)")
        c.executemany("INSERT OR IGNORE INTO steps(listing_id,name) VALUES(1,?)", [(s,) for s in server.STEPS])
    server.set_kit(1, dict(title="Suporte bonito", description="d" * 90, bullets=["a", "b", "c"], scripts=["s"], keywords=["k"]))
    with pytest.raises(ValueError, match="confirme o kit"):
        server.ml_publish(1, "MLB123", {"BRAND": "X"}, 5)
    with server.db() as c:
        c.execute("UPDATE steps SET status='ok' WHERE name='kit'")
    with pytest.raises(ValueError, match="categoria"):
        server.ml_publish(1, "../x", {}, 5)
    got = {}
    monkeypatch.setattr(server.ml, "publish", lambda item, desc, files: got.update(item=item, desc=desc) or ("MLB999", "https://produto.mercadolivre.com.br/MLB-999"))
    assert server.ml_publish(1, "MLB123", {"BRAND": "X"}, 5)[0] == "MLB999"
    assert got["item"]["category_id"] == "MLB123" and "- a" in got["desc"]
    cand = server.candidates()[0]
    assert cand["publications"]["ml"]["external_id"] == "MLB999" and cand["steps"]["ml"] == "ok"
