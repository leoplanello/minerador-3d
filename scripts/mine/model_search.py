"""Busca modelos 3D nos sites de modelos para o produto escolhido.
Printables tem API pública (sem navegador, com download). MakerWorld e Thingiverse ficam atrás de verificação do Cloudflare:
abrimos o Chrome do perfil salvo, lemos a página de busca e o download é feito por você no próprio site (o app captura o arquivo)."""
import io
import json
import re
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from store_reader import PROFILES_DIR, _captcha, _wait_human, front, list_profiles, launch_ctx

PRINTABLES_API = "https://api.printables.com/graphql/"
PRINTABLES_MEDIA = "https://media.printables.com/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
MODEL_EXT = {".3mf", ".stl"}
MAX_MODEL = 200 * 1024 * 1024
SITES = {  # a ordem é a de preferência (impressora Bambu Lab: MakerWorld primeiro)
    "makerworld": "MakerWorld",
    "printables": "Printables",
    "thingiverse": "Thingiverse",
}
# páginas de busca dos sites que exigem navegador e como reconhecer o link de um modelo nelas
BROWSER_SITES = {
    "makerworld": dict(search="https://makerworld.com/pt/search/models?keyword={q}", link=r"/models/(\d+)"),
    "thingiverse": dict(search="https://www.thingiverse.com/search?q={q}&type=things&sort=popular", link=r"/thing:(\d+)"),
}


def commercial_ok(license_name):
    """True: a licença não proíbe uso comercial; False: proíbe (NC); None: não deu para saber."""
    n = (license_name or "").lower()
    if not n:
        return None
    if "noncommercial" in n or "non-commercial" in n or re.search(r"\bnc\b", n):
        return False
    if any(k in n for k in ("creative commons", "cc by", "cc0", "public domain", "gnu", "mit", "apache", "bsd")):
        return True
    return None


def _gql(query, variables):
    req = urllib.request.Request(PRINTABLES_API, json.dumps({"query": query, "variables": variables}).encode(),
                                 {"Content-Type": "application/json", "User-Agent": UA})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as e:
        raise ValueError(f"o Printables não respondeu: {e}")
    if r.get("errors"):
        raise ValueError("o Printables recusou a consulta: " + str(r["errors"][0].get("message", ""))[:200])
    return r["data"]


def search_printables(q, limit=8):
    d = _gql("""query S($q:String!,$n:Int){ result: searchPrints2(query:$q, limit:$n){ items{ id name slug downloadCount likesCount
        license{ name } user{ publicUsername } image{ filePath } } } }""", {"q": q, "n": limit})
    out = []
    for it in (d["result"] or {}).get("items") or []:
        lic = (it.get("license") or {}).get("name", "")
        out.append(dict(source="printables", id=str(it["id"]), title=it["name"], author=(it.get("user") or {}).get("publicUsername", ""),
                        url=f"https://www.printables.com/model/{it['id']}-{it['slug']}",
                        thumb=PRINTABLES_MEDIA + it["image"]["filePath"] if it.get("image") else "",
                        downloads=it.get("downloadCount"), likes=it.get("likesCount"), license=lic, commercial=commercial_ok(lic)))
    return out


def printables_files(model_id):
    """Arquivos .stl e .3mf do modelo: [{id, name, size, kind}]."""
    if not re.fullmatch(r"\d+", str(model_id)):
        raise ValueError("id de modelo inválido")
    d = _gql("""query P($id:ID!){ print(id:$id){ stls{ id name fileSize } } }""", {"id": str(model_id)})
    files = [dict(id=str(f["id"]), name=f["name"], size=f.get("fileSize"), kind="stl") for f in (d["print"] or {}).get("stls") or []]
    return sorted(files, key=lambda f: -(f["size"] or 0))


def printables_download(model_id, file_id, kind="stl"):
    """Devolve (nome, bytes). O link vem assinado do próprio Printables."""
    if not re.fullmatch(r"\d+", str(model_id)) or not re.fullmatch(r"\d+", str(file_id)) or kind != "stl":
        raise ValueError("pedido de download inválido")
    d = _gql("""mutation D($id:ID!,$m:ID!){ getDownloadLink(id:$id, printId:$m, fileType: stl, source: model_detail){ ok output{ link } } }""",
             {"id": str(file_id), "m": str(model_id)})
    link = ((d["getDownloadLink"] or {}).get("output") or {}).get("link")
    host = urllib.parse.urlparse(link or "").hostname or ""
    if not link or not host.endswith("printables.com"):  # o link vem da API; só aceito o domínio deles
        raise ValueError("o Printables não liberou o download desse arquivo")
    req = urllib.request.Request(link, headers={"User-Agent": UA})
    try:
        data = urllib.request.urlopen(req, timeout=60).read(MAX_MODEL + 1)
    except Exception as e:
        raise ValueError(f"falha no download: {e}")
    if not 0 < len(data) <= MAX_MODEL:
        raise ValueError("arquivo vazio ou maior que 200 MB")
    return Path(urllib.parse.urlparse(link).path).name, data


def extract_model_links(site, anchors):
    """anchors: [{href, text, alt, img}] lidos da página de busca. Devolve os modelos únicos, na ordem em que aparecem."""
    rx = re.compile(BROWSER_SITES[site]["link"])
    seen, out = set(), []
    for a in anchors:
        m = rx.search(a.get("href", ""))
        if not m or m.group(1) in seen:
            continue
        title = (a.get("alt") or a.get("text") or "").strip().split("\n")[0][:140]
        if not title:
            continue
        seen.add(m.group(1))
        out.append(dict(source=site, id=m.group(1), title=title, author="", url=a["href"].split("?")[0], thumb=a.get("img", ""),
                        downloads=None, likes=None, license="", commercial=None))
    return out


ANCHORS_JS = """els => els.map(a => { const i = a.querySelector('img'); return {href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim(),
  alt: i ? (i.alt || '') : '', img: i ? (i.currentSrc || i.src || '') : ''}; })"""


def search_browser(q, profile, sites, limit=8, on_captcha=lambda paused, kind="captcha": None, headless=False):
    """Uma sessão do Chrome do perfil salvo para os sites que exigem navegador. Devolve (resultados, avisos).
    "printables" em sites só mostra a página de busca na janela (os resultados dele vêm da API); com headless=False a janela fica à vista."""
    if profile not in list_profiles():
        raise ValueError(f"perfil desconhecido: {profile}")
    results, notes = [], []
    with sync_playwright() as p:
        ctx = launch_ctx(p, profile, headless=headless)
        front(ctx, headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for site in sites:
                try:
                    if site == "printables":
                        page.goto("https://www.printables.com/search/models?q=" + urllib.parse.quote(q), wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_timeout(4000)
                        continue
                    page.goto(BROWSER_SITES[site]["search"].format(q=urllib.parse.quote(q)), wait_until="domcontentloaded", timeout=45000)
                    if "just a moment" in page.title().lower() or _captcha(page):  # verificação do Cloudflare: a pessoa resolve na janela
                        _wait_human(page, on_captcha)
                    page.wait_for_timeout(3500)
                    page.mouse.wheel(0, 1500)
                    page.wait_for_timeout(1500)
                    found = extract_model_links(site, page.eval_on_selector_all("a[href]", ANCHORS_JS))[:limit]
                    results += found
                    if not found:
                        notes.append(f"{SITES[site]}: nenhum modelo encontrado na página (o site pode ter mudado)")
                except Exception as e:
                    notes.append(f"{SITES[site]}: {str(e)[:120]}")
        finally:
            ctx.close()
    return results, notes


def search(q, profile=None, sites=tuple(SITES), limit=8, on_captcha=lambda paused, kind="captcha": None):
    """(resultados, avisos). Printables sempre; os outros só com perfil do Chrome escolhido."""
    q = re.sub(r"\s+", " ", q).strip()[:100]
    if len(q) < 2:
        raise ValueError("digite o que buscar")
    results, notes = [], []
    if "printables" in sites:
        try:
            results += search_printables(q, limit)
        except ValueError as e:
            notes.append(str(e))
    browser_sites = [s for s in sites if s in BROWSER_SITES]
    if browser_sites and profile:
        r, n = search_browser(q, profile, browser_sites, limit, on_captcha)
        results += r
        notes += n
    elif browser_sites:
        notes.append("MakerWorld e Thingiverse precisam de um perfil do Chrome escolhido no topo da tela")
    return sorted(results, key=lambda r: list(SITES).index(r["source"])), notes


def unzip_model(name, data):
    """Se o arquivo baixado é .zip, devolve o maior .3mf (ou .stl) de dentro; senão devolve como veio."""
    if Path(name).suffix.lower() != ".zip":
        return name, data
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        cands = [i for i in z.infolist() if Path(i.filename).suffix.lower() in MODEL_EXT and not i.is_dir()]
        if not cands:
            raise ValueError("o .zip baixado não tem arquivo .3mf nem .stl")
        best = max(cands, key=lambda i: (Path(i.filename).suffix.lower() == ".3mf", i.file_size))
        if best.file_size > MAX_MODEL:
            raise ValueError("arquivo maior que 200 MB")
        return Path(best.filename).name, z.read(best)


def capture_download(page_url, profile, on_captcha=lambda paused, kind="captcha": None, wait_min=10):
    """Abre a página do modelo no Chrome do perfil e espera a pessoa clicar em Baixar. Devolve (nome, bytes) do .3mf/.stl/.zip baixado."""
    if profile not in list_profiles():
        raise ValueError(f"perfil desconhecido: {profile}")
    host = urllib.parse.urlparse(page_url).hostname or ""
    if not any(host.endswith(d) for d in ("makerworld.com", "thingiverse.com", "printables.com")):
        raise ValueError("só abro páginas de MakerWorld, Thingiverse ou Printables")
    with sync_playwright() as p:
        ctx = launch_ctx(p, profile, accept_downloads=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        got = []
        hook = lambda pg: pg.on("download", got.append)  # o site pode abrir o download em outra aba
        hook(page)
        ctx.on("page", hook)
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
            if "just a moment" in page.title().lower() or _captcha(page):
                _wait_human(page, on_captcha)
            end = time.time() + wait_min * 60
            while not got and ctx.pages and time.time() < end:
                time.sleep(1)
            if not got:
                raise ValueError(f"nenhum download em {wait_min} minutos; clique em Baixar na janela do Chrome e tente de novo" if ctx.pages
                                 else "a janela do Chrome foi fechada antes do download")
            data, name = Path(got[0].path()).read_bytes(), got[0].suggested_filename
        finally:
            ctx.close()
    if not 0 < len(data) <= MAX_MODEL:
        raise ValueError("arquivo vazio ou maior que 200 MB")
    ext = Path(name).suffix.lower()
    if ext not in MODEL_EXT | {".zip"}:
        raise ValueError(f"o arquivo baixado ({name}) não é .3mf, .stl nem .zip")
    return unzip_model(name, data)
