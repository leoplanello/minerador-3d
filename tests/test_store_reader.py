import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "mine"))
from store_reader import extract_links


def test_extract_links_decodifica_redirect_e_dedup():
    prod = "https://produto.mercadolivre.com.br/MLB-123-vaso-_JM"
    hrefs = [prod + "?x=1", "https://click1.mercadolivre.com.br/c?urldest=https%3A%2F%2Fproduto.mercadolivre.com.br%2FMLB-123-vaso-_JM", "https://outro.com/a"]
    assert extract_links(hrefs) == [prod]


def test_extract_links_aceita_produto_de_usuario_up():
    # formato real da /pagina/ da atacado3d; categorias da mesma página não entram
    up = "https://www.mercadolivre.com.br/saboneteira-de-parede/up/MLBU4900759470"
    hrefs = [up + "?pdp_filters=seller_id%3A1#polycard_client=search-desk",
             "https://lista.mercadolivre.com.br/pagina/atacado3d/lista/saude/_NoIndex_True"]
    assert extract_links(hrefs) == [up]


def test_seller_block_nome_e_logo():
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    from store_reader import seller_block
    html = (Path(__file__).parent / "fixtures" / "vendedor_bloco.html").read_text(encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page()
        page.set_content(html)
        assert seller_block(page) == dict(name="PEKO 3D", logo="https://http2.mlstatic.com/D_NQ_NP_617907-MLA73799752331_012024-F.jpg")
        page.set_content("<p>sem bloco</p>")
        assert seller_block(page) == dict(name="", logo="")
        b.close()


def test_clean_title_tira_contador_e_sufixo():
    from store_reader import clean_title
    assert clean_title("(9+) PEKO 3D | Página do vendedor") == "PEKO 3D"
    assert clean_title("Salva Caixinha | Loja Oficial") == "Salva Caixinha"


def test_seller_block_pagina_lista_so_tem_nome():
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    from store_reader import seller_block
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page()
        page.set_content((Path(__file__).parent / "fixtures" / "lista_cabecalho.html").read_text(encoding="utf-8"))
        assert seller_block(page) == dict(name="RAZA2469", logo="")  # o vendedor de um anúncio da lista (CIA DA LEITURA) não conta
        page.set_content("<h1 class='ui-search-breadcrumb__title'>suporte celular</h1>")  # busca comum, não é página de vendedor
        assert seller_block(page)["name"] == ""
        b.close()


def test_abrir_chrome_para_login_so_em_sites_conhecidos(monkeypatch):
    import pytest
    import store_reader as sr
    chamadas = []
    monkeypatch.setattr(sr.subprocess, "Popen", lambda cmd: chamadas.append(cmd))
    monkeypatch.setattr(sr, "chrome_path", lambda: "chrome.exe")
    monkeypatch.setattr(sr, "list_profiles", lambda: ["user1"])
    sr.open_for_login("user1", "https://www.mercadolivre.com.br/")
    cmd = chamadas[0]
    assert cmd[0] == "chrome.exe" and cmd[1].startswith("--user-data-dir=") and cmd[1].endswith("user1") and "--enable-automation" not in " ".join(cmd)
    for perfil, url in [("user1", "https://evil.com/login"), ("user1", "https://mercadolivre.com.br.evil.com/"), ("user1", "http://www.mercadolivre.com.br/"), ("user1", "https://shopee.com.br/"), ("../x", "https://www.mercadolivre.com.br/")]:
        with pytest.raises(ValueError):
            sr.open_for_login(perfil, url)
    assert len(chamadas) == 1
