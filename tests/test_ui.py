"""GUI no Chrome real: sem rolagem lateral em larguras comuns e preços com vírgula nos centavos."""
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import server

playwright = pytest.importorskip("playwright.sync_api")


TOURS = ("resumo", "lojas", "produtos", "produto", "config")


@pytest.fixture()
def gui(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    monkeypatch.setattr(server, "PRODUCTS", tmp_path / "products")
    server.init()
    server.set_onboarding(dict(done=True, tours={k: True for k in TOURS}))  # assistente e tour por cima da tela atrapalhariam os outros testes
    long = "Suporte articulado para celular e tablet impresso sob encomenda em PLA com base reforçada " * 2
    with server.db() as c:
        c.execute("INSERT INTO stores(url,name,profile,reputation,sales,rating,followers,location) VALUES"
                  "('https://www.mercadolivre.com.br/pagina/loja_com_nome_bem_comprido_para_testar_o_layout','Loja Com Nome Bem Comprido Para Testar','user1','MercadoLíder Platinum',12000,4.8,3400,'Campinas, SP')")
        for i, (st, price) in enumerate([("new", 39.9), ("approved", 1234.5), ("discarded", 20.0)], 1):
            c.execute("INSERT INTO listings(store_id,url,title,price,material,is_3d,status) VALUES(1,?,?,?,?,1,?)",
                      (f"https://produto.mercadolivre.com.br/MLB-{i}", long + str(i), price, "PLA", st))
            c.execute("INSERT INTO snapshots(listing_id,sold,reviews,rank) VALUES(?,?,?,?)", (i, 100 * i, 10 * i, i))
        c.executemany("INSERT INTO steps(listing_id,name) VALUES(2,?)", [(s,) for s in server.STEPS])
        c.execute("INSERT INTO slices(listing_id,minutes,grams) VALUES(2,120,40)")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.mark.parametrize("width", [1000, 1280, 1920])
def test_sem_rolagem_lateral(gui, width):
    with playwright.sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": width, "height": 800})
        for route in ["resumo", "lojas", "produtos", "producao", "producao/2", "config", "ajuda"]:
            page.goto(f"{gui}/#/{route}")
            page.wait_for_timeout(700)
            assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), f"{route} a {width}px"
        page.goto(f"{gui}/#/produtos")
        page.click("[data-layout=grid]")
        page.click("[data-view=all]")
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), f"grade a {width}px"
        b.close()


def test_precos_com_virgula_e_sem_3d(gui):
    with playwright.sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{gui}/#/produtos")
        page.click("[data-view=all]")
        page.wait_for_selector(".item")
        text = page.inner_text("#plist")
        assert "R$ 39,90" in text.replace("\n", "") or "R$39,90" in text.replace("\n", "").replace(" ", "")
        assert "1.234,50" in text.replace("\n", "")
        body = page.inner_text("body")
        assert "impressos em 3D" not in body and "1ª leitura" not in body and "só impressão 3D" not in body
        assert page.locator("th").count() == 0
        page.goto(f"{gui}/#/lojas")
        page.wait_for_selector(".scard")
        store = page.inner_text(".scard")
        assert "MercadoLíder Platinum" in store and "12.000" in store and "4,8 de 5" in store and "não informado" not in store and "seguidores" in store.lower()
        b.close()


def _espera(page, cond, tentativas=60):
    """A tela grava no servidor depois de mudar; espera a condição ficar verdadeira em vez de olhar no mesmo instante."""
    for _ in range(tentativas):
        if cond():
            return True
        page.wait_for_timeout(100)
    return cond()


def _arrastar(page, origem, destino, dx=400, dy=60, embaixo=False):
    """Arrasto em passos: o Chrome só começa o dragover depois de vários movimentos do mouse."""
    o = page.locator(origem).bounding_box()
    d = page.locator(destino).bounding_box()
    page.mouse.move(o["x"] + o["width"] / 2, o["y"] + o["height"] / 2)
    page.mouse.down()
    page.mouse.move(o["x"] + 30, o["y"] + 30, steps=5)
    dy = d["height"] - 12 if embaixo else dy  # em lista vertical, soltar na metade de baixo põe depois do alvo
    page.mouse.move(d["x"] + dx, d["y"] + dy, steps=15)
    page.mouse.move(d["x"] + dx + 2, d["y"] + dy + 2, steps=3)
    page.mouse.up()


def test_remover_loja_pede_segundo_clique(gui):
    with playwright.sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{gui}/#/lojas")
        page.wait_for_selector(".scard")
        page.click("[data-remove]")
        assert "de novo" in page.inner_text("[data-remove]")
        assert page.locator(".scard").count() == 1  # um clique só não remove
        page.click("[data-remove]")
        page.wait_for_selector(".scard", state="detached")
        with server.db() as c:
            assert c.execute("SELECT COUNT(*) FROM stores").fetchone()[0] == 0 and c.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0
        b.close()


def test_arrastar_cards_guarda_ordem(gui):
    with server.db() as c:
        c.execute("INSERT INTO stores(url,name) VALUES('https://www.mercadolivre.com.br/pagina/segunda','Segunda Loja')")
    with playwright.sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{gui}/#/lojas")
        page.wait_for_selector(".scard >> nth=1")
        keys = lambda: page.eval_on_selector_all(".scard", "els => els.map(e => e.dataset.key)")
        assert keys() == ["2", "1"]  # a loja mais nova vem primeiro
        page.locator(".scard >> nth=0").hover()
        _arrastar(page, ".scard >> nth=0 >> .grip", ".scard >> nth=1")
        assert keys() == ["1", "2"]
        page.wait_for_timeout(3500)  # o redesenho periódico não pode desfazer a ordem
        assert keys() == ["1", "2"]
        page.reload()
        page.wait_for_selector(".scard >> nth=1")
        assert keys() == ["1", "2"]
        # cartões da tela inteira também se movem
        page.set_viewport_size({"width": 1280, "height": 1500})  # o cartão das lojas fica alto: o alvo do arrasto precisa caber na janela
        page.wait_for_timeout(500)
        _arrastar(page, "#view > .card >> nth=0 >> .grip", "#view > .card >> nth=1", dx=300, embaixo=True)
        assert page.eval_on_selector_all("#view > .card", "els => els.map(e => e.querySelector('h2').textContent)")[0] == "Lojas"
        b.close()


def test_producao_busca_modelo_imagens_e_configuracao(gui):
    from PIL import Image
    d = server.PRODUCTS / "2" / "renders"
    d.mkdir(parents=True)
    for n in ("render_1.jpg", "render_2.jpg"):
        Image.new("RGB", (60, 60), (200, 200, 200)).save(d / n)
    with server.db() as c:
        c.execute("UPDATE steps SET status='ok' WHERE listing_id=2 AND name='images'")
    with playwright.sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1000, "height": 900})
        page.goto(f"{gui}/#/producao/2")
        page.wait_for_selector("#igal .gi >> nth=1")
        assert "Passo 1" in page.inner_text(".next")  # sem modelo, o passo é achar o modelo
        assert page.input_value("#msq").startswith("Suporte articulado")
        assert page.input_value("[data-i=finish]") == "matte" and page.locator("[data-iview]:checked").count() == 5
        assert page.input_value("[data-v=format]") == "9:16"
        page.click("#igal [data-g=right] >> nth=0")  # primeira imagem vai para depois
        page.wait_for_function("document.querySelector('#igal img').alt === 'render_2.jpg'")
        page.click("#igal [data-g=hide] >> nth=0")
        page.wait_for_selector("#igal .gi.off")
        assert next(c for c in server.candidates() if c["id"] == 2)["images"] == ["render_1.jpg"]  # render_2 ficou oculto
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        b.close()


def test_resumo_funil_simulacao_e_navegacao(gui):
    with playwright.sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1000, "height": 900})
        page.goto(f"{gui}/")  # sem rota: abre no Resumo
        page.wait_for_selector("#rfunil .tile")
        assert page.get_attribute("[data-nav=resumo]", "aria-current") == "page"
        tiles = page.inner_text("#rfunil").replace("\n", " ")
        assert "Lojas lidas" in tiles and "Em produção" in tiles
        page.wait_for_selector("#simres .tile")
        antes = page.inner_text("#simres .tile >> nth=1")  # lucro esperado com 10 vendas
        page.fill("[data-sn]", "40")
        page.wait_for_function("document.querySelector('#simres .tile:nth-child(2) b').innerText !== %r" % antes.split("\n")[0])
        assert "R$" in page.inner_text("#simres") and "Esperado" in page.inner_text("#simres")
        page.select_option("#simch", "shopee")
        page.wait_for_timeout(600)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        assert "Produtos, mídias e custos" in page.inner_text("#c-prod h2") and page.locator("#rprod .rp").count() == 1
        b.close()


def test_onboarding_primeira_abertura_e_tour(gui, tmp_path):
    server.set_onboarding(dict(done=False, step=0, tours={k: False for k in TOURS}))
    with playwright.sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1000, "height": 800})
        page.goto(f"{gui}/#/resumo")
        page.wait_for_selector("#ob .ob-card")
        assert "Passo 1 de 8" in page.inner_text("#ob") and "Bem-vindo" in page.inner_text("#ob h2")
        page.wait_for_timeout(1400)
        assert page.locator("#tour-tip").count() == 0  # o tour não abre por cima do assistente
        page.click("[data-obnext]")
        assert "Ferramentas" in page.inner_text("#ob h2") and "Bambu Studio" in page.inner_text("#ob")
        page.click("[data-obnext]")  # contas
        page.click("[data-obnext]")  # custos
        page.wait_for_selector("[data-oc=filamento_rs_kg]")
        page.fill("[data-oc=filamento_rs_kg]", "99,5".replace(",", "."))
        page.check("#obconf")
        page.click("[data-obnext]")
        page.wait_for_selector("[data-ob=nome]")  # o passo só avança depois de gravar os custos
        assert server.get_costs()["filamento_rs_kg"] == 99.5 and server.get_costs()["confirmado"] == 1
        page.fill("[data-ob=nome]", "Minha Loja 3D")
        page.click("[data-obnext]")
        page.wait_for_function("document.querySelector('#ob h2').innerText.includes('Mercado Livre')")
        assert server.get_business()["nome"] == "Minha Loja 3D"
        page.click("[data-obback]")  # voltar não perde o passo
        assert "Dados da sua loja" in page.inner_text("#ob h2")
        page.click("[data-obskip]")
        page.wait_for_selector("#ob", state="hidden")
        assert _espera(page, lambda: server.get_onboarding()["done"] is True)
        page.reload()
        page.wait_for_timeout(2000)
        assert page.locator("#ob .ob-card:visible").count() == 0  # concluído: não volta a abrir
        # tour da tela: balão sobre o elemento, avança e conclui
        page.goto(f"{gui}/#/lojas")
        page.wait_for_selector("#tour-tip", timeout=6000)
        assert "Adicione lojas" in page.inner_text("#tour-tip")
        page.click("[data-tournext]")
        page.click("[data-tournext]")
        page.click("[data-tournext]")
        page.wait_for_selector("#tour-tip", state="detached")
        assert _espera(page, lambda: server.get_onboarding()["tours"].get("lojas") is True)
        # na Ajuda dá para refazer o assistente
        page.goto(f"{gui}/#/ajuda")
        page.click("[data-onb='0']")
        page.wait_for_selector("#ob .ob-card")
        assert "Passo 1 de 8" in page.inner_text("#ob")
        b.close()


def test_linha_do_tempo_e_atividade_do_produto(gui):
    with server.db() as c:
        c.execute("UPDATE steps SET status='running' WHERE listing_id=2 AND name='images'")
    with playwright.sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1000, "height": 900})
        page.goto(f"{gui}/#/producao/2")
        page.wait_for_selector("#tline li")
        assert page.locator("#tline li").count() == len(server.STEPS)
        assert "em andamento" in page.inner_text("#tline li.running")
        assert "Trabalhando" in page.inner_text("#status")  # a barra do topo mostra o que o app está fazendo
        b.close()
