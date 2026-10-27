"""GUI local: python scripts/app/server.py  ->  http://localhost:8765"""
import json
import os
import html
import io
import re
import sqlite3
import zipfile
from datetime import datetime
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import paths  # noqa: E402
import proc  # noqa: E402

ROOT = paths.DATA  # banco, produtos e inbox; a pasta do projeto quando roda do código, %LOCALAPPDATA% quando instalado
if not paths.FROZEN:
    sys.path.insert(0, str(paths.SOURCE_ROOT / "scripts" / "mine"))
import costs as custos  # noqa: E402
import ml  # noqa: E402
import render as renderizar  # noqa: E402
import slice as fatiar  # noqa: E402
import video as videos  # noqa: E402
import selecao  # noqa: E402
import texto  # noqa: E402  (scripts/app/slice.py; mesmo diretório do server.py)
from classify import score  # noqa: E402
import model_search  # noqa: E402
import tools_installer  # noqa: E402
import updater  # noqa: E402
from store_reader import LOGIN_HOSTS as store_reader_hosts, chrome_path, list_profiles, open_for_login as store_reader_open, read_store, read_store_info  # noqa: E402

DB = ROOT / "db" / "app.sqlite"
STEPS = ["model", "slice", "cost", "copy", "images", "kit", "ml", "shopee", "video"]
STEP_NAMES = {"slice": "Fatiamento", "copy": "Texto do anúncio", "images": "Imagens"}
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg"}
lock = threading.Lock()
browser_lock = threading.Lock()


def db():
    c = sqlite3.connect(DB, timeout=120)  # o disco fica lento enquanto o Chrome escreve o perfil; esperar é melhor que falhar a leitura da loja
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA synchronous=NORMAL")  # com WAL, poucas sincronizações no disco e leitores que não travam quem grava
    return c


def init():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript((paths.RESOURCES / "db" / "schema.sql").read_text(encoding="utf-8"))
        if "profile" not in [r[1] for r in c.execute("PRAGMA table_info(stores)")]:  # banco criado antes dos perfis
            c.execute("ALTER TABLE stores ADD COLUMN profile TEXT DEFAULT ''")
        for table, col, ddl in [("listings", "thumb", "TEXT DEFAULT ''"), ("listings", "image", "INTEGER DEFAULT 0"), ("listings", "created", "TEXT DEFAULT ''"),
                                ("stores", "name", "TEXT DEFAULT ''")]:  # bancos criados antes dessas colunas
            if col not in [r[1] for r in c.execute(f"PRAGMA table_info({table})")]:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        for col, ddl in [("platform", "TEXT DEFAULT 'ml'"), ("reputation", "TEXT DEFAULT ''"), ("location", "TEXT DEFAULT ''"), ("since_text", "TEXT DEFAULT ''"),
                         ("sales", "INTEGER"), ("rating", "REAL"), ("followers", "INTEGER"), ("logo", "TEXT DEFAULT ''"), ("read_at", "TEXT DEFAULT ''")]:
            if col not in [r[1] for r in c.execute("PRAGMA table_info(stores)")]:  # dados da loja, adicionados depois
                c.execute(f"ALTER TABLE stores ADD COLUMN {col} {ddl}")
        if "info" not in [r[1] for r in c.execute("PRAGMA table_info(models)")]:  # título, autor, imagem e números do modelo escolhido (JSON)
            c.execute("ALTER TABLE models ADD COLUMN info TEXT DEFAULT ''")
        for col in ("started", "ts"):  # quando cada etapa começou e mudou de estado por último
            if col not in [r[1] for r in c.execute("PRAGMA table_info(steps)")]:
                c.execute(f"ALTER TABLE steps ADD COLUMN {col} TEXT")
        c.execute("CREATE TRIGGER IF NOT EXISTS steps_ts AFTER UPDATE OF status ON steps BEGIN UPDATE steps SET ts=CURRENT_TIMESTAMP,"
                  " started=CASE WHEN NEW.status='running' THEN CURRENT_TIMESTAMP ELSE started END WHERE listing_id=NEW.listing_id AND name=NEW.name; END")
        for name in STEPS:  # etapas criadas depois da aprovação de produtos antigos
            c.execute("INSERT OR IGNORE INTO steps(listing_id,name) SELECT id, ? FROM listings WHERE status='approved'", (name,))


def resume():
    """Servidor reiniciado: lojas que ficaram na fila ou lendo voltam a ser lidas."""
    with db() as c:
        c.execute("UPDATE stores SET status='pending' WHERE status IN ('running','captcha')")
        c.execute("UPDATE steps SET status='pending' WHERE status='running'")  # a thread que rodava a etapa morreu junto com o servidor
        rows = c.execute("SELECT id, url, profile FROM stores WHERE status='pending' AND profile!=''").fetchall()
        for l in c.execute("SELECT id, thumb FROM listings WHERE image=0 AND thumb!=''").fetchall():  # leituras anteriores à cópia local
            threading.Thread(target=fetch_image, args=(l["id"], l["thumb"]), daemon=True).start()
    for r in rows:
        threading.Thread(target=run_store, args=(r["id"], r["url"], r["profile"]), daemon=True).start()


TOAST = r"""
[void][Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent('ToastText02')
$t = $x.GetElementsByTagName('text')
[void]$t.Item(0).AppendChild($x.CreateTextNode($env:N_TITLE))
[void]$t.Item(1).AppendChild($x.CreateTextNode($env:N_MSG))
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""


def notify(title, msg):
    """Toast do Windows quando o fluxo precisa de uma pessoa. Texto vai por env var (sem injeção)."""
    proc.popen(["powershell", "-NoProfile", "-Command", TOAST], env=os.environ | {"N_TITLE": title, "N_MSG": msg},
                     stdout=proc.DEVNULL, stderr=proc.DEVNULL)


POPUP = """
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$f = New-Object Windows.Forms.Form -Property @{FormBorderStyle='None'; TopMost=$true; ShowInTaskbar=$false; StartPosition='Manual';
  Size=New-Object Drawing.Size(380,120); BackColor=[Drawing.Color]::FromArgb(255,230,0); Cursor='Hand'}
$wa = [Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$f.Location = New-Object Drawing.Point(($wa.Right - 396), ($wa.Bottom - 136))
$t = New-Object Windows.Forms.Label -Property @{Text=$env:N_TITLE; Font=New-Object Drawing.Font('Segoe UI',11,[Drawing.FontStyle]::Bold); Location='14,12'; Size='352,24'; ForeColor='#333333'}
$m = New-Object Windows.Forms.Label -Property @{Text=$env:N_MSG; Font=New-Object Drawing.Font('Segoe UI',9.5); Location='14,40'; Size='352,70'; ForeColor='#333333'}
$f.Controls.AddRange(@($t,$m))
foreach ($c in @($f,$t,$m)) { $c.Add_Click({ $f.Close() }) }
$tm = New-Object Windows.Forms.Timer -Property @{Interval=60000}; $tm.Add_Tick({ $f.Close() }); $tm.Start()
[Windows.Forms.Application]::Run($f)
"""


def popup(title, msg):
    """Aviso amarelo no canto inferior direito, sempre à frente, para ação manual (captcha, login). Clique ou 60 s fecha."""
    proc.popen(["powershell", "-NoProfile", "-Command", POPUP], env=os.environ | {"N_TITLE": title, "N_MSG": msg},
                     stdout=proc.DEVNULL, stderr=proc.DEVNULL)


IMAGES = ROOT / "db" / "images"
PRODUCTS = ROOT / "products"
INBOX = ROOT / "inbox"
MODEL_EXT = {".3mf", ".stl"}
MAX_MODEL = 200 * 1024 * 1024


def inbox_models():
    return sorted(p.name for p in INBOX.iterdir() if p.suffix.lower() in MODEL_EXT) if INBOX.exists() else []


def set_model(lid, name, data):
    """Guarda o arquivo em products/<id>/model/ e marca a etapa 'model' como ok."""
    with db() as c:
        if not c.execute("SELECT 1 FROM listings WHERE id=?", (lid,)).fetchone():
            raise ValueError("produto não encontrado")
    name = re.sub(r"[^\w.\- ]", "_", Path(name).name)  # só o nome do arquivo, sem pastas
    if Path(name).suffix.lower() not in MODEL_EXT:
        raise ValueError("só arquivos .3mf ou .stl")
    if not 0 < len(data) <= MAX_MODEL:
        raise ValueError("arquivo vazio ou maior que 200 MB")
    d = PRODUCTS / str(lid) / "model"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    with lock, db() as c:
        c.execute("INSERT INTO models(listing_id,file_path) VALUES(?,?) ON CONFLICT(listing_id) DO UPDATE SET file_path=excluded.file_path",
                  (lid, f"products/{lid}/model/{name}"))
        c.execute("UPDATE steps SET status='ok' WHERE listing_id=? AND name='model'", (lid,))
        c.execute("UPDATE steps SET status='pending', data='{}' WHERE listing_id=? AND name='slice'", (lid,))  # modelo novo: o fatiamento antigo não vale
        c.execute("DELETE FROM slices WHERE listing_id=?", (lid,))
        c.execute("UPDATE steps SET status='pending' WHERE listing_id=? AND name IN ('cost','images')", (lid,))


def get_setting(key, default=None):
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def put_setting(key, value):
    with lock, db() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


MEDIA_RE = re.compile(r"(render|photo)_\d+\.jpg")
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg"}


def media_files(lid):
    """Imagens do produto na ordem escolhida: [{name, hidden}]. render_N.jpg vem do Blender, photo_N.jpg é foto enviada por você."""
    d = PRODUCTS / str(lid) / "renders"
    names = [f.name for f in d.glob("*.jpg") if MEDIA_RE.fullmatch(f.name)] if d.exists() else []
    saved = get_setting(f"media:{lid}", {})
    order, hidden = saved.get("order", []), set(saved.get("hidden", []))
    names.sort(key=lambda n: (order.index(n) if n in order else 10**6, n.startswith("photo"), int(re.search(r"\d+", n).group())))
    return [dict(name=n, hidden=n in hidden) for n in names]


def set_media(lid, order, hidden):
    ok = lambda xs: isinstance(xs, list) and all(isinstance(x, str) and MEDIA_RE.fullmatch(x) for x in xs)
    if not ok(order) or not ok(hidden):
        raise ValueError("nomes de imagem inválidos")
    put_setting(f"media:{lid}", dict(order=order, hidden=hidden))


def add_photo(lid, data):
    """Foto enviada por você: vira JPG de até 2400 px em renders/photo_N.jpg e conta como imagem pronta."""
    from PIL import Image
    if not 0 < len(data) <= 25 * 1024 * 1024:
        raise ValueError("foto vazia ou maior que 25 MB")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise ValueError("não consegui abrir essa imagem (use JPG, PNG ou WEBP)")
    im = im.convert("RGB")
    im.thumbnail((2400, 2400))
    d = PRODUCTS / str(lid) / "renders"
    d.mkdir(parents=True, exist_ok=True)
    n = 1 + max([int(re.search(r"\d+", f.name).group()) for f in d.glob("photo_*.jpg")] or [0])
    im.save(d / f"photo_{n}.jpg", quality=92)
    with lock, db() as c:
        c.execute("UPDATE steps SET status='ok' WHERE listing_id=? AND name='images'", (lid,))
        c.execute("UPDATE steps SET status='pending' WHERE listing_id=? AND name='kit'", (lid,))
    return f"photo_{n}.jpg"


def del_photo(lid, name):
    if not re.fullmatch(r"photo_\d+\.jpg", name):
        raise ValueError("só dá para apagar fotos enviadas; os renders são refeitos em Gerar imagens")
    (PRODUCTS / str(lid) / "renders" / name).unlink(missing_ok=True)


def media_config():
    return dict(render=render_cfg(), video=video_cfg(),
                options=dict(finish=renderizar.CHOICES["finish"], background=renderizar.CHOICES["background"], quality=renderizar.CHOICES["quality"],
                             light=renderizar.CHOICES["light"], views=renderizar.VIEW_LABELS, formats=list(videos.FORMATS)))


def render_cfg():
    try:
        return renderizar.clean_render_cfg(get_setting("render_cfg", {}))
    except ValueError:
        return dict(renderizar.RENDER_DEFAULT)


def video_cfg():
    try:
        return videos.clean_video_cfg(get_setting("video_cfg", {}))
    except ValueError:
        return dict(videos.VIDEO_DEFAULT)


def get_costs():
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key='costs'").fetchone()
    return custos.DEFAULTS | (json.loads(row["value"]) if row else {})


def set_costs(data):
    new = {}
    for k, default in custos.DEFAULTS.items():
        if k in data:
            v = float(data[k])  # ValueError/TypeError viram 400 no chamador
            if not 0 <= v <= 100000:
                raise ValueError(f"{k}: valor fora do intervalo")
            new[k] = int(v) if k == "confirmado" else v
    with lock, db() as c:
        c.execute("INSERT INTO settings(key,value) VALUES('costs',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(get_costs() | new),))


def set_price(lid, price):
    price = float(price)
    if not 5 <= price <= 2000:
        raise ValueError("preço-alvo deve ficar entre R$ 5 e R$ 2.000")
    with lock, db() as c:
        if not c.execute("SELECT 1 FROM steps WHERE listing_id=? AND name='cost'", (lid,)).fetchone():
            raise ValueError("aprove o produto antes")
        c.execute("UPDATE steps SET data=? WHERE listing_id=? AND name='cost'", (json.dumps(dict(price=price)), lid))
        if c.execute("SELECT 1 FROM slices WHERE listing_id=?", (lid,)).fetchone():
            c.execute("UPDATE steps SET status='ok' WHERE listing_id=? AND name='cost'", (lid,))


BUSINESS = {"nome": "", "cores": "", "medidas": "", "prazo_dias": "3"}


def get_business():
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key='business'").fetchone()
    return BUSINESS | (json.loads(row["value"]) if row else {})


def set_business(data):
    new = {k: str(data[k]).strip()[:200] for k in BUSINESS if k in data}
    if "prazo_dias" in new and not new["prazo_dias"].isdigit():
        raise ValueError("prazo deve ser um número de dias")
    with lock, db() as c:
        c.execute("INSERT INTO settings(key,value) VALUES('business',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(get_business() | new),))


def set_kit(lid, d):
    """Valida e grava título, descrição, bullets, roteiros e palavras-chave (edição da pessoa ou resposta do Claude)."""
    title, desc = str(d.get("title", "")).strip(), str(d.get("description", "")).strip()
    lists = {k: [str(x).strip() for x in d.get(k, []) if str(x).strip()] for k in ("bullets", "scripts", "keywords")}
    if not 5 <= len(title) <= 60:
        raise ValueError("o título precisa ter de 5 a 60 caracteres")
    if len(desc) < 20 or len(desc) > 5000:
        raise ValueError("a descrição precisa ter de 20 a 5000 caracteres")
    with lock, db() as c:
        c.execute("INSERT INTO kits(listing_id,title,description,bullets,scripts,keywords) VALUES(?,?,?,?,?,?) ON CONFLICT(listing_id) DO UPDATE SET"
                  " title=excluded.title, description=excluded.description, bullets=excluded.bullets, scripts=excluded.scripts,"
                  " keywords=excluded.keywords, confirmed=0, ts=CURRENT_TIMESTAMP",
                  (lid, title, desc, json.dumps(lists["bullets"]), json.dumps(lists["scripts"]), json.dumps(lists["keywords"])))
        c.execute("UPDATE steps SET status='ok' WHERE listing_id=? AND name='copy'", (lid,))
        c.execute("UPDATE steps SET status='pending' WHERE listing_id=? AND name='kit'", (lid,))  # texto mudou: confirmar de novo


def run_copy(lid):
    def step(status, msg=""):
        with lock, db() as c:
            c.execute("UPDATE steps SET status=?, data=? WHERE listing_id=? AND name='copy'", (status, json.dumps(dict(msg=msg)), lid))

    try:
        step("running")
        cand = next((c for c in candidates() if c["id"] == lid), None)
        if not cand or not cand["slice"] or not cand["target_price"]:
            raise ValueError("fatie o modelo e defina o preço-alvo antes de gerar o texto")
        b = get_business()
        d = texto.generate(dict(title=cand["title"], price=cand["target_price"], material=(cand["material"] or "").strip(": ") or "PLA",
                                minutes=cand["slice"]["minutes"], grams=cand["slice"]["grams"], brand=b["nome"], colors=b["cores"],
                                sizes=b["medidas"], days=b["prazo_dias"]))
        set_kit(lid, d)
        step("ok")
    except Exception as e:  # erro fica visível no card da GUI
        step("error", str(e)[:300])


def confirm_kit(lid):
    """Aprovação humana 2: só confirma com modelo, fatiamento, custo, texto e imagens prontos."""
    cand = next((c for c in candidates() if c["id"] == lid), None)
    if not cand:
        raise ValueError("produto não encontrado")
    faltam = [n for n in ("model", "slice", "cost", "copy", "images") if cand["steps"].get(n) != "ok"]
    if faltam:
        raise ValueError("faltam etapas: " + ", ".join(faltam))
    with lock, db() as c:
        c.execute("UPDATE kits SET confirmed=1 WHERE listing_id=?", (lid,))
        c.execute("UPDATE steps SET status='ok' WHERE listing_id=? AND name='kit'", (lid,))


def kit_zip(lid):
    cand = next((c for c in candidates() if c["id"] == lid), None)
    if not cand or not cand["kit"]:
        raise ValueError("o produto ainda não tem texto")
    k, sl = cand["kit"], cand["slice"]
    anuncio = f"{k['title']}\n\nR$ {cand['target_price']:.2f}\n\n{k['description']}\n\n" + "\n".join(f"- {b}" for b in k["bullets"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("anuncio.txt", anuncio)
        z.writestr("roteiros.txt", "\n\n---\n\n".join(k["scripts"]))
        z.writestr("dados.json", json.dumps(dict(titulo=k["title"], preco=cand["target_price"], palavras_chave=k["keywords"],
                                                 tempo_min=sl["minutes"] if sl else None, gramas=sl["grams"] if sl else None,
                                                 margem=cand["margin"], origem=cand["url"]), ensure_ascii=False, indent=1))
        for n in cand["images"]:
            z.write(PRODUCTS / str(lid) / "renders" / n, f"imagens/{n}")
    return buf.getvalue()


def ml_item(lid, category_id, attributes, quantity):
    """Monta o anúncio do ML a partir do kit confirmado. Só kit confirmado vai para a API."""
    cand = next((c for c in candidates() if c["id"] == lid), None)
    if not cand or cand["steps"].get("kit") != "ok":
        raise ValueError("confirme o kit antes de publicar")
    if not isinstance(attributes, dict) or not re.fullmatch(r"MLB\d+", str(category_id)):
        raise ValueError("escolha a categoria e preencha os atributos")
    return cand, ml.build_item(cand, category_id, attributes, [], quantity=quantity, days=get_business()["prazo_dias"])


def ml_publish(lid, category_id, attributes, quantity):
    cand, item = ml_item(lid, category_id, attributes, quantity)
    files = [PRODUCTS / str(lid) / "renders" / n for n in cand["images"]]
    ext_id, link = ml.publish(item, cand["kit"]["description"] + "\n\n" + "\n".join("- " + b for b in cand["kit"]["bullets"]), files)
    with lock, db() as c:
        c.execute("INSERT INTO publications(listing_id,channel,external_id,url) VALUES(?,?,?,?) ON CONFLICT(listing_id,channel) DO UPDATE SET"
                  " external_id=excluded.external_id, url=excluded.url, status='published', ts=CURRENT_TIMESTAMP", (lid, "ml", ext_id, link))
        c.execute("UPDATE steps SET status='ok' WHERE listing_id=? AND name='ml'", (lid,))
    return ext_id, link


def mark_shopee(lid, url):
    if url and not re.match(r"https://", url):
        raise ValueError("o link deve começar com https://")
    with lock, db() as c:
        if not c.execute("SELECT 1 FROM steps WHERE listing_id=? AND name='shopee'", (lid,)).fetchone():
            raise ValueError("produto não encontrado")
        c.execute("INSERT INTO publications(listing_id,channel,url) VALUES(?,?,?) ON CONFLICT(listing_id,channel) DO UPDATE SET url=excluded.url, status='published', ts=CURRENT_TIMESTAMP",
                  (lid, "shopee", url[:500]))
        c.execute("UPDATE steps SET status='ok' WHERE listing_id=? AND name='shopee'", (lid,))


VOICE_EXT = {".wav", ".mp3", ".m4a", ".ogg"}


def set_voice(lid, name, data):
    ext = Path(name).suffix.lower()
    if ext not in VOICE_EXT or not 0 < len(data) <= 50 * 1024 * 1024:
        raise ValueError("envie um áudio .wav, .mp3, .m4a ou .ogg de até 50 MB")
    d = PRODUCTS / str(lid) / "kit"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("voz.*"):
        old.unlink()
    (d / f"voz{ext}").write_bytes(data)


def run_video(lid):
    def step(status, msg=""):
        with lock, db() as c:
            c.execute("UPDATE steps SET status=?, data=? WHERE listing_id=? AND name='video'", (status, json.dumps(dict(msg=msg)), lid))

    try:
        step("running")
        cand = next((c for c in candidates() if c["id"] == lid), None)
        if not cand or not cand["kit"] or not cand["images"]:
            raise ValueError("gere o texto e as imagens antes do vídeo")
        kit = PRODUCTS / str(lid) / "kit"
        voice = next(iter(sorted(kit.glob("voz.*"))), None)
        music = next(iter(sorted(kit.glob("musica.*"))), None)
        videos.make_video([PRODUCTS / str(lid) / "renders" / n for n in cand["images"]], (cand["kit"]["scripts"] or [cand["kit"]["title"]])[0],
                          kit / "video.mp4", voice, cfg=video_cfg(), music=music)
        step("ok", "com a sua voz" if voice else "sem voz: grave o roteiro, envie o áudio e gere de novo")
    except Exception as e:  # erro fica visível no card da GUI
        step("error", str(e)[:300])


render_lock = threading.Lock()


def run_images(lid, cfg):
    def step(status, msg=""):
        with lock, db() as c:
            c.execute("UPDATE steps SET status=?, data=? WHERE listing_id=? AND name='images'", (status, json.dumps(dict(msg=msg)), lid))

    try:
        with render_lock:
            step("running")
            with db() as c:
                m = c.execute("SELECT m.file_path, l.title FROM models m JOIN listings l ON l.id=m.listing_id WHERE m.listing_id=?", (lid,)).fetchone()
            if not m or not m["file_path"]:
                raise ValueError("envie o modelo 3D antes de gerar as imagens")
            renderizar.render_images(ROOT / m["file_path"], PRODUCTS / str(lid) / "renders", cfg, title=m["title"] or "")
            step("ok")
    except Exception as e:  # erro fica visível no card da GUI
        step("error", str(e)[:300])


AUTO = {}  # lid -> andamento do "rodar etapas", só em memória


def step_status(lid, name):
    with db() as c:
        r = c.execute("SELECT status, data FROM steps WHERE listing_id=? AND name=?", (lid, name)).fetchone()
    return (r["status"], json.loads(r["data"] or "{}").get("msg", "")) if r else ("pending", "")


def run_auto(lid):
    """Roda sozinho o que não depende de você: fatiar, texto e imagens (nessa ordem), parando no primeiro erro.
    Só você confirma o kit, grava a voz e publica."""
    job = AUTO[lid] = dict(status="running", step="", msg="")
    try:
        plan = [("slice", "Fatiando", run_slice, ()), ("copy", "Escrevendo o texto", run_copy, ()), ("images", "Gerando as imagens", run_images, (render_cfg(),))]
        for name, label, fn, extra in plan:
            if step_status(lid, name)[0] == "ok":
                continue
            job.update(step=name, msg=label + "…")
            with lock, db() as c:
                c.execute("UPDATE steps SET status='running' WHERE listing_id=? AND name=?", (lid, name))
            fn(lid, *extra)
            st, msg = step_status(lid, name)
            if st != "ok":
                raise ValueError(f"{STEP_NAMES[name]}: {msg or 'não terminou'}")
        job.update(status="done", step="", msg="Etapas automáticas prontas. Revise o texto e as imagens e confirme o kit.")
    except Exception as e:
        job.update(status="error", msg=str(e)[:300])


slice_lock = threading.Lock()  # um fatiamento por vez


def run_slice(lid):
    def step(status, msg=""):
        with lock, db() as c:
            c.execute("UPDATE steps SET status=?, data=? WHERE listing_id=? AND name='slice'", (status, json.dumps(dict(msg=msg)), lid))

    try:
        with slice_lock:
            step("running")
            with db() as c:
                m = c.execute("SELECT file_path FROM models WHERE listing_id=?", (lid,)).fetchone()
            if not m or not m["file_path"]:
                raise ValueError("envie o modelo 3D antes de fatiar")
            minutes, grams, out = fatiar.slice_model(ROOT / m["file_path"], PRODUCTS / str(lid) / "slice")
            with lock, db() as c:
                c.execute("INSERT INTO slices(listing_id,minutes,grams,file_path) VALUES(?,?,?,?) ON CONFLICT(listing_id) DO UPDATE SET"
                          " minutes=excluded.minutes, grams=excluded.grams, file_path=excluded.file_path, ts=CURRENT_TIMESTAMP",
                          (lid, minutes, grams, str(out.relative_to(ROOT)).replace("\\", "/")))
            step("ok")
            with lock, db() as c:
                c.execute("UPDATE steps SET status='ok' WHERE listing_id=? AND name='cost'", (lid,))
        try:
            eval_filters(lid)  # filtros do produto: medidas e teste de suporte (fora do lock do fatiamento)
        except Exception:
            pass  # o card mostra "não testado" e o botão Avaliar tenta de novo
    except Exception as e:  # erro fica visível no card da GUI
        step("error", str(e)[:300])


def set_model_meta(lid, source_url, license_note, info=None):
    if source_url and not re.match(r"https?://", source_url):  # o link é exibido na GUI
        raise ValueError("o link do modelo deve começar com http:// ou https://")
    with lock, db() as c:
        c.execute("INSERT INTO models(listing_id,source_url,license_note) VALUES(?,?,?) ON CONFLICT(listing_id) DO UPDATE SET"
                  " source_url=excluded.source_url, license_note=excluded.license_note", (lid, source_url[:500], license_note[:500]))
        if info is not None:
            c.execute("UPDATE models SET info=? WHERE listing_id=?", (json.dumps(info, ensure_ascii=False), lid))


MODEL_JOBS = {}  # lid -> estado da busca/captura de modelo, só em memória (a tela consulta)


def license_note(item):
    c = item.get("commercial")
    verdict = "uso comercial permitido" if c is True else "NÃO permite uso comercial" if c is False else "confira o uso comercial na página"
    return f"{item.get('license') or 'licença não informada'} ({verdict}). Fonte: {item.get('source', '')}"[:500]


def browser_headless():
    """Uma escolha só para todo o Chrome do app (leitura de lojas e busca de modelos). Padrão: a janela aparece, para você acompanhar."""
    return bool(get_setting("browser_headless", False))


model_headless = browser_headless


def run_model_search(lid, q, profile, sites, headless=None):
    headless = model_headless() if headless is None else headless
    job = MODEL_JOBS[lid] = dict(status="running", results=[], notes=[], msg="Buscando no Printables…", q=q, sites=sites, headless=headless)
    try:
        if "printables" in sites:
            try:
                job["results"] += model_search.search_printables(q)
            except ValueError as e:
                job["notes"].append(str(e))
        browser = [x for x in sites if x in model_search.BROWSER_SITES]
        show = ["printables"] if "printables" in sites and not headless and profile else []  # só para você ver a busca na janela
        if (browser or show) and profile:
            job["msg"] = ("Abrindo o Chrome" if not headless else "Buscando em segundo plano") + ". Se pedir verificação, resolva na janela."
            with browser_lock:
                r, n = model_search.search_browser(q, profile, show + browser, on_captcha=lambda p, kind="captcha": popup(*MANUAL[kind]) if p else None, headless=headless)
            job["results"] += r
            job["notes"] += n
        elif browser:
            job["notes"].append("MakerWorld e Thingiverse precisam de um perfil do Chrome escolhido no topo da tela")
        job["results"].sort(key=lambda r: list(model_search.SITES).index(r["source"]))  # MakerWorld primeiro
        if not job["results"] and not job["notes"]:
            job["notes"].append("nenhum modelo achado; os sites estão em inglês, use “Sugerir termos”")
        job.update(status="done", msg=f"{len(job['results'])} modelos encontrados")
    except Exception as e:
        job.update(status="error", msg=str(e)[:300])
    put_setting(f"msearch:{lid}", {k: job.get(k) for k in ("q", "sites", "headless", "results", "notes", "msg")} | dict(at=datetime.now().isoformat(timespec="seconds")))


def suggest_terms(title):
    """Termos de busca em inglês (os sites de modelos 3D são em inglês) para o título do anúncio, pelo Claude."""
    prompt = (f"Anúncio de um produto: «{title[:150]}». Dê 6 termos curtos de busca, em inglês, para achar o modelo 3D imprimível desse produto "
              "no Printables ou MakerWorld (2 a 4 palavras cada, do mais provável ao mais amplo). Responda só com os termos, um por linha, sem numeração.")
    r = proc.run([texto._cmd(), "-p"], input=prompt, capture_output=True, text=True, timeout=120, encoding="utf-8")
    if r.returncode:
        raise ValueError("o Claude retornou erro: " + (r.stderr or r.stdout)[:200])
    out = [re.sub(r"^[\-*\d.)\s]+", "", x).strip() for x in r.stdout.splitlines()]
    return [x for x in out if 2 <= len(x) <= 50][:6]


def pick_profile(wanted):
    """O perfil escolhido na tela; sem ele, o das lojas já cadastradas, ou o único que existe."""
    profiles = list_profiles()
    if wanted in profiles:
        return wanted
    with db() as c:
        used = [r[0] for r in c.execute("SELECT profile FROM stores WHERE profile!='' ORDER BY id DESC")]
    return next((p for p in used if p in profiles), profiles[0] if len(profiles) == 1 else None)


def open_url(url, profile=None):
    """Abre um link no navegador padrão, ou no Chrome do perfil do app. Só sites que o app usa."""
    u = urlparse(url)
    if u.scheme != "https" or not any((u.hostname or "") == h or (u.hostname or "").endswith("." + h)
                                      for h in store_reader_hosts + ("github.com",)):
        raise ValueError("só abro links de Mercado Livre, MakerWorld, Printables, Thingiverse e GitHub")
    if profile:
        store_reader_open(profile, url)
    else:
        import webbrowser
        webbrowser.open(url)


def get_printables_model(lid, model_id, file_id, title, url, license_name, info=None):
    """Baixa o arquivo pelo Printables e já guarda como modelo do produto, com link e licença."""
    name, data = model_search.printables_download(model_id, file_id)
    set_model(lid, name, data)
    set_model_meta(lid, url, license_note(dict(license=license_name, commercial=model_search.commercial_ok(license_name), source="Printables")),
                   dict(info or {}, title=title, source="Printables", file=name))


def model_info(d):
    """Dados do modelo escolhido que a tela mostra: imagem (só https), autor, números da página e o que foi buscado."""
    thumb = str(d.get("thumb", ""))
    return dict(thumb=thumb if thumb.startswith("https://") else "", author=str(d.get("author", ""))[:80], query=str(d.get("q", ""))[:100],
                file_size=d.get("file_size") if isinstance(d.get("file_size"), int) else None, model_id=str(d.get("model_id", ""))[:20],
                downloads=d.get("downloads") if isinstance(d.get("downloads"), int) else None, likes=d.get("likes") if isinstance(d.get("likes"), int) else None)


def git(*args, timeout=60):
    return proc.run(["git", *args], cwd=str(paths.SOURCE_ROOT), capture_output=True, text=True, timeout=timeout)


def git_behind():
    """Quantos commits o GitHub tem a mais que esta pasta (0 se não der para saber)."""
    try:
        if git("fetch", "-q", timeout=30).returncode:
            return 0
        r = git("rev-list", "--count", "HEAD..@{u}")
        return int(r.stdout.strip() or 0) if not r.returncode else 0
    except Exception:
        return 0


def git_pull():
    """Traz as alterações do GitHub sem mexer no que está feito aqui; levanta ValueError com o motivo se não der."""
    try:
        r = git("pull", "--ff-only")
    except Exception as e:
        raise ValueError(f"não consegui rodar o git: {e}")
    if r.returncode:
        raise ValueError("não consegui puxar as alterações: " + (r.stderr.strip() or r.stdout.strip())[:250])


def run_restart():
    """Fecha o app e abre de novo (a janela e o servidor). Do código, recarrega os arquivos .py do disco."""
    exe = Path(sys.executable)
    cmd = f'"{exe}"' if paths.FROZEN else f'"{exe.with_name("pythonw.exe") if exe.name.lower() == "python.exe" else exe}" "{Path(__file__).with_name("desktop.py")}"'
    # espera as portas fecharem e só então abre; roda solto, para sobreviver a este processo
    proc.popen(f'cmd /c ping -n 4 127.0.0.1 >nul & start "" {cmd}', cwd=str(paths.SOURCE_ROOT if not paths.FROZEN else paths.HOME), shell=True,
                     creationflags=proc.DETACHED_PROCESS | proc.CREATE_NEW_PROCESS_GROUP, show=True)
    if not paths.FROZEN:  # o servidor é filho da janela (desktop.py): fecha a janela junto
        proc.run(["taskkill", "/F", "/PID", str(os.getppid())])
    os._exit(0)


def run_model_capture(lid, url, profile, license_name, source):
    job = MODEL_JOBS[lid] = dict(status="running", results=[], notes=[], msg="Chrome aberto: clique em Baixar na página do modelo. O app captura o arquivo.")
    try:
        with browser_lock:
            name, data = model_search.capture_download(url, profile, on_captcha=lambda p, kind="captcha": popup(*MANUAL[kind]) if p else None)
        set_model(lid, name, data)
        set_model_meta(lid, url, license_note(dict(license=license_name, commercial=model_search.commercial_ok(license_name), source=source)))
        job.update(status="done", msg=f"Arquivo {name} guardado como modelo.")
    except Exception as e:
        job.update(status="error", msg=str(e)[:300])


def fetch_image(lid, url):
    """Guarda a miniatura em disco para o catálogo não depender do link do ML."""
    u = urlparse(url or "")
    if u.scheme != "https" or not (u.hostname or "").endswith("mlstatic.com"):  # URL vem da página lida
        return
    try:
        data = urllib.request.urlopen(url, timeout=10).read(2_000_000)
        IMAGES.mkdir(exist_ok=True)
        (IMAGES / f"{lid}.img").write_bytes(data)
        with lock, db() as c:
            c.execute("UPDATE listings SET image=1 WHERE id=?", (lid,))
    except Exception:
        pass  # shortcut: sem cópia local, a GUI usa a URL remota


def sniff(data):
    return "image/webp" if data[8:12] == b"WEBP" else "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"


MANUAL = {
    "captcha": ("Resolva o captcha no Chrome",
                "Vá à janela do Chrome aberta pelo app e marque “Não sou um robô” ou conclua a etapa de segurança. A leitura continua sozinha."),
    "login": ("Faça login no site aberto",
              "Vá à janela do Chrome aberta pelo app e entre com a sua conta. Para entrar com o Google, feche essa janela e use Configurações > Entrar nas contas."),
}


def remove_store(sid):
    """Apaga a loja, os anúncios lidos dela e tudo que pendura neles. Recusa se está sendo lida ou se algum produto já foi publicado."""
    with lock, db() as c:
        row = c.execute("SELECT status FROM stores WHERE id=?", (sid,)).fetchone()
        if not row:
            raise ValueError("loja não encontrada")
        if row["status"] in ("running", "captcha"):
            raise ValueError("a loja está sendo lida agora; espere terminar")
        ids = [r[0] for r in c.execute("SELECT id FROM listings WHERE store_id=?", (sid,))]
        marks = ",".join("?" * len(ids))
        if ids and c.execute(f"SELECT 1 FROM publications WHERE listing_id IN ({marks})", ids).fetchone():
            raise ValueError("a loja tem produto publicado; não dá para remover")
        for t in ("snapshots", "steps", "models", "slices", "kits"):
            c.execute(f"DELETE FROM {t} WHERE listing_id IN ({marks})", ids)
        c.execute("DELETE FROM listings WHERE store_id=?", (sid,))
        c.execute("DELETE FROM stores WHERE id=?", (sid,))
    for i in ids:  # miniaturas; a pasta products/<id> com modelos e renders fica no disco
        (IMAGES / f"{i}.img").unlink(missing_ok=True)


def save_store_info(store_id, d):
    """Grava só o que a leitura achou; o que veio vazio não apaga o que já se sabia."""
    with lock, db() as c:
        c.execute("UPDATE stores SET name=COALESCE(NULLIF(?,''),name), reputation=COALESCE(NULLIF(?,''),reputation), location=COALESCE(NULLIF(?,''),location),"
                  " since_text=COALESCE(NULLIF(?,''),since_text), sales=COALESCE(?,sales), rating=COALESCE(?,rating), followers=COALESCE(?,followers),"
                  " logo=COALESCE(NULLIF(?,''),logo), read_at=CURRENT_TIMESTAMP WHERE id=?",
                  (d.get("name", ""), d.get("reputation", ""), d.get("location", ""), d.get("since_text", ""), d.get("sales"), d.get("rating"),
                   d.get("followers"), d.get("logo", ""), store_id))


def platform_of(url):
    """'ml' pelo domínio de verdade (não por texto solto na URL); None se não for loja que o app lê."""
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https":
        return None
    if host == "mercadolivre.com.br" or host.endswith(".mercadolivre.com.br"):
        return "ml"
    return None


def run_store_info(ids, profile):
    """Atualiza nome, logo e dados das lojas sem reler os anúncios (uma página por loja)."""
    for sid in ids:
        with db() as c:
            row = c.execute("SELECT url FROM stores WHERE id=?", (sid,)).fetchone()
        if not row:
            continue
        try:
            with browser_lock:
                save_store_info(sid, read_store_info(row["url"], profile, on_captcha=lambda p, kind="captcha": popup(*MANUAL[kind]) if p else None, headless=browser_headless()))
        except Exception as e:
            with lock, db() as c:
                c.execute("UPDATE stores SET msg=? WHERE id=?", (str(e)[:300], sid))


def run_store(store_id, url, profile):
    def setstatus(status, msg=""):
        with lock, db() as c:
            c.execute("UPDATE stores SET status=?, msg=? WHERE id=?", (status, msg, store_id))
        if status == "captcha":
            popup(*MANUAL[msg])
        elif status == "error":
            popup("A leitura da loja falhou", f"{msg[:140]}\nAbra o app e clique em “Tentar de novo”.")

    def on_listing(d):
        with lock, db() as c:
            c.execute("INSERT OR IGNORE INTO listings(store_id,url,title,price,material,is_3d) VALUES(?,?,?,?,?,?)",
                      (store_id, d["url"], d["title"], d["price"], d["material"], d["is_3d"]))
            lid = c.execute("SELECT id FROM listings WHERE url=?", (d["url"],)).fetchone()[0]
            c.execute("UPDATE listings SET title=?, price=?, material=?, is_3d=?, thumb=? WHERE id=?",
                      (d["title"], d["price"], d["material"], d["is_3d"], d["thumb"], lid))
            c.execute("UPDATE stores SET name=? WHERE id=? AND ?!='' AND name=''", (d["store_name"], store_id, d["store_name"]))  # o nome do bloco do vendedor (on_store) manda
            c.execute("INSERT INTO snapshots(listing_id,sold,reviews,rank) VALUES(?,?,?,?)",
                      (lid, d["sold"], d["reviews"], d["rank"]))
        threading.Thread(target=fetch_image, args=(lid, d["thumb"]), daemon=True).start()

    on_store = lambda d: save_store_info(store_id, d)

    try:
        with browser_lock:  # o perfil do Chrome só abre uma vez; lojas rodam em fila
            setstatus("running")
            read_store(url, profile, on_captcha=lambda p, kind="captcha": setstatus("captcha" if p else "running", kind if p else ""),
                       on_listing=on_listing, on_store=on_store, headless=browser_headless())
        setstatus("done")
        with db() as c:
            n = c.execute("SELECT COUNT(*) FROM listings WHERE store_id=? AND is_3d=1 AND status='new'", (store_id,)).fetchone()[0]
        notify("Loja analisada", f"{n} produtos 3D esperando sua aprovação.")
    except Exception as e:  # erro fica visível na GUI
        setstatus("error", str(e)[:300])


def get_filters():
    try:
        return selecao.clean_filters(get_setting("filters", {}))
    except ValueError:
        return selecao.clean_filters({})


def eval_filters(lid, support=True):
    """Mede o modelo (dimensões, espessura média, área em balanço) e, com support, faz o fatiamento de teste com suporte ligado. Guarda em mesh:<id>."""
    with db() as c:
        m = c.execute("SELECT file_path FROM models WHERE listing_id=?", (lid,)).fetchone()
    if not m or not m["file_path"]:
        raise ValueError("envie o modelo 3D antes de avaliar os filtros")
    path = ROOT / m["file_path"]
    prev = get_setting(f"mesh:{lid}", {})
    put_setting(f"mesh:{lid}", dict(prev, status="running", msg=""))
    data = dict(prev, status="ok", msg="")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            stl = path
            if path.suffix.lower() == ".3mf":
                stl = Path(tmp) / "modelo.stl"
                renderizar.threemf_to_stl(path, stl)
            data["stats"] = selecao.mesh_stats(stl)
        if support:
            try:
                with slice_lock:
                    r = fatiar.check_support(path, PRODUCTS / str(lid) / "slice_suporte")
                data.update(support=r["support"], support_minutes=r["minutes"])
            except ValueError as e:
                data.update(support=None, msg="teste de suporte indisponível: " + str(e)[:160])
    except Exception as e:
        data.update(status="error", msg=str(e)[:200])
    put_setting(f"mesh:{lid}", data)
    return data


def propose_tese(lid):
    """O Claude propõe a dor e os tipos de produto parecidos a partir da foto e dos títulos. A faixa de preço vem dos anúncios parecidos já lidos. A pessoa edita depois."""
    prev = get_setting(f"tese:{lid}") or {}
    put_setting(f"tese:{lid}", dict(prev, status="running", msg=""))
    try:
        cands = candidates()
        me = next(c for c in cands if c["id"] == lid)
        photo = IMAGES / f"{lid}.img"
        if not photo.is_file():
            raise ValueError("sem a foto do anúncio guardada")
        sim = selecao.similar_rows(me, cands)
        t = selecao.propose_thesis(me["title"], photo, [r["title"] for r in sim if r["id"] != lid])
        band = selecao.price_band(sim, lid)
        put_setting(f"tese:{lid}", dict(status="ok", msg="", dor=t["dor"], similares=t["similares"], faixa_min=band["min"] if band else None, faixa_max=band["max"] if band else None,
                                        faixa_fonte="anúncios parecidos lidos" if band else "", proposta=True))
    except Exception as e:
        put_setting(f"tese:{lid}", dict(prev, status="error", msg=str(e)[:200]))


def set_created(lid, created):
    created = str(created or "").strip()
    if created and selecao.age_days(created) is None:
        raise ValueError("data de publicação inválida (use AAAA-MM-DD, no passado)")
    with lock, db() as c:
        c.execute("UPDATE listings SET created=? WHERE id=?", (created[:10], lid))


def candidates():
    cc = get_costs()
    F = get_filters()
    with db() as c:
        rows = []
        for l in c.execute("SELECT l.*, s.name AS store_name, s.url AS store_url FROM listings l JOIN stores s ON s.id=l.store_id"):
            snaps = c.execute("SELECT sold,reviews,rank,ts FROM snapshots WHERE listing_id=? ORDER BY id", (l["id"],)).fetchall()
            last, first = snaps[-1], snaps[0]
            growth = last["reviews"] - first["reviews"] if len(snaps) > 1 else 0
            steps = {s["name"]: s["status"] for s in c.execute("SELECT name,status FROM steps WHERE listing_id=?", (l["id"],))}
            step_times = {s["name"]: dict(started=s["started"], ts=s["ts"], seconds=int((datetime.fromisoformat(s["ts"]) - datetime.fromisoformat(s["started"])).total_seconds())
                                          if s["started"] and s["ts"] and s["status"] in ("ok", "error") else None)
                          for s in c.execute("SELECT name,status,started,ts FROM steps WHERE listing_id=?", (l["id"],))}
            model = c.execute("SELECT source_url,license_note,file_path,info,added_at FROM models WHERE listing_id=?", (l["id"],)).fetchone()
            sl = c.execute("SELECT minutes,grams FROM slices WHERE listing_id=?", (l["id"],)).fetchone()
            slmsg = c.execute("SELECT data FROM steps WHERE listing_id=? AND name='slice'", (l["id"],)).fetchone()
            kit = c.execute("SELECT title,description,bullets,scripts,keywords,confirmed FROM kits WHERE listing_id=?", (l["id"],)).fetchone()
            cpmsg = c.execute("SELECT data FROM steps WHERE listing_id=? AND name='copy'", (l["id"],)).fetchone()
            pubs = {r["channel"]: dict(r) for r in c.execute("SELECT channel,external_id,url,status FROM publications WHERE listing_id=?", (l["id"],))}
            vmsg = c.execute("SELECT data FROM steps WHERE listing_id=? AND name='video'", (l["id"],)).fetchone()
            impath = c.execute("SELECT data FROM steps WHERE listing_id=? AND name='images'", (l["id"],)).fetchone()
            cprice = c.execute("SELECT data FROM steps WHERE listing_id=? AND name='cost'", (l["id"],)).fetchone()
            target = (json.loads(cprice["data"]).get("price") if cprice else None) or l["price"]
            margin = {ch: custos.calc(cc, sl["minutes"], sl["grams"], target, ch) for ch in ("ml", "shopee")} if sl and target else None
            rows.append(dict(l) | dict(sold=last["sold"], reviews=last["reviews"], growth=growth, snapshots=len(snaps),
                                      sold_growth=last["sold"] - first["sold"], since=first["ts"], last_seen=last["ts"], model=dict(model) | dict(info=json.loads(model["info"] or "{}")) if model else None, msearch=get_setting(f"msearch:{l['id']}"), slice_file=(sl_file["file_path"] if (sl_file := c.execute("SELECT file_path FROM slices WHERE listing_id=?", (l["id"],)).fetchone()) else ""), slice=dict(sl) if sl else None, margin=margin, target_price=target,
                                      kit=dict(kit) | {k: json.loads(kit[k]) for k in ("bullets", "scripts", "keywords")} if kit else None,
                                      copy_msg=json.loads(cpmsg["data"]).get("msg", "") if cpmsg else "",
                                      publications=pubs, auto=AUTO.get(l["id"]), step_times=step_times, video_msg=json.loads(vmsg["data"]).get("msg", "") if vmsg else "",
                                      has_voice=any((PRODUCTS / str(l["id"]) / "kit").glob("voz.*")),
                                      images=[m["name"] for m in media_files(l["id"]) if not m["hidden"]] if steps.get("images") == "ok" else [], media=media_files(l["id"]),
                                      has_music=any((PRODUCTS / str(l["id"]) / "kit").glob("musica.*")),
                                      images_msg=json.loads(impath["data"]).get("msg", "") if impath else "", costs_confirmed=bool(cc["confirmado"]),
                                      slice_msg=json.loads(slmsg["data"]).get("msg", "") if slmsg else "", history=[s["reviews"] for s in snaps],
                                      score=score(last["sold"], last["reviews"], l["price"], l["is_3d"], last["rank"], growth),
                                      steps=steps))
            mesh = get_setting(f"mesh:{l['id']}", {}) or {}
            spd = selecao.sales_per_day(last["sold"], l["created"])
            rows[-1].update(tese=get_setting(f"tese:{l['id']}"), filtros=selecao.evaluate(l["title"], F, mesh.get("stats"), sl["minutes"] if sl else None, mesh.get("support")) | dict(mesh_msg=mesh.get("msg", ""), mesh_status=mesh.get("status", ""),
                            stats=mesh.get("stats")), per_day=spd, age_days=selecao.age_days(l["created"]), champion=selecao.is_champion(spd, F))
        return sorted(rows, key=lambda r: (r["filtros"]["status"] == "reprovado", -r["score"]))  # reprovados nos filtros vão para o fim


_ML_CACHE = {"at": 0, "data": None}


def ml_overview():
    """Conta do Mercado Livre pela API oficial, com cache de 60 s para não chamar a cada atualização da tela."""
    import time
    st = ml.status()
    if not st["connected"]:
        return dict(connected=False, configured=st["configured"])
    if _ML_CACHE["data"] and time.time() - _ML_CACHE["at"] < 60:
        return _ML_CACHE["data"]
    try:
        me = ml.call("GET", "/users/me")
        items = ml.call("GET", f"/users/{me['id']}/items/search?limit=1")
        data = dict(connected=True, configured=True, nickname=me.get("nickname", ""), user_id=me.get("id"), items=(items.get("paging") or {}).get("total"),
                    reputation=((me.get("seller_reputation") or {}).get("level_id") or ""), permalink=me.get("permalink", ""))
    except ValueError as e:
        return dict(connected=True, configured=True, error=str(e))
    _ML_CACHE.update(at=time.time(), data=data)
    return data


def summary():
    """Tudo o que já foi feito, em um lugar: funil, produtos com mídia e custos, anúncios publicados, lojas e contas."""
    cands = candidates()
    approved = [c for c in cands if c["status"] == "approved"]
    with db() as c:
        stores = [dict(r) for r in c.execute(
            "SELECT s.id, s.name, s.url, s.logo, s.status, (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id) AS n,"
            " (SELECT ROUND(AVG(price),2) FROM listings l WHERE l.store_id=s.id AND price IS NOT NULL) AS avg_price FROM stores s ORDER BY s.id DESC")]
    products = []
    for p in approved:
        kitdir = PRODUCTS / str(p["id"]) / "kit"
        products.append(dict(id=p["id"], title=p["title"], thumb=p["thumb"], image=p["image"], steps=p["steps"], done=sum(1 for v in p["steps"].values() if v == "ok"),
                             total=len(STEPS), price=p["target_price"], original_price=p["price"], margin=p["margin"], slice=p["slice"],
                             images=p["images"], has_video=(kitdir / "video.mp4").is_file(), has_voice=p["has_voice"], has_music=p["has_music"],
                             model=p["model"], publications=p["publications"], kit_title=(p["kit"] or {}).get("title", ""), url=p["url"]))
    published = [dict(id=p["id"], title=p["title"], channel=ch, url=pub.get("url", ""), external_id=pub.get("external_id", ""), status=pub.get("status", ""))
                 for p in approved for ch, pub in p["publications"].items()]
    funnel = dict(stores=len(stores), listings=len(cands), review=sum(1 for c in cands if c["status"] == "new"), approved=len(approved),
                  ready=sum(1 for p in approved if p["steps"].get("kit") == "ok"), published=len({x["id"] for x in published}),
                  with_video=sum(1 for p in products if p["has_video"]))
    cc = get_costs()
    return dict(funnel=funnel, products=products, published=published, stores=stores, ml=ml_overview(), costs=cc, costs_confirmed=bool(cc["confirmado"]),
                labels=custos.LABELS, business=get_business())


def run_simulation(data):
    """Valida a entrada da tela e usa custos.simulate nos produtos aprovados já fatiados."""
    channel = data.get("channel", "ml")
    if channel not in ("ml", "shopee"):
        raise ValueError("canal inválido")
    fixed = float(data.get("fixed", 0))
    if not 0 <= fixed <= 100000:
        raise ValueError("custo fixo mensal fora do intervalo")
    by_id = {c["id"]: c for c in candidates() if c["status"] == "approved" and c["slice"]}
    items = []
    for it in data.get("items", []):
        c = by_id.get(int(it["id"]))
        if not c:
            continue
        price, units = float(it.get("price") or c["target_price"]), int(it.get("units", 0))
        if not 5 <= price <= 2000 or not 0 <= units <= 10000:
            raise ValueError("preço entre R$ 5 e R$ 2.000 e vendas entre 0 e 10.000 por mês")
        items.append(dict(id=c["id"], minutes=c["slice"]["minutes"], grams=c["slice"]["grams"], price=price, units=units))
    return custos.simulate(get_costs(), items, channel, fixed)


def health():
    """O que o app precisa para trabalhar e se está disponível neste computador."""
    def which(f):
        try:
            return str(f())
        except Exception:
            return ""
    claude = which(texto._cmd)
    return dict(slicer=fatiar.SLICER.exists(), blender=renderizar.BLENDER.exists(), ffmpeg=videos.FFMPEG.exists(), chrome=bool(which(chrome_path)), claude=bool(claude),
                profiles=list_profiles(), ml=ml.status(), costs_confirmed=bool(get_costs()["confirmado"]), business=get_business())


TOOL_JOBS = {}  # nome -> andamento do download/instalação, só em memória
UPDATE_JOB = {"status": "idle", "msg": "", "done": 0, "total": 0}
_UPDATE_CHECK = {"at": 0, "data": None}


def tools_status():
    return [dict(name=n, label=m["label"], size_mb=m["size_mb"], installed=tools_installer.installed(n) or _tool_ok(n), job=TOOL_JOBS.get(n))
            for n, m in tools_installer.MANIFEST.items()]


def _tool_ok(name):
    """Ferramenta achada fora da pasta do app (ex.: ffmpeg no PATH) também vale."""
    return {"bambustudio": fatiar.SLICER.exists(), "blender": renderizar.BLENDER.exists(), "ffmpeg": videos.FFMPEG.exists()}[name]


def run_tool_install(name):
    job = TOOL_JOBS[name] = dict(status="running", stage="baixando", done=0, total=0, msg="")

    def progress(stage, done, total):
        job.update(stage=stage, done=done, total=total)

    try:
        tools_installer.install(name, progress)
        renderizar.refresh()
        videos.refresh()
        job.update(status="done", stage="pronto")
    except Exception as e:
        job.update(status="error", msg=str(e)[:300])


def update_check(force=False):
    import time
    if not force and _UPDATE_CHECK["data"] and time.time() - _UPDATE_CHECK["at"] < 600:
        return _UPDATE_CHECK["data"]
    data = updater.check() | dict(frozen=paths.FROZEN)
    if not paths.FROZEN:  # rodando do código a versão é o git: o que importa é quanto falta puxar do GitHub
        data["behind"] = git_behind()
    _UPDATE_CHECK.update(at=time.time(), data=data)
    return data


def run_update(info):
    UPDATE_JOB.update(status="running", msg="Baixando a atualização…", done=0, total=0)
    try:
        path = updater.download(info, progress=lambda d, t: UPDATE_JOB.update(done=d, total=t))
        UPDATE_JOB.update(status="installing", msg="Instalando. O app fecha e abre de novo sozinho.")
        updater.launch_installer(path)
        threading.Timer(2.0, lambda: os._exit(0)).start()  # dá tempo da tela receber o aviso; o instalador reabre o app
    except Exception as e:
        UPDATE_JOB.update(status="error", msg=str(e)[:300])


ONBOARDING = {"done": False, "step": 0, "tours": {}}


def get_onboarding():
    return ONBOARDING | (get_setting("onboarding", {}) or {})


def set_onboarding(d):
    cur = get_onboarding()
    if "done" in d:
        cur["done"] = bool(d["done"])
    if "step" in d:
        cur["step"] = max(0, min(20, int(d["step"])))
    if "tours" in d and isinstance(d["tours"], dict):
        cur["tours"] = cur["tours"] | {str(k)[:30]: bool(v) for k, v in d["tours"].items()}
    put_setting("onboarding", cur)
    return cur


class H(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path == "/api/state":
            with db() as c:
                stores = [dict(r) for r in c.execute(
                    "SELECT s.*, (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id) AS n,"
                    " (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.is_3d=1) AS n3d,"
                    " (SELECT COUNT(*) FROM listings l WHERE l.store_id=s.id AND l.status='approved') AS n_appr,"
                    " (SELECT ROUND(AVG(price),2) FROM listings l WHERE l.store_id=s.id AND price IS NOT NULL) AS avg_price,"
                    " (SELECT title FROM listings l JOIN snapshots n ON n.listing_id=l.id WHERE l.store_id=s.id ORDER BY n.sold DESC LIMIT 1) AS best"
                    " FROM stores s ORDER BY s.id DESC")]
            return self._json(dict(stores=stores, candidates=candidates(), steps=STEPS, profiles=list_profiles()))
        if path == "/api/business":
            return self._json(get_business())
        if path == "/api/ml/status":
            return self._json(ml.status())
        if path == "/api/ml/auth":
            try:
                loc = ml.auth_url()
            except ValueError as e:
                return self._json(dict(error=str(e)), 400)
            self.send_response(302)
            self.send_header("Location", loc)
            self.end_headers()
            return
        if path == "/api/ml/callback":
            try:
                ml.exchange_code("code=" + parse_qs(url.query).get("code", [""])[0])
                msg = "Conta do Mercado Livre conectada. Pode fechar esta janela."
            except ValueError as e:
                msg = f"Não foi possível conectar: {e}"
            body = f"<!doctype html><meta charset=utf-8><title>Mercado Livre</title><p style='font:16px system-ui;padding:24px'>{html.escape(msg)}</p>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/api/ml/categories", "/api/ml/attributes"):
            q = parse_qs(url.query).get("q", [""])[0]
            try:
                return self._json(ml.categories(q) if path.endswith("categories") else ml.required_attributes(q))
            except ValueError as e:
                return self._json(dict(error=str(e)), 400)
        if path == "/api/tools":
            return self._json(tools_status())
        if path == "/api/update/check":
            return self._json(update_check(force="force" in parse_qs(url.query)) | dict(job=UPDATE_JOB, version=paths.version()))
        if path == "/api/summary":
            return self._json(summary())
        if path == "/api/health":
            return self._json(health())
        if path == "/api/onboarding":
            return self._json(get_onboarding())
        if path == "/api/media/config":
            return self._json(media_config())
        if path == "/api/costs":
            return self._json(dict(values=get_costs(), labels=custos.LABELS))
        if path == "/api/filtros":
            return self._json(dict(values=get_filters(), labels=selecao.LABELS))
        if path == "/api/similares":
            lid = int(parse_qs(url.query).get("id", ["0"])[0])
            cands = candidates()
            me = next((c for c in cands if c["id"] == lid), None)
            if not me:
                return self._json(dict(error="produto não encontrado"), 404)
            sim = selecao.similar_rows(me, cands)
            return self._json(dict(rows=selecao.compare_similar(sim), price=selecao.price_band(sim, me["id"])))
        m = re.fullmatch(r"/api/kit/(\d+)\.zip", path)
        if m:
            try:
                body = kit_zip(int(m.group(1)))
            except ValueError as e:
                return self._json(dict(error=str(e)), 404)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="kit-{m.group(1)}.zip"')
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/browser":
            return self._json(dict(headless=browser_headless()))
        if path == "/api/model/search":
            q = parse_qs(url.query)
            lid = int(q.get("id", ["0"])[0])
            return self._json(dict(MODEL_JOBS.get(lid) or dict(get_setting(f"msearch:{lid}") or dict(results=[], notes=[], msg=""), status="idle"), headless=model_headless()))
        if path == "/api/model/files":
            try:
                return self._json(model_search.printables_files(parse_qs(url.query).get("model_id", [""])[0]))
            except ValueError as e:
                return self._json(dict(error=str(e)), 400)
        if path == "/api/inbox":
            return self._json(inbox_models())
        if path.startswith("/api/product/"):
            pid = path.rsplit("/", 1)[1]
            found = next((c for c in candidates() if str(c["id"]) == pid), None)
            return self._json(found or dict(error="produto não encontrado"), 200 if found else 404)
        m = re.fullmatch(r"/products/(\d+)/renders/((?:render|photo)_\d+\.jpg)", path)  # só as fotos geradas, nunca outro arquivo
        if m:
            f = PRODUCTS / m.group(1) / "renders" / m.group(2)
            if not f.is_file():
                return self._json(dict(error="não encontrado"), 404)
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(body)
            return
        m = re.fullmatch(r"/products/(\d+)/kit/video\.mp4", path)
        if m and (PRODUCTS / m.group(1) / "kit" / "video.mp4").is_file():
            body = (PRODUCTS / m.group(1) / "kit" / "video.mp4").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/images/") and path[8:].isdigit():
            f = IMAGES / f"{path[8:]}.img"
            if not f.is_file():
                return self._json(dict(error="não encontrado"), 404)
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", sniff(body))
            self.end_headers()
            self.wfile.write(body)
            return
        static = (paths.RESOURCES / "scripts" / "app" / "static").resolve()
        f = (static / path.removeprefix("/static/")).resolve() if path.startswith("/static/") else static / "index.html"
        if static not in f.parents or not f.is_file():  # barra '../' e arquivos inexistentes
            return self._json(dict(error="não encontrado"), 404)
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(f.suffix, "application/octet-stream"))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        url = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0))
        if url.path == "/api/voice/upload":
            q = parse_qs(url.query)
            try:
                set_voice(int(q["id"][0]), q["name"][0], self.rfile.read(n) if n <= 50 * 1024 * 1024 else b"")
            except (ValueError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if url.path in ("/api/photo/upload", "/api/music/upload"):
            q = parse_qs(url.query)
            try:
                lid, name = int(q["id"][0]), q["name"][0]
                data = self.rfile.read(n) if n <= 50 * 1024 * 1024 else b""
                if url.path == "/api/photo/upload":
                    add_photo(lid, data)
                else:
                    if Path(name).suffix.lower() not in AUDIO_EXT or not 0 < len(data) <= 50 * 1024 * 1024:
                        raise ValueError("envie um áudio .wav, .mp3, .m4a ou .ogg de até 50 MB")
                    d = PRODUCTS / str(lid) / "kit"
                    d.mkdir(parents=True, exist_ok=True)
                    for old in d.glob("musica.*"):
                        old.unlink()
                    (d / f"musica{Path(name).suffix.lower()}").write_bytes(data)
            except (ValueError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if url.path == "/api/model/upload":  # corpo bruto = o arquivo; id e nome vão na query
            q = parse_qs(url.query)
            if n > MAX_MODEL:
                return self._json(dict(error="arquivo maior que 200 MB"), 413)
            try:
                set_model(int(q["id"][0]), q["name"][0], self.rfile.read(n))
            except (ValueError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:  # JSON quebrado ou texto que não é UTF-8
            return self._json(dict(error="corpo da requisição inválido (esperado JSON em UTF-8)"), 400)
        path = url.path
        if path in ("/api/model", "/api/model/inbox"):
            try:
                if path == "/api/model":
                    set_model_meta(int(data["id"]), str(data.get("source_url", "")).strip(), str(data.get("license_note", "")).strip())
                elif data.get("name") in inbox_models():  # só nomes que existem em inbox/
                    set_model(int(data["id"]), data["name"], (INBOX / data["name"]).read_bytes())
                else:
                    raise ValueError("arquivo não está em inbox/")
            except (ValueError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path in ("/api/model/search", "/api/model/get", "/api/model/capture"):
            try:
                lid = int(data["id"])
                if lid not in {c["id"] for c in candidates()}:
                    raise ValueError("produto não encontrado")
                if MODEL_JOBS.get(lid, {}).get("status") == "running":
                    raise ValueError("já tem uma busca ou captura em andamento")
                profile = pick_profile(data.get("profile"))
                if path == "/api/model/search":
                    sites = [x for x in data.get("sites", list(model_search.SITES)) if x in model_search.SITES]
                    q = re.sub(r"\s+", " ", str(data.get("q", ""))).strip()[:100]
                    if len(q) < 2 or not sites:
                        raise ValueError("digite o que buscar")
                    if "headless" in data:
                        put_setting("browser_headless", bool(data["headless"]))
                    threading.Thread(target=run_model_search, args=(lid, q, profile, sites), daemon=True).start()
                elif path == "/api/model/get":
                    get_printables_model(lid, str(data["model_id"]), str(data["file_id"]), str(data.get("title", "")), str(data.get("url", "")), str(data.get("license", "")), model_info(data))
                else:
                    if not profile:
                        raise ValueError("escolha um perfil do Chrome no topo da tela")
                    threading.Thread(target=run_model_capture, args=(lid, str(data["url"]), profile, str(data.get("license", "")), str(data.get("source", ""))), daemon=True).start()
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path == "/api/business":
            try:
                set_business(data)
            except ValueError as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path == "/api/kit":
            try:
                set_kit(int(data["id"]), data)
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path == "/api/copy":
            with lock, db() as c:
                st = c.execute("SELECT status FROM steps WHERE listing_id=? AND name='copy'", (data.get("id"),)).fetchone()
                if not st or st["status"] == "running":
                    return self._json(dict(error="aprove o produto antes" if not st else "já está gerando"), 400)
                c.execute("UPDATE steps SET status='running' WHERE listing_id=? AND name='copy'", (data["id"],))
            threading.Thread(target=run_copy, args=(data["id"],), daemon=True).start()
            return self._json(dict(ok=True))
        if path == "/api/filtros":
            try:
                put_setting("filters", selecao.clean_filters(data))
            except (ValueError, TypeError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path == "/api/filtros/avaliar":
            try:
                lid = int(data["id"])
                if lid not in {c["id"] for c in candidates()}:
                    raise ValueError("produto não encontrado")
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            threading.Thread(target=lambda: eval_filters(lid), daemon=True).start()
            return self._json(dict(ok=True))
        if path == "/api/tese/propor":
            try:
                lid = int(data["id"])
                if lid not in {c["id"] for c in candidates()}:
                    raise ValueError("produto não encontrado")
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            threading.Thread(target=propose_tese, args=(lid,), daemon=True).start()
            return self._json(dict(ok=True))
        if path == "/api/tese":
            try:
                lid = int(data["id"])
                put_setting(f"tese:{lid}", selecao.clean_thesis(data) | dict(status="ok", msg="", proposta=False))
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path == "/api/listing/created":
            try:
                set_created(int(data["id"]), data.get("created", ""))
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path in ("/api/costs", "/api/price"):
            try:
                set_costs(data) if path == "/api/costs" else set_price(int(data["id"]), data["price"])
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=f"valor inválido: {e}"), 400)
            return self._json(dict(ok=True))
        if path == "/api/shopee/done":  # a Shopee é publicada por você; aqui só se registra o link
            try:
                mark_shopee(int(data["id"]), str(data.get("url", "")).strip())
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path in ("/api/ml/config", "/api/ml/code", "/api/ml/validate", "/api/ml/publish"):
            try:
                if path == "/api/ml/config":
                    ml.save_credentials(str(data.get("client_id", "")).strip(), str(data.get("client_secret", "")).strip())
                elif path == "/api/ml/code":
                    ml.exchange_code(str(data.get("code", "")))
                else:
                    args = (int(data["id"]), data.get("category_id"), data.get("attributes"), int(data.get("quantity", 5)))
                    if path == "/api/ml/validate":
                        ml.validate(ml_item(*args)[1])
                    else:
                        ext_id, link = ml_publish(*args)
                        return self._json(dict(ok=True, external_id=ext_id, url=link))
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path == "/api/tools/install":
            name = str(data.get("name", ""))
            if name not in tools_installer.MANIFEST:
                return self._json(dict(error="ferramenta desconhecida"), 400)
            if any(j.get("status") == "running" for j in TOOL_JOBS.values()):
                return self._json(dict(error="já tem um download em andamento"), 400)
            threading.Thread(target=run_tool_install, args=(name,), daemon=True).start()
            return self._json(dict(ok=True))
        if path == "/api/browser":
            put_setting("browser_headless", bool(data.get("headless")))
            return self._json(dict(headless=browser_headless()))
        if path == "/api/open":
            try:
                profile = pick_profile(data.get("profile"))
                open_url(str(data.get("url", "")), profile if data.get("chrome") else None)
            except ValueError as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path == "/api/model/suggest":
            try:
                return self._json(dict(terms=suggest_terms(str(data.get("title", "")))))
            except Exception as e:
                return self._json(dict(error=str(e)[:200]), 400)
        if path == "/api/restart":
            threading.Timer(0.5, run_restart).start()  # responde antes de fechar
            return self._json(dict(ok=True))
        if path == "/api/update/apply":
            info = update_check()
            if not paths.FROZEN:  # do código: puxa do GitHub e reinicia
                try:
                    git_pull()
                except ValueError as e:
                    return self._json(dict(error=str(e)), 400)
                _UPDATE_CHECK["data"] = None
                threading.Timer(0.5, run_restart).start()
                return self._json(dict(ok=True, restart=True))
            if not info.get("newer") or not info.get("asset_url"):
                return self._json(dict(error="não há atualização para instalar"), 400)
            if UPDATE_JOB["status"] in ("running", "installing"):
                return self._json(dict(error="a atualização já está em andamento"), 400)
            threading.Thread(target=run_update, args=(info,), daemon=True).start()
            return self._json(dict(ok=True))
        if path in ("/api/simulate", "/api/onboarding"):
            try:
                return self._json(run_simulation(data) if path == "/api/simulate" else set_onboarding(data))
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
        if path in ("/api/media/config", "/api/media/order", "/api/photo/delete"):
            try:
                if path == "/api/media/config":
                    if "render" in data:
                        put_setting("render_cfg", renderizar.clean_render_cfg(data["render"]))
                    if "video" in data:
                        put_setting("video_cfg", videos.clean_video_cfg(data["video"]))
                elif path == "/api/media/order":
                    set_media(int(data["id"]), data.get("order", []), data.get("hidden", []))
                else:
                    del_photo(int(data["id"]), str(data["name"]))
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path == "/api/auto":
            try:
                lid = int(data["id"])
                color = str(data.get("color", "#3a3a3a"))
                if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                    raise ValueError("cor inválida")
                cand = next((c for c in candidates() if c["id"] == lid), None)
                if not cand:
                    raise ValueError("produto não encontrado")
                if not (cand["model"] or {}).get("file_path"):
                    raise ValueError("falta o arquivo do modelo 3D")
                if AUTO.get(lid, {}).get("status") == "running" or "running" in cand["steps"].values():
                    raise ValueError("já tem uma etapa em andamento")
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            threading.Thread(target=run_auto, args=(lid,), daemon=True).start()
            return self._json(dict(ok=True))
        if path == "/api/video":
            with lock, db() as c:
                st = c.execute("SELECT status FROM steps WHERE listing_id=? AND name='video'", (data.get("id"),)).fetchone()
                if not st or st["status"] == "running":
                    return self._json(dict(error="aprove o produto antes" if not st else "já está gerando"), 400)
                c.execute("UPDATE steps SET status='running' WHERE listing_id=? AND name='video'", (data["id"],))
            threading.Thread(target=run_video, args=(data["id"],), daemon=True).start()
            return self._json(dict(ok=True))
        if path == "/api/kit/confirm":
            try:
                confirm_kit(int(data["id"]))
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path == "/api/render":
            try:
                cfg = renderizar.clean_render_cfg(data.get("cfg") or dict(color=str(data.get("color", "#3a3a3a"))))
            except (ValueError, TypeError) as e:
                return self._json(dict(error=str(e)), 400)
            put_setting("render_cfg", cfg)
            with lock, db() as c:
                st = c.execute("SELECT status FROM steps WHERE listing_id=? AND name='images'", (data.get("id"),)).fetchone()
                if not st or st["status"] == "running":
                    return self._json(dict(error="aprove o produto antes" if not st else "já está gerando"), 400)
                c.execute("UPDATE steps SET status='running' WHERE listing_id=? AND name='images'", (data["id"],))
            threading.Thread(target=run_images, args=(data["id"], cfg), daemon=True).start()
            return self._json(dict(ok=True))
        if path == "/api/slice":
            with lock, db() as c:
                st = c.execute("SELECT status FROM steps WHERE listing_id=? AND name='slice'", (data.get("id"),)).fetchone()
                if not st:
                    return self._json(dict(error="aprove o produto antes de fatiar"), 400)
                if st["status"] == "running":
                    return self._json(dict(error="já está fatiando"), 400)
                c.execute("UPDATE steps SET status='running' WHERE listing_id=? AND name='slice'", (data["id"],))
            threading.Thread(target=run_slice, args=(data["id"],), daemon=True).start()
            return self._json(dict(ok=True))
        if path == "/api/profile/open":
            try:
                store_reader_open(str(data.get("profile", "")), str(data.get("url", "")))
            except (ValueError, OSError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path == "/api/stores/remove":
            try:
                remove_store(int(data["id"]))
            except (ValueError, TypeError, KeyError) as e:
                return self._json(dict(error=str(e)), 400)
            return self._json(dict(ok=True))
        if path == "/api/stores/info":
            if data.get("profile") not in list_profiles():
                return self._json(dict(error="escolha um perfil"), 400)
            with db() as c:
                ids = [r[0] for r in c.execute("SELECT id FROM stores")] if data.get("id") in (None, "all") else [int(data["id"])]
            threading.Thread(target=run_store_info, args=(ids, data["profile"]), daemon=True).start()
            return self._json(dict(started=len(ids)))
        if path == "/api/stores":
            profile = data.get("profile", "")
            if profile not in list_profiles():
                return self._json(dict(error="escolha um perfil"), 400)
            added = 0
            for u in data.get("urls", []):
                u = u.strip()
                plat = platform_of(u)
                if not plat:  # trust boundary: só Mercado Livre de verdade
                    continue
                with lock, db() as c:
                    row = c.execute("SELECT id, status FROM stores WHERE url=?", (u,)).fetchone()
                    if row and row["status"] in ("pending", "running", "captcha"):
                        continue  # já na fila
                    if row:  # reenvio (ex.: outro perfil) reaproveita a loja
                        sid = row["id"]
                        c.execute("UPDATE stores SET status='pending', msg='', profile=? WHERE id=?", (profile, sid))
                    else:
                        sid = c.execute("INSERT INTO stores(url, profile, platform) VALUES(?,?,?)", (u, profile, plat)).lastrowid
                threading.Thread(target=run_store, args=(sid, u, profile), daemon=True).start()
                added += 1
            return self._json(dict(added=added))
        if path == "/api/decide":
            status = data.get("status")
            if status not in ("approved", "discarded", "new"):
                return self._json(dict(error="status inválido"), 400)
            with lock, db() as c:
                c.execute("UPDATE listings SET status=? WHERE id=?", (status, data["id"]))
                if status == "approved":
                    c.executemany("INSERT OR IGNORE INTO steps(listing_id,name) VALUES(?,?)",
                                  [(data["id"], s) for s in STEPS])
            return self._json(dict(ok=True))
        self._json(dict(error="não encontrado"), 404)

    def log_message(self, *a):
        pass


def make_server(port=paths.PORT):
    """Prepara o banco e devolve o servidor HTTP (sem iniciar). O desktop.py instalado roda isto numa thread."""
    init()
    resume()
    return ThreadingHTTPServer(("127.0.0.1", port), H)


if __name__ == "__main__":
    print(f"http://localhost:{paths.PORT}")
    make_server().serve_forever()
