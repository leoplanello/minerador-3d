import struct
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import selecao as sel

F = sel.clean_filters({})


def box_stl(path, x, y, z):
    """Caixa x·y·z mm como STL binário (12 triângulos), de (0,0,0) a (x,y,z)."""
    v = [(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
    t = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    body = b"".join(struct.pack("<12fH", 0, 0, 0, *v[a], *v[b], *v[c], 0) for a, b, c in t)
    Path(path).write_bytes(b"\0" * 80 + struct.pack("<I", 12) + body)
    return path


def test_filtros_padrao_e_validacao():
    assert F["printer"] == "Bambu Lab A1 Mini" and sel.printer_of(F) == dict(name="Bambu Lab A1 Mini", x=180, y=180, z=180) and F["max_hours"] == 4 and F["max_colors"] == 1
    f = sel.clean_filters(dict(printers=[dict(name="A1", x=256, y=256, z=256), dict(name="Mini", x=180, y=180, z=180)], printer="A1", stock_colors="Preto, Branca , preto"))
    assert f["stock_colors"] == ["preto", "branco"] and sel.printer_of(f)["x"] == 256
    for ruim in (dict(printers=[]), dict(printer="Outra"), dict(printers=[dict(name="x", x=10, y=180, z=180)], printer="x"), dict(max_hours=0), dict(max_colors=0), dict(max_hours="abc")):
        with pytest.raises(ValueError):
            sel.clean_filters(ruim)


def test_anuncio_colorido_com_montagem_e_cor_fora_do_estoque_sao_reprovados():
    assert sel.listing_checks("Suporte De Parede Preto Para Fone", F) == ([], [])
    r, _ = sel.listing_checks("Organizador Colorido Para Montar Com Parafusos", F)
    assert any("cor" in x for x in r) and any("montagem" in x for x in r)
    f = sel.clean_filters(dict(stock_colors=["preto", "branco"]))
    assert sel.listing_checks("Porta Chaves Azul", f)[0] == ["cor fora do estoque de filamento (azul)"]
    assert sel.listing_checks("Porta Chaves Preto", f)[0] == []
    assert sel.listing_checks("Vaso Azul E Branco", sel.clean_filters(dict(max_colors=2)))[0] == []  # duas cores aceitas
    assert sel.listing_checks("Kit Para Montar", sel.clean_filters(dict(allow_assembly=True)))[0] == []


def test_medidas_da_malha(tmp_path):
    s = sel.mesh_stats(box_stl(tmp_path / "c.stl", 100, 50, 2))
    assert s["dims"] == [100, 50, 2] and s["volume"] == 10000 and s["area"] == 2 * (5000 + 200 + 100)
    assert abs(s["thickness"] - 2 * 10000 / 10600) < 0.01 and s["slender"] > 50  # chapa fina e comprida
    with pytest.raises(ValueError):
        sel.read_triangles(tmp_path / "vazio.stl") if (tmp_path / "vazio.stl").write_bytes(b"\0" * 80 + struct.pack("<I", 5)) else None


def test_modelo_que_nao_cabe_e_tempo_longo_reprovam_e_fragil_so_avisa(tmp_path):
    grande = sel.mesh_stats(box_stl(tmp_path / "g.stl", 300, 140, 115))
    r, w, p = sel.model_checks(grande, 120, False, F)
    assert len(r) == 1 and "não cabe na Bambu Lab A1 Mini" in r[0] and "300 × 140 × 115" in r[0] and p == []
    ok = sel.mesh_stats(box_stl(tmp_path / "o.stl", 60, 60, 60))
    assert sel.model_checks(ok, 241, False, F)[0] == ["imprime em 4 h 01 min, acima do limite de 4 h"]
    fino = sel.mesh_stats(box_stl(tmp_path / "f.stl", 120, 20, 0.8))
    r, w, _ = sel.model_checks(fino, 30, False, F)
    assert r == [] and len(w) == 1 and "fragilidade" in w[0]  # aviso, não bloqueio
    assert sel.model_checks(ok, 30, True, F)[0] == ["precisa de suporte de impressão"]
    assert sel.model_checks(ok, 30, True, sel.clean_filters(dict(allow_support=True)))[0] == []
    assert sel.model_checks(None, None, None, F)[2] == ["medidas do modelo", "tempo de impressão", "teste de suporte"]


def test_avaliacao_unica_para_a_tela(tmp_path):
    ok = sel.mesh_stats(box_stl(tmp_path / "o.stl", 60, 60, 60))
    assert sel.evaluate("Suporte Preto", F)["status"] == "pendente"
    assert sel.evaluate("Suporte Preto", F, ok, 60, False)["status"] == "aprovado"
    ev = sel.evaluate("Suporte Colorido", F, ok, 300, False)
    assert ev["status"] == "reprovado" and len(ev["reasons"]) == 2


def test_vendas_por_dia_pela_idade_do_anuncio():
    hoje = date(2026, 10, 27)
    assert sel.age_days("2026-10-17", hoje) == 10 and sel.age_days("lixo", hoje) is None and sel.age_days("2027-01-01", hoje) is None
    assert sel.sales_per_day(50, "2026-10-17", hoje) == 5.0 and sel.sales_per_day(50, "", hoje) is None and sel.sales_per_day(3, "2026-10-27", hoje) == 3.0
    assert sel.is_champion(1.01, F) and not sel.is_champion(1.0, F) and not sel.is_champion(None, F)
    rows = sel.compare_similar([dict(id=1, title="antigo", sold=1000, created="2024-10-01"), dict(id=2, title="novo", sold=40, created="2026-09-01"), dict(id=3, title="?", sold=5, created="")])
    por_id = {r["id"]: r for r in rows}
    assert por_id[1]["note"] == "se sustenta há muito tempo" and por_id[2]["note"] == "demanda ainda viva" and por_id[3]["per_day"] is None
    assert [r["id"] for r in rows] == [1, 2, 3] and rows[0]["per_day"] > rows[1]["per_day"] > 0  # por vendas/dia, desconhecidos por último


def test_anuncios_parecidos_e_faixa_de_preco():
    c = [dict(id=1, title="Suporte De Parede Para Roteador Modem", sold=100, created="2025-01-01", price=30.0),
         dict(id=2, title="Suporte Parede Roteador Modem Vertical", sold=500, created="2024-01-01", price=25.0),
         dict(id=3, title="Suporte Roteador Modem Ajustavel Parede", sold=20, created="2026-09-01", price=45.0),
         dict(id=4, title="Porta Chaves De Parede", sold=900, created="", price=20.0)]
    sim = sel.similar_rows(c[0], c)
    assert [r["id"] for r in sim] == [1, 2, 3]
    assert sel.price_band(sim, me_id=1) == dict(min=25.0, median=35.0, max=45.0, n=2) and sel.price_band([sim[0]], me_id=1) is None
    assert sel.similarity("Vaso Azul", "Porta Chaves") == 0


def test_tese_proposta_pelo_claude_e_editada_na_tela(tmp_path):
    from PIL import Image
    foto = tmp_path / "f.img"
    Image.new("RGB", (300, 400), (30, 30, 30)).save(foto, format="PNG")
    visto = {}
    resp = '{"dor": "Quem tem roteador na mesa quer liberar espaço — sem furar a parede.", "similares": [{"nome": "Suporte de modem", "busca": "suporte modem parede"}, {"nome": "", "busca": "x"}, {"nome": "Prateleira para roteador"}]}'
    t = sel.propose_thesis("Suporte Roteador", foto, ["Suporte Modem Parede"], ask=lambda prompt, wd: visto.update(p=prompt) or resp)
    assert t["dor"].startswith("Quem tem roteador na mesa quer liberar espaço, sem") and [s["nome"] for s in t["similares"]] == ["Suporte de modem", "Prateleira para roteador"]
    assert t["similares"][1]["busca"] == "Prateleira para roteador" and "Suporte Modem Parede" in visto["p"] and "Suporte Roteador" in visto["p"]
    for ruim in ("sem json", '{"dor": "", "similares": []}', '{"dor": "a"}'):
        with pytest.raises(ValueError):
            sel.parse_thesis(ruim)
    ok = sel.clean_thesis(dict(dor=" liberar a mesa ", faixa_min="25", faixa_max="39,9".replace(",", "."), similares=[dict(nome="a"), dict(nome=" ")]))
    assert ok == dict(dor="liberar a mesa", faixa_min=25.0, faixa_max=39.9, similares=[dict(nome="a", busca="a")])
    assert sel.clean_thesis(dict(dor="x"))["faixa_min"] is None
    for ruim in (dict(faixa_min="40", faixa_max="30"), dict(faixa_min="abc"), dict(faixa_min="-1")):
        with pytest.raises(ValueError):
            sel.clean_thesis(ruim)


def cand(i, titulo, grams=None, dor="", price=30.0, status="new", score=10, similares=()):
    return dict(id=i, title=titulo, grams=grams, price=price, status=status, score=score, tese=dict(dor=dor, similares=[dict(nome=n) for n in similares]) if dor else None)


def test_familias_mesma_dor_peso_parecido_e_variacoes_sugeridas():
    cs = [cand(1, "Suporte Parede Roteador Modem", 30, dor="prender o roteador na parede", similares=["Prateleira para roteador", "Suporte de modem"]),
          cand(2, "Suporte Roteador Modem Vertical", 34),
          cand(3, "Caixa Esconde Fios E Roteador Parede", 200, dor="prender o roteador na parede"),   # mesma dor, mas 6x mais pesado: fica de fora
          cand(4, "Porta Chaves De Parede", 25),
          cand(5, "Porta Chaves Parede Com Prateleira", 28),
          cand(6, "Vaso Geométrico", 90),
          cand(7, "Suporte Parede Roteador Descartado", 30, status="discarded")]
    fam = sel.families(cs)
    assert [f["members"] for f in fam] == [[1, 2], [4, 5]]
    f = fam[0]
    assert f["grams"] == [30, 34] and f["pain"] == "prender o roteador na parede" and f["price"]["n"] == 2
    assert [v["nome"] for v in f["variations"]] == ["Prateleira para roteador"]  # "Suporte de modem" já existe na família (título parecido)
    assert sel.weight_ok(30, None) and not sel.weight_ok(30, 90) and sel.weight_ok(30, 34)


def test_funil_valida_contagens_e_mantem_so_escolhidos():
    ids = set(range(1, 20))
    f, w = sel.clean_funnel(dict(lista=[1, 2, 3, 3], escolhidos=[2, 9], decisoes={"2": "mantem", "1": "sai"}), ids)
    assert f == dict(lista=[1, 2, 3], escolhidos=[2], decisoes={"2": "mantem"}) and len(w) == 2 and "5 a 10" in w[0] and "3 a 5" in w[1]
    f, w = sel.clean_funnel(dict(lista=list(range(1, 8)), escolhidos=[1, 2, 3]), ids)
    assert w == []
    for ruim in (dict(lista=list(range(1, 12))), dict(lista=[99]), dict(lista=list(range(1, 8)), escolhidos=[1, 2, 3, 4, 5, 6])):
        with pytest.raises(ValueError):
            sel.clean_funnel(ruim, ids)


def test_desempenho_depois_de_publicado_sugere_manter_ou_sair():
    pts = lambda *p: [dict(ts=t, sold=s) for t, s in p]
    assert sel.perf_summary(pts(("2026-10-01", 0)), 40, 30)["suggestion"] == "espera"
    assert sel.perf_summary(pts(("2026-10-01", 0), ("2026-10-08", 5)), 40, 30)["suggestion"] == "espera"  # só 7 dias
    ok = sel.perf_summary(pts(("2026-10-01", 0), ("2026-10-21", 10)), 40, 30)
    assert ok["suggestion"] == "mantem" and ok["per_day"] == 0.5 and ok["days"] == 20
    ruim = sel.perf_summary(pts(("2026-10-01", 0), ("2026-10-21", 10)), 12, 30)
    assert ruim["suggestion"] == "sai" and "margem" in ruim["why"]  # vende, mas a margem não paga
    assert sel.perf_summary(pts(("2026-10-01", 3), ("2026-10-21", 3)), 40, 30)["suggestion"] == "sai"  # não vendeu nada


def test_plano_de_fotos_e_amostra():
    p = sel.photo_plan(["render_1.jpg", "render_2.jpg"])
    assert p["real"] == [] and "Sem foto real" in p["warnings"][0] and "renderizada em 3D" in p["warnings"][0] and len(p["rules"]) == 4
    assert all("http" in r for r in p["rules"][:2])  # as regras citam a página oficial
    p = sel.photo_plan(["render_1.jpg", "photo_1.jpg"])
    assert p["real"] == ["photo_1.jpg"] and len(p["warnings"]) == 2 and "capa é um render" in p["warnings"][1]
    assert sel.photo_plan(["photo_1.jpg", "photo_2.jpg", "photo_3.jpg", "render_1.jpg"])["warnings"] == []
    assert sel.clean_sample(dict(impressa=1, l="60", a="40,5".replace(",", "."), p="", notas=" ok "))== dict(impressa=True, notas="ok", l=60.0, a=40.5, p=None)
    for ruim in (dict(l="abc"), dict(l="0"), dict(a="5000")):
        with pytest.raises(ValueError):
            sel.clean_sample(ruim)
