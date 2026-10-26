import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import costs
import server

C = costs.DEFAULTS


def test_simulacao_lucro_linear_cenarios_e_equilibrio():
    one = costs.calc(C, 120, 50, 40.0, "ml")
    sim = costs.simulate(C, [dict(id=1, minutes=120, grams=50, price=40.0, units=10), dict(id=2, minutes=60, grams=20, price=30.0, units=5)], "ml", fixed_month=100)
    r1 = sim["rows"][0]
    assert r1["lucro_mes"] == round(one["lucro"] * 10, 2) and r1["receita_mes"] == 400.0 and r1["horas_mes"] == 20.0 and r1["gramas_mes"] == 500.0
    assert sim["unidades"] == 15 and sim["receita"] == 550.0 and sim["horas"] == 25.0
    bruto = sim["lucro_bruto"]
    assert sim["cenarios"] == dict(pessimista=round(bruto * 0.5 - 100, 2), esperado=round(bruto - 100, 2), otimista=round(bruto * 1.5 - 100, 2))
    medio = bruto / 15
    assert sim["equilibrio_unidades"] == -(-100 // medio) and sim["equilibrio_unidades"] * medio >= 100
    assert costs.simulate(C, [], "ml", 0)["equilibrio_unidades"] == 0
    assert costs.simulate(C, [dict(id=1, minutes=600, grams=500, price=10.0, units=5)], "ml", 50)["equilibrio_unidades"] is None  # prejuízo por peça: nunca empata


def _loja(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    monkeypatch.setattr(server, "PRODUCTS", tmp_path / "products")
    server.init()
    with server.db() as c:
        c.execute("INSERT INTO stores(url,name) VALUES('https://www.mercadolivre.com.br/pagina/x','Loja X')")
        for i, st in enumerate(("approved", "approved", "new"), 1):
            c.execute("INSERT INTO listings(store_id,url,title,price,status,is_3d) VALUES(1,?,?,?,?,1)", (f"u{i}", f"Produto {i}", 30.0 + i, st))
            c.execute("INSERT INTO snapshots(listing_id,sold,reviews,rank) VALUES(?,?,?,?)", (i, 10, 5, i))
        c.executemany("INSERT INTO steps(listing_id,name) VALUES(1,?)", [(s,) for s in server.STEPS])
        c.executemany("INSERT INTO steps(listing_id,name) VALUES(2,?)", [(s,) for s in server.STEPS])
        c.execute("INSERT INTO slices(listing_id,minutes,grams) VALUES(1,90,30)")
        c.execute("INSERT INTO publications(listing_id,channel,url,external_id) VALUES(1,'ml','https://ml/x','MLB1')")
        c.execute("UPDATE steps SET status='ok' WHERE listing_id=1 AND name IN ('model','slice')")


def test_resumo_junta_funil_produtos_e_publicacoes(tmp_path, monkeypatch):
    _loja(tmp_path, monkeypatch)
    monkeypatch.setattr(server.ml, "status", lambda: dict(configured=False, connected=False))
    s = server.summary()
    assert s["funnel"] == dict(stores=1, listings=3, review=1, approved=2, ready=0, published=1, with_video=0)
    p1 = next(p for p in s["products"] if p["id"] == 1)
    assert p1["done"] == 2 and p1["total"] == len(server.STEPS) and p1["slice"]["minutes"] == 90 and p1["margin"]["ml"]["lucro"] is not None
    assert s["published"] == [dict(id=1, title="Produto 1", channel="ml", url="https://ml/x", external_id="MLB1", status="published")]
    assert s["stores"][0]["n"] == 3 and s["ml"] == dict(connected=False, configured=False) and s["costs_confirmed"] is False


def test_simulacao_do_servidor_so_usa_produto_fatiado_e_valida(tmp_path, monkeypatch):
    _loja(tmp_path, monkeypatch)
    sim = server.run_simulation(dict(channel="ml", fixed=0, items=[dict(id=1, units=10), dict(id=2, units=10), dict(id=3, units=10)]))
    assert [r["id"] for r in sim["rows"]] == [1]  # o 2 não foi fatiado e o 3 não está aprovado
    assert sim["rows"][0]["price"] == 31.0 and sim["unidades"] == 10
    for bad in (dict(channel="tiktok"), dict(fixed=-1), dict(items=[dict(id=1, units=-5)]), dict(items=[dict(id=1, units=1, price=1)])):
        with pytest.raises(ValueError):
            server.run_simulation(dict(channel="ml", fixed=0, items=[]) | bad)


def test_onboarding_guarda_passo_e_tour(tmp_path, monkeypatch):
    _loja(tmp_path, monkeypatch)
    assert server.get_onboarding() == dict(done=False, step=0, tours={})
    server.set_onboarding(dict(step=3, tours=dict(lojas=True)))
    server.set_onboarding(dict(tours=dict(produtos=True), done=True))
    assert server.get_onboarding() == dict(done=True, step=3, tours=dict(lojas=True, produtos=True))
    assert server.set_onboarding(dict(step=999))["step"] == 20


def test_tempo_de_cada_etapa_pelo_gatilho(tmp_path, monkeypatch):
    _loja(tmp_path, monkeypatch)
    with server.db() as c:
        c.execute("UPDATE steps SET status='running' WHERE listing_id=1 AND name='images'")
        c.execute("UPDATE steps SET started=datetime('now','-90 seconds') WHERE listing_id=1 AND name='images'")
        c.execute("UPDATE steps SET status='ok' WHERE listing_id=1 AND name='images'")
    t = next(c for c in server.candidates() if c["id"] == 1)["step_times"]
    assert t["images"]["seconds"] in range(89, 93) and t["model"]["seconds"] is None or t["model"]["seconds"] == 0


def test_saude_lista_ferramentas(monkeypatch, tmp_path):
    _loja(tmp_path, monkeypatch)
    h = server.health()
    assert set(h) >= {"orca", "blender", "ffmpeg", "chrome", "claude", "profiles", "ml", "costs_confirmed", "business"}
