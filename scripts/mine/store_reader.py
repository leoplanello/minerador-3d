"""Lê uma loja do Mercado Livre e grava listings + snapshots. Um anúncio por vez, ritmo lento."""
import os
import random
import sys
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from playwright.sync_api import sync_playwright

from classify import is_3d, parse_material, parse_price, parse_reviews, parse_sold, parse_store_info

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))  # paths.py mora em scripts/app
import proc  # noqa: E402
from paths import DATA  # noqa: E402

PROFILES_DIR = DATA / "db" / "profiles"
DEBUG_DIR = DATA / "db" / "debug"
LINK_RE = re.compile(r"https://(?:produto|www)\.mercadolivre\.com\.br/[^\s?#]*(?:MLBU?-?\d+|/p/MLB\d+)[^\s?#]*")
CAPTCHA_HINTS = ("captcha", "account-verification", "negative_traffic", "/login", "registration", "/account/signin")  # login conta como ação manual
CAPTCHA_TEXTS = ("não sou um robô", "por segurança, complete esta etapa")


def launch_ctx(p, profile, headless=False, **kw):
    """Chrome do perfil salvo para o Playwright. Sem a marca de automação, que faz o Google e o Cloudflare recusarem o login."""
    return p.chromium.launch_persistent_context(str(PROFILES_DIR / profile), channel="chrome", headless=headless,
                                                ignore_default_args=["--enable-automation"], args=["--disable-blink-features=AutomationControlled"], **kw)


def front(ctx, headless):
    """Com a janela visível, traz o Chrome do app para a frente, para a pessoa acompanhar."""
    if not headless:
        try:
            (ctx.pages[0] if ctx.pages else ctx.new_page()).bring_to_front()
        except Exception:
            pass


def chrome_path():
    for c in (os.environ.get("CHROME_PATH"), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")):
        if c and os.path.isfile(c):
            return c
    raise ValueError("não achei o Google Chrome instalado; defina CHROME_PATH")


LOGIN_HOSTS = ("mercadolivre.com.br", "mercadolibre.com", "makerworld.com", "printables.com", "thingiverse.com", "accounts.google.com")


def open_for_login(profile, url):
    """Abre o Chrome normal (sem automação) no perfil salvo para você entrar nas contas, inclusive com Google. Feche a janela quando terminar:
    o app só consegue usar o perfil com o Chrome dele fechado."""
    if profile not in list_profiles():
        raise ValueError(f"perfil desconhecido: {profile}")
    u = urlparse(url)
    if u.scheme != "https" or not any((u.hostname or "") == h or (u.hostname or "").endswith("." + h) for h in LOGIN_HOSTS):
        raise ValueError("só abro sites de Mercado Livre, MakerWorld, Printables e Thingiverse")
    proc.popen([chrome_path(), f"--user-data-dir={PROFILES_DIR / profile}", "--no-first-run", "--no-default-browser-check", url], show=True)


def extract_links(hrefs):
    """Links de produto únicos, na ordem; decodifica redirecionamentos click1...?urldest=<url>."""
    seen = []
    for h in hrefs:
        h = unquote(parse_qs(urlparse(h).query)["urldest"][0]) if "urldest=" in h else h
        m = LINK_RE.match(h)
        if m and m.group(0) not in seen:
            seen.append(m.group(0))
    return seen


def _captcha(page):
    head = page.inner_text("body")[:2000].lower()
    return any(h in page.url for h in CAPTCHA_HINTS) or any(t in head for t in CAPTCHA_TEXTS)


def _wait_human(page, on_captcha):
    """Pausa até o usuário resolver o captcha na janela aberta (máx. 10 min)."""
    on_captcha(True, "login" if "/login" in page.url or "registration" in page.url else "captcha")
    for _ in range(300):
        if not _captcha(page):
            on_captcha(False)
            return
        time.sleep(2)
    raise TimeoutError("captcha não resolvido em 10 min")


def _goto(page, url, on_captcha):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    if _captcha(page):
        _wait_human(page, on_captcha)
    time.sleep(random.uniform(2, 5))


def clean_title(title):
    """'(9+) PEKO 3D | Página do vendedor' -> 'PEKO 3D' (o ML põe o contador de notificações na frente do título)."""
    return re.sub(r"^\(\d+\+?\)\s*", "", title.split(" | ")[0]).strip()


def seller_block(page, wait_ms=0):
    """Nome e logo do vendedor. Página da loja e do anúncio: .ui-ms-profile__full_name e a imagem da bolha da loja.
    Página lista.mercadolivre.com.br/_CustId_...: só o título 'Anúncios de <nome>' em h1.ui-search-breadcrumb__title, sem logo.
    O bloco é desenhado depois do carregamento, por isso wait_ms espera por ele."""
    if wait_ms:
        try:
            page.wait_for_selector(".ui-ms-profile__full_name, h1.ui-search-breadcrumb__title", timeout=wait_ms)
        except Exception:
            pass

    def one(sel, attr=None):
        loc = page.locator(sel)
        if not loc.count():
            return ""
        return ((loc.first.get_attribute(attr) if attr else loc.first.inner_text()) or "").strip()
    lista = re.match(r"An[úu]ncios de\s+(.+)", one("h1.ui-search-breadcrumb__title"), re.I)
    return dict(name=one(".ui-ms-profile__full_name") or (lista.group(1).strip() if lista else ""), logo=one("img.ui-bubble-store__logo", "src"))


def list_profiles():
    return sorted(d.name for d in PROFILES_DIR.iterdir() if d.is_dir()) if PROFILES_DIR.exists() else []


def read_store(url, profile, limit=20, on_captcha=lambda paused, kind="captcha": None, on_listing=lambda d: None, on_store=lambda d: None, headless=False):
    """on_listing recebe dict(url,title,price,material,is_3d,sold,reviews,rank) por anúncio lido."""
    if profile not in list_profiles():  # também barra '../' vindo da API
        raise ValueError(f"perfil desconhecido: {profile}")
    with sync_playwright() as p:
        ctx = launch_ctx(p, profile, headless=headless)
        front(ctx, headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _goto(page, url, on_captcha)
            seller = seller_block(page, 6000)
            store_name = seller["name"] or clean_title(page.title())
            sem_logo = urlparse(url).hostname == "lista.mercadolivre.com.br"  # essa página não tem logo; não adianta procurar nos anúncios
            on_store(parse_store_info(page.inner_text("body")) | {k: v for k, v in seller.items() if v})
            page.mouse.wheel(0, 4000)  # anúncios podem carregar só após rolar
            time.sleep(2)
            seen = extract_links(page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)"))
            for rank, link in enumerate(seen[:limit], 1):
                _goto(page, link, on_captcha)
                if not sem_logo and not (seller.get("name") and seller.get("logo")):  # a página da loja nem sempre traz o bloco; o anúncio traz
                    seller = {k: seller.get(k) or v for k, v in seller_block(page, 6000).items()}
                    on_store({k: v for k, v in seller.items() if v})
                text = page.inner_text("body")[:20000]
                title = (page.locator("h1").first.inner_text() if page.locator("h1").count() else "").strip()
                DEBUG_DIR.mkdir(exist_ok=True)  # texto cru para ajustar os parsers
                (DEBUG_DIR / f"{rank:02d}.txt").write_text(text, encoding="utf-8")
                og = page.locator("meta[property='og:image']")
                thumb = og.first.get_attribute("content") if og.count() else ""
                material = parse_material(text)
                on_listing(dict(url=link, title=title, thumb=thumb, store_name=store_name, price=parse_price(text), material=material,
                                is_3d=is_3d(material, text), sold=parse_sold(text),
                                reviews=parse_reviews(text), rank=rank))
        finally:
            ctx.close()


def read_store_info(url, profile, on_captcha=lambda paused, kind="captcha": None, headless=False):
    """Lê só a página da loja (nome, logo, reputação, vendas...), sem abrir anúncio. Devolve um dict só com o que achou."""
    if profile not in list_profiles():
        raise ValueError(f"perfil desconhecido: {profile}")
    with sync_playwright() as p:
        ctx = launch_ctx(p, profile, headless=headless)
        front(ctx, headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _goto(page, url, on_captcha)
            seller = seller_block(page, 8000)
            info = parse_store_info(page.inner_text("body")) | {k: v for k, v in seller.items() if v}
            if not info.get("name"):
                info["name"] = clean_title(page.title())
            return info
        finally:
            ctx.close()
