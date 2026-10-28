import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
from costs import DEFAULTS, at_competitor, calc, ml_fixa

C = DEFAULTS | dict(potencia_kw=0.1, energia_rs_kwh=1.0, maquina_rs_h=2.0, filamento_rs_kg=100.0, embalagem_rs=2.0, frete_rs=5.0,
                    garantia_pct=10.0, imposto_pct=0.0, ml_pct=10.0, margem_alvo_pct=40.0)


def test_producao_a_mao():
    # 50 g a R$100/kg = 5,00; 2 h × R$2 = 4,00; 2 h × 0,1 kW × R$1 = 0,20 -> 9,20; garantia 10% = 0,92
    r = calc(C, 120, 50, 40.0)
    assert (r["producao"], r["garantia"], r["custo_total"]) == (9.2, 0.92, 17.12)  # + embalagem 2 + frete 5
    # taxas: 10% de 40 = 4,00 + fixa 6,50 = 10,50; lucro = 40 - 17,12 - 10,50 = 12,38 -> 30,95%
    assert (r["taxas"], r["lucro"], r["margem_pct"]) == (10.5, 12.38, 31.0)


def test_preco_minimo_atinge_a_margem_alvo():
    r = calc(C, 120, 50, 40.0)
    p = r["preco_minimo"]
    m = lambda x: calc(C, 120, 50, x)["lucro"] / x * 100  # sem o arredondamento de margem_pct
    assert m(p) >= 40 > m(round(p - 0.1, 1))


def test_taxa_fixa_ml_por_faixa_e_shopee():
    assert [ml_fixa(p) for p in (10, 20, 40, 60, 80)] == [5.0, 6.25, 6.5, 6.75, 0.0]
    shopee = calc(C | dict(shopee_pct=20.0, shopee_fixa_rs=4.0), 120, 50, 40.0, "shopee")
    assert shopee["taxas"] == 12.0  # 20% de 40 + R$4


def test_imposto_perdas_embalagem_e_margem_no_preco_do_concorrente():
    c = DEFAULTS | dict(imposto_pct=6.0, garantia_pct=10.0, embalagem_rs=3.0, frete_rs=0.0, ml_pct=14.0)
    m = calc(c, 60, 50, 40.0, "ml")
    assert m["imposto"] == 2.4 and m["embalagem"] == 3.0 and m["garantia"] == round(m["producao"] * 0.10, 2)
    assert abs(m["producao"] + m["garantia"] + m["embalagem"] + m["frete"] + m["imposto"] + m["taxas"] + m["lucro"] - 40.0) < 0.02  # tudo fecha no preço
    sem = calc(c | dict(imposto_pct=0.0), 60, 50, 40.0, "ml")
    assert round(sem["lucro"] - m["lucro"], 2) == 2.4  # o imposto sai direto do lucro
    comp = at_competitor(c, 60, 50, dict(min=30.0, median=40.0, max=55.0, n=3), "ml")
    assert comp["median"]["lucro"] == m["lucro"] and comp["min"]["margem_pct"] < comp["median"]["margem_pct"] < comp["max"]["margem_pct"]
    assert at_competitor(c, 60, 50, None) is None
