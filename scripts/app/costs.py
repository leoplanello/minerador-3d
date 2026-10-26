"""Custo, taxas e margem de um produto. Valores PROVISÓRIOS até o usuário confirmar na tela Configurações."""

DEFAULTS = {
    "potencia_kw": 0.12,        # A1 imprimindo, média
    "energia_rs_kwh": 0.95,     # tarifa residencial de Campinas (estimativa)
    "maquina_rs_h": 1.50,       # desgaste e depreciação da impressora
    "filamento_rs_kg": 120.0,   # reposição
    "embalagem_rs": 2.50,
    "frete_rs": 8.0,            # frete grátis pago pelo vendedor, média
    "garantia_pct": 5.0,        # reimpressão, % do custo de produção
    "imposto_pct": 0.0,         # CPF por enquanto; MEI depois
    "ml_pct": 14.0,             # comissão ML clássico, varia por categoria
    "shopee_pct": 20.0, "shopee_fixa_rs": 4.0,
    "margem_alvo_pct": 40.0,
    "confirmado": 0,
}
LABELS = {
    "potencia_kw": "Potência média da impressora (kW)", "energia_rs_kwh": "Energia (R$/kWh)", "maquina_rs_h": "Desgaste da máquina (R$/hora)",
    "filamento_rs_kg": "Filamento (R$/kg)", "embalagem_rs": "Embalagem por peça (R$)", "frete_rs": "Frete pago pelo vendedor (R$)",
    "garantia_pct": "Garantia de reimpressão (% do custo de produção)", "imposto_pct": "Imposto (%)", "ml_pct": "Comissão do Mercado Livre (%)",
    "shopee_pct": "Comissão da Shopee (%)", "shopee_fixa_rs": "Taxa fixa da Shopee (R$)", "margem_alvo_pct": "Margem alvo (%)",
}


def ml_fixa(price):
    """Taxa fixa do ML para itens abaixo de R$ 79. shortcut: tabela de memória, conferir no ML antes de confiar."""
    if price >= 79:
        return 0.0
    return price * 0.5 if price < 12.5 else 6.25 if price < 29 else 6.5 if price < 50 else 6.75


def calc(c, minutes, grams, price, channel="ml"):
    horas = minutes / 60
    producao = grams / 1000 * c["filamento_rs_kg"] + horas * c["maquina_rs_h"] + horas * c["potencia_kw"] * c["energia_rs_kwh"]
    garantia = producao * c["garantia_pct"] / 100
    fixo = producao + garantia + c["embalagem_rs"] + c["frete_rs"]

    def lucro(p):
        pct, fixa = (c["ml_pct"], ml_fixa(p)) if channel == "ml" else (c["shopee_pct"], c["shopee_fixa_rs"])
        return p - fixo - p * (pct + c["imposto_pct"]) / 100 - fixa

    minimo = next((p / 10 for p in range(10, 10000) if lucro(p / 10) / (p / 10) * 100 >= c["margem_alvo_pct"]), None)
    l = lucro(price)
    return dict(producao=round(producao, 2), garantia=round(garantia, 2), embalagem=c["embalagem_rs"], frete=c["frete_rs"],
                taxas=round(price - fixo - l, 2), custo_total=round(fixo, 2), lucro=round(l, 2),
                margem_pct=round(l / price * 100, 1) if price else 0.0, preco_minimo=minimo)


def simulate(c, items, channel="ml", fixed_month=0.0):
    """Simulação mensal. items: [{id, minutes, grams, price, units}]. Devolve linhas por produto, totais e três cenários
    (vendas em 0,5x, 1x e 1,5x do informado). O lucro é linear nas vendas; o custo fixo mensal entra uma vez."""
    rows = []
    for it in items:
        m = calc(c, it["minutes"], it["grams"], it["price"], channel)
        u = it["units"]
        rows.append(dict(id=it["id"], price=it["price"], units=u, custo_peca=m["custo_total"], taxas_peca=m["taxas"], lucro_peca=m["lucro"], margem_pct=m["margem_pct"],
                         receita_mes=round(it["price"] * u, 2), lucro_mes=round(m["lucro"] * u, 2), horas_mes=round(it["minutes"] / 60 * u, 1), gramas_mes=round(it["grams"] * u, 1)))
    lucro_bruto = sum(r["lucro_mes"] for r in rows)
    units = sum(r["units"] for r in rows)
    medio = lucro_bruto / units if units else 0
    return dict(rows=rows, receita=round(sum(r["receita_mes"] for r in rows), 2), lucro_bruto=round(lucro_bruto, 2), horas=round(sum(r["horas_mes"] for r in rows), 1),
                gramas=round(sum(r["gramas_mes"] for r in rows), 1), unidades=units, custo_fixo=fixed_month,
                cenarios={k: round(lucro_bruto * m - fixed_month, 2) for k, m in (("pessimista", 0.5), ("esperado", 1.0), ("otimista", 1.5))},
                equilibrio_unidades=int(-(-fixed_month // medio)) if medio > 0 and fixed_month > 0 else (0 if fixed_month <= 0 else None))
