"""Seleção de produtos: o método do vídeo de Helton Gramari (ver docs/selecao-produtos.md), em funções puras e testáveis.
Filtros fixos antes do ranking, vendas por dia pela idade do anúncio, famílias de produtos e funil de abrir e fechar."""
import math
import re
import struct
from datetime import date, datetime
from pathlib import Path

DEFAULT_FILTERS = dict(
    printers=[dict(name="Bambu Lab A1 Mini", x=180, y=180, z=180)], printer="Bambu Lab A1 Mini",
    max_hours=4.0,           # tempo máximo de impressão por peça
    min_thickness_mm=1.6,    # abaixo disto a espessura média do STL acende o aviso de fragilidade (não bloqueia)
    allow_support=False,     # produto que precisa de suporte de impressão é reprovado
    max_colors=1,            # número de cores aceito
    allow_assembly=False,    # produto que pede montagem ou acabamento é reprovado
    stock_colors=[],         # cores de filamento em estoque; vazio = qualquer cor
    champion_per_day=1.0,    # campeão: mais que isto de unidades vendidas por dia
)
LABELS = dict(max_hours="Tempo máximo de impressão (horas)", min_thickness_mm="Espessura média mínima (mm) para não avisar fragilidade",
              max_colors="Número máximo de cores", champion_per_day="Campeão: unidades por dia acima de")

COLOR_WORDS = {"preto": "preto", "preta": "preto", "branco": "branco", "branca": "branco", "azul": "azul", "vermelho": "vermelho", "vermelha": "vermelho", "verde": "verde",
               "amarelo": "amarelo", "amarela": "amarelo", "rosa": "rosa", "cinza": "cinza", "laranja": "laranja", "roxo": "roxo", "roxa": "roxo", "marrom": "marrom",
               "dourado": "dourado", "dourada": "dourado", "prata": "prata", "prateado": "prata", "bege": "bege", "madeira": "madeira", "transparente": "transparente"}
MULTI_WORDS = ("colorido", "coloridos", "multicolor", "multicor", "arco-íris", "arco iris", "várias cores", "varias cores", "cores sortidas", "cores variadas", "gradiente")
ASSEMBLY_RX = re.compile(r"\b(para montar|a montar|montagem|montável|montavel|desmontável para montar|parafusos?|colar|colagem|lixar|lixado para pintar|pintar você|acabamento manual|peças separadas|pecas separadas|encaixar peças)\b", re.I)


def clean_filters(d):
    """Valida o que veio da tela e completa com o padrão. Levanta ValueError com o motivo."""
    f = DEFAULT_FILTERS | {k: v for k, v in (d or {}).items() if k in DEFAULT_FILTERS}
    printers = []
    for p in f["printers"] if isinstance(f["printers"], list) else []:
        try:
            x, y, z = (float(p[k]) for k in "xyz")
        except (KeyError, TypeError, ValueError):
            raise ValueError("impressora com volume inválido")
        name = str(p.get("name", "")).strip()[:60]
        if not name or not all(30 <= v <= 2000 for v in (x, y, z)):
            raise ValueError("cada impressora precisa de nome e volume entre 30 e 2000 mm")
        printers.append(dict(name=name, x=x, y=y, z=z))
    if not printers:
        raise ValueError("cadastre pelo menos uma impressora")
    if f["printer"] not in [p["name"] for p in printers]:
        raise ValueError("a impressora escolhida não está na lista")
    try:
        max_hours, thick, colors, champ = float(f["max_hours"]), float(f["min_thickness_mm"]), int(f["max_colors"]), float(f["champion_per_day"])
    except (TypeError, ValueError):
        raise ValueError("número inválido nos filtros")
    if not (0.1 <= max_hours <= 200 and 0 <= thick <= 50 and 1 <= colors <= 16 and 0 <= champ <= 1000):
        raise ValueError("valor fora do intervalo nos filtros")
    stock = [norm_color(c) for c in (f["stock_colors"] if isinstance(f["stock_colors"], list) else str(f["stock_colors"]).split(",")) if str(c).strip()]
    return dict(printers=printers, printer=f["printer"], max_hours=max_hours, min_thickness_mm=thick, allow_support=bool(f["allow_support"]), max_colors=colors,
                allow_assembly=bool(f["allow_assembly"]), stock_colors=list(dict.fromkeys(stock)), champion_per_day=champ)


def norm_color(c):
    c = str(c).strip().lower()
    return COLOR_WORDS.get(c, c)


def printer_of(f):
    return next(p for p in f["printers"] if p["name"] == f["printer"])


def listing_checks(title, f):
    """Filtros que dá para aplicar só com o anúncio (antes de existir modelo): cores e montagem. Devolve (motivos de reprovação, avisos)."""
    t = " " + (title or "").lower() + " "
    reasons, warnings = [], []
    found = []
    for w in re.findall(r"[a-zçãéíóú\-]+", t):
        c = COLOR_WORDS.get(w)
        if c and c not in found:
            found.append(c)
    multi = any(m in t for m in MULTI_WORDS)
    n = max(len(found), 2 if multi else 0)
    if n > f["max_colors"]:
        reasons.append(f"mais de {f['max_colors']} cor no anúncio ({', '.join(found) if found else 'colorido'})")
    if f["stock_colors"] and found and not multi and not any(c in f["stock_colors"] for c in found):
        reasons.append(f"cor fora do estoque de filamento ({', '.join(found)})")
    m = ASSEMBLY_RX.search(t)
    if m and not f["allow_assembly"]:
        reasons.append(f"pede montagem ou acabamento (“{m.group(1)}” no título)")
    return reasons, warnings


# ---------- malha: medidas, volume, espessura média ----------
def read_triangles(path):
    """Triângulos [(v1, v2, v3)] de um STL binário ou ASCII, em mm. shortcut: sem unidades (STL não tem), assume mm."""
    data = Path(path).read_bytes()
    tris = []
    if data[:5] == b"solid" and b"facet" in data[:400]:
        pts = [tuple(float(x) for x in m) for m in re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)]
        tris = [tuple(pts[i:i + 3]) for i in range(0, len(pts) - 2, 3)]
    else:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + n * 50 > len(data):
            raise ValueError("STL binário truncado")
        for k in range(n):
            o = 84 + k * 50 + 12
            tris.append(tuple(struct.unpack("<3f", data[o + 12 * j:o + 12 * j + 12]) for j in range(3)))
    if not tris:
        raise ValueError("o arquivo não tem nenhum triângulo")
    return tris


def mesh_stats(path):
    """dims (maior para menor, mm), volume (mm³), área de superfície (mm²), espessura média ≈ 2·volume/área (uma chapa de espessura t tem V = A·t e S ≈ 2A)
    e esbeltez (maior dimensão / espessura média). Também a área voltada para baixo e acima do plano da mesa, para o aviso de suporte sem fatiar."""
    tris = read_triangles(path)
    xs, ys, zs = zip(*[v for t in tris for v in t])
    dims = sorted((max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)), reverse=True)
    vol = area = overhang = 0.0
    zmin = min(zs)
    for a, b, c in tris:
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        two_a = math.sqrt(nx * nx + ny * ny + nz * nz)
        area += two_a / 2
        vol += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6
        if two_a > 0 and nz / two_a < -0.7071 and min(a[2], b[2], c[2]) > zmin + 0.6:  # parede que "pende" a mais de 45° e não toca a mesa
            overhang += two_a / 2
    vol = abs(vol)
    thick = 2 * vol / area if area else 0.0
    return dict(dims=[round(d, 1) for d in dims], volume=round(vol, 1), area=round(area, 1), thickness=round(thick, 2),
                slender=round(dims[0] / thick, 1) if thick else None, overhang_area=round(overhang, 1), overhang_pct=round(100 * overhang / area, 1) if area else 0.0)


def model_checks(stats, minutes, support, f):
    """Filtros que dependem do modelo e do fatiamento. stats: mesh_stats; minutes: do fatiamento (ou None); support: True/False/None (None = não testado).
    Devolve (motivos de reprovação, avisos, pendências)."""
    reasons, warnings, pending = [], [], []
    p = printer_of(f)
    vol = sorted((p["x"], p["y"], p["z"]), reverse=True)
    if stats:
        d = stats["dims"]
        if any(a > b + 0.01 for a, b in zip(d, vol)):
            reasons.append(f"não cabe na {p['name']} (peça {d[0]:g} × {d[1]:g} × {d[2]:g} mm, mesa {vol[0]:g} × {vol[1]:g} × {vol[2]:g} mm)")
        if 0 < stats["thickness"] < f["min_thickness_mm"] or (stats["slender"] or 0) > 60:
            warnings.append(f"risco de fragilidade: espessura média de {stats['thickness']:g} mm (limite {f['min_thickness_mm']:g}) e peça {stats['slender']:g}× mais comprida que grossa")
    else:
        pending.append("medidas do modelo")
    if minutes is not None:
        if minutes > f["max_hours"] * 60:
            reasons.append(f"imprime em {minutes // 60} h {minutes % 60:02d} min, acima do limite de {f['max_hours']:g} h")
    else:
        pending.append("tempo de impressão")
    if support is True and not f["allow_support"]:
        reasons.append("precisa de suporte de impressão")
    elif support is None:
        pending.append("teste de suporte")
    return reasons, warnings, pending


def evaluate(title, f, stats=None, minutes=None, support=None):
    """Resultado único para a tela: status 'reprovado' (com motivos), 'aprovado' (tudo testado e ok) ou 'pendente' (nada reprovou, mas falta testar)."""
    r1, w1 = listing_checks(title, f)
    r2, w2, pend = model_checks(stats, minutes, support, f)
    reasons = r1 + r2
    return dict(status="reprovado" if reasons else "pendente" if pend else "aprovado", reasons=reasons, warnings=w1 + w2, pending=pend)


# ---------- vendas por dia ----------
def age_days(created, today=None):
    """Dias desde a publicação (ISO 'AAAA-MM-DD...'). None se a data é desconhecida ou inválida (ou no futuro)."""
    try:
        d = datetime.fromisoformat(str(created)[:10]).date()
    except ValueError:
        return None
    n = ((today or date.today()) - d).days
    return n if n >= 0 else None


def sales_per_day(sold, created, today=None):
    """Vendas por dia = vendidos / idade do anúncio em dias (mínimo 1). None sem a data de publicação."""
    n = age_days(created, today)
    return None if n is None or sold is None else round(sold / max(n, 1), 2)


def is_champion(spd, f):
    return spd is not None and spd > f["champion_per_day"]


def compare_similar(rows):
    """Compara anúncios parecidos de idades diferentes. rows: [{id, title, sold, created}]. Para cada um: vendas por dia, idade e o veredito do vídeo:
    antigo com muita venda = o produto se sustenta; novo com venda menor = a demanda ainda existe."""
    out = []
    for r in rows:
        spd, age = sales_per_day(r.get("sold"), r.get("created")), age_days(r.get("created"))
        out.append(dict(id=r["id"], title=r.get("title", ""), sold=r.get("sold"), age_days=age, per_day=spd, note=""))
    known = [o for o in out if o["per_day"] is not None]
    if known:
        oldest, newest = max(known, key=lambda o: o["age_days"]), min(known, key=lambda o: o["age_days"])
        for o in known:
            o["note"] = ("se sustenta há muito tempo" if o is oldest and o["age_days"] >= 365 and o["per_day"] >= 0.3
                         else "demanda ainda viva" if o is newest and o is not oldest and o["per_day"] >= 0.3 else "")
    return sorted(out, key=lambda o: -(o["per_day"] or -1))


# ---------- anúncios parecidos ----------
STOP = set("de da do das dos para com sem em e a o as os um uma por no na nos nas ao à se que kit unidade unidades peça peças pç pcs 3d impressão impressao impresso".split())


def tokens(title):
    return {w for w in re.findall(r"[a-zà-ú0-9]+", (title or "").lower()) if len(w) > 2 and w not in STOP}


def similarity(a, b):
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def similar_rows(me, cands, min_sim=0.34):
    """O produto e os outros anúncios lidos com título parecido (mesma dor), para comparar idades e preços. Cada linha: id, title, sold, created, price, sim."""
    out = []
    for c in cands:
        sim = 1.0 if c["id"] == me["id"] else similarity(me["title"], c["title"])
        if sim >= min_sim:
            out.append(dict(id=c["id"], title=c["title"], sold=c.get("sold"), created=c.get("created", ""), price=c.get("price"), sim=round(sim, 2)))
    return out


def price_band(rows, me_id=None):
    """Faixa de preço dos concorrentes (os parecidos, sem o próprio produto): mínimo, mediana e máximo. None se não há outro com preço."""
    prices = sorted(r["price"] for r in rows if r.get("price") and r["id"] != me_id)
    if not prices:
        return None
    mid = prices[len(prices) // 2] if len(prices) % 2 else (prices[len(prices) // 2 - 1] + prices[len(prices) // 2]) / 2
    return dict(min=prices[0], median=round(mid, 2), max=prices[-1], n=len(prices))


# ---------- tese do produto: dor, faixa de preço, similares ----------
def ask_claude(prompt, workdir):
    """`claude -p` com a ferramenta Read (para ver a foto do anúncio). Levanta ValueError com o motivo."""
    import proc
    import texto
    r = proc.run([texto._cmd(), "-p", "--allowedTools", "Read", "--add-dir", str(workdir)], input=prompt, capture_output=True, text=True, timeout=300, encoding="utf-8")
    if r.returncode != 0:
        raise ValueError(f"o Claude retornou erro: {(r.stderr or r.stdout)[:200]}")
    return r.stdout


def thesis_prompt(title, photo, similar_titles):
    outros = "\n".join(f"- {t[:90]}" for t in similar_titles[:8]) or "- (nenhum outro anúncio parecido lido ainda)"
    return f"""Use a ferramenta Read para ver a imagem {photo}: é a foto de um anúncio de venda de um produto impresso em 3D: «{title[:120]}».
Outros anúncios parecidos já lidos:
{outros}

Escreva a TESE do produto em duas partes:
1. "dor": a dor ou necessidade do cliente que o produto resolve, em UMA frase em português, concreta (quem sente, em que situação).
2. "similares": de 4 a 6 TIPOS de produto parecidos que resolvem a mesma dor (nome genérico em português, com um termo curto de busca para o Mercado Livre). Não invente marcas nem anúncios.
Responda SOMENTE com JSON: {{"dor": "...", "similares": [{{"nome": "...", "busca": "..."}}]}}"""


def parse_thesis(text):
    import json
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("a resposta do Claude não trouxe JSON")
    try:
        d = json.loads(m.group(0))
        dor = re.sub(r"\s*—\s*", ", ", re.sub(r"\s+", " ", str(d["dor"]))).strip()[:300]
        sim = [dict(nome=re.sub(r"\s+", " ", str(s["nome"])).strip()[:80], busca=re.sub(r"\s+", " ", str(s.get("busca", s["nome"]))).strip()[:60]) for s in d["similares"] if str(s.get("nome", "")).strip()]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("o JSON da tese veio quebrado")
    if not dor or not sim:
        raise ValueError("a tese veio sem a dor ou sem similares")
    return dict(dor=dor, similares=sim[:6])


def propose_thesis(title, photo, similar_titles, ask=ask_claude):
    """O Claude propõe a dor e os tipos de produto parecidos a partir da foto e dos títulos; a pessoa edita depois."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        from PIL import Image
        jpg = Path(tmp) / "anuncio.jpg"
        im = Image.open(photo).convert("RGB")
        im.thumbnail((640, 640))
        im.save(jpg, quality=88)
        return parse_thesis(ask(thesis_prompt(title, jpg, similar_titles), tmp))


def clean_thesis(d):
    """Valida a tese editada na tela. faixa: preços mínimo e máximo que o cliente aceita pagar (R$) ou vazio."""
    try:
        lo = float(d["faixa_min"]) if str(d.get("faixa_min", "")).strip() else None
        hi = float(d["faixa_max"]) if str(d.get("faixa_max", "")).strip() else None
    except (TypeError, ValueError):
        raise ValueError("faixa de preço inválida")
    if (lo is not None and lo < 0) or (hi is not None and hi < 0) or (lo is not None and hi is not None and lo > hi):
        raise ValueError("a faixa de preço precisa ter mínimo menor que o máximo")
    sim = []
    for s in d.get("similares", []):
        nome, busca = str(s.get("nome", "")).strip()[:80], str(s.get("busca", "")).strip()[:60]
        if nome:
            sim.append(dict(nome=nome, busca=busca or nome))
    return dict(dor=str(d.get("dor", "")).strip()[:300], faixa_min=lo, faixa_max=hi, similares=sim[:10])


# ---------- famílias: mesma dor, peso parecido ----------
def weight_ok(a, b, tol=0.4):
    """Pesos compatíveis (gramas) a menos de tol de diferença; se um deles é desconhecido, não atrapalha."""
    return not (a and b) or abs(a - b) / max(a, b) <= tol


def families(cands, min_sim=0.34, pain_sim=0.5):
    """Agrupa candidatos que resolvem a mesma dor: título parecido ou dores parecidas na tese, e peso parecido quando se sabe.
    cands: [{id, title, status, grams, price, score, tese}]. Devolve famílias com 2 ou mais produtos, as maiores primeiro.
    Cada uma traz as variações sugeridas: os tipos de produto parecidos da tese que ainda não existem na família."""
    cs = [c for c in cands if c.get("status") != "discarded"]
    parent = {c["id"]: c["id"] for c in cs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, a in enumerate(cs):
        for b in cs[i + 1:]:
            da, db_ = (a.get("tese") or {}).get("dor", ""), (b.get("tese") or {}).get("dor", "")
            same = similarity(a["title"], b["title"]) >= min_sim or (da and db_ and similarity(da, db_) >= pain_sim)
            if same and weight_ok(a.get("grams"), b.get("grams")):
                parent[find(a["id"])] = find(b["id"])
    groups = {}
    for c in cs:
        groups.setdefault(find(c["id"]), []).append(c)
    out = []
    for g in groups.values():
        if len(g) < 2:
            continue
        titles = [c["title"] for c in g]
        grams = [c["grams"] for c in g if c.get("grams")]
        sugg, seen = [], []
        for c in g:
            for s in (c.get("tese") or {}).get("similares", []):
                if all(similarity(s["nome"], t) < min_sim for t in titles) and s["nome"] not in seen:
                    seen.append(s["nome"])
                    sugg.append(dict(nome=s["nome"], busca=s.get("busca", s["nome"])))
        pain = next(((c.get("tese") or {}).get("dor") for c in g if (c.get("tese") or {}).get("dor")), "")
        out.append(dict(id=min(c["id"] for c in g), members=sorted(c["id"] for c in g), titles=titles, pain=pain, grams=[min(grams), max(grams)] if grams else None,
                        price=price_band([dict(id=c["id"], price=c.get("price")) for c in g]), best_score=max(c.get("score", 0) for c in g), variations=sugg[:6]))
    return sorted(out, key=lambda f: (-len(f["members"]), -f["best_score"]))


# ---------- funil de abrir e fechar ----------
FUNNEL_OPEN = (5, 10)     # candidatos abertos
FUNNEL_PICK = (3, 5)      # escolhidos para imprimir a amostra


def clean_funnel(d, known_ids):
    """Valida o funil vindo da tela: ids conhecidos, escolhidos dentro dos abertos, no máximo 10 e 5. Devolve (funil, avisos de contagem)."""
    lista = list(dict.fromkeys(int(i) for i in d.get("lista", [])))
    esc = [i for i in dict.fromkeys(int(i) for i in d.get("escolhidos", [])) if i in lista]
    if any(i not in known_ids for i in lista):
        raise ValueError("produto desconhecido na lista")
    if len(lista) > FUNNEL_OPEN[1]:
        raise ValueError(f"a lista aberta aceita no máximo {FUNNEL_OPEN[1]} candidatos")
    if len(esc) > FUNNEL_PICK[1]:
        raise ValueError(f"escolha no máximo {FUNNEL_PICK[1]} para a amostra")
    dec = {str(k): v for k, v in (d.get("decisoes") or {}).items() if v in ("mantem", "sai") and int(k) in esc}
    warn = []
    if lista and len(lista) < FUNNEL_OPEN[0]:
        warn.append(f"abra de {FUNNEL_OPEN[0]} a {FUNNEL_OPEN[1]} candidatos (tem {len(lista)})")
    if esc and len(esc) < FUNNEL_PICK[0]:
        warn.append(f"escolha de {FUNNEL_PICK[0]} a {FUNNEL_PICK[1]} para a amostra (tem {len(esc)})")
    return dict(lista=lista, escolhidos=esc, decisoes=dec), warn


def perf_summary(points, margin_pct, target_pct, min_days=14, min_per_day=0.2):
    """Desempenho depois de publicado. points: [{ts 'AAAA-MM-DD...', sold}] (vendas acumuladas do anúncio). Sugere mantém / sai / espera:
    com pelo menos min_days de venda, mantém se vende e a margem está na meta; sai se não vende ou se a margem fica abaixo da meta."""
    pts = sorted((p for p in points if p.get("ts") and p.get("sold") is not None), key=lambda p: p["ts"])
    if len(pts) < 2:
        return dict(days=0, sold=pts[-1]["sold"] if pts else None, per_day=None, suggestion="espera", why="faltam leituras de vendas (precisa de pelo menos duas)")
    d0, d1 = datetime.fromisoformat(pts[0]["ts"][:10]).date(), datetime.fromisoformat(pts[-1]["ts"][:10]).date()
    days, sold = (d1 - d0).days, pts[-1]["sold"] - pts[0]["sold"]
    per_day = round(sold / days, 2) if days else None
    if days < min_days:
        return dict(days=days, sold=sold, per_day=per_day, suggestion="espera", why=f"só {days} dias de venda; espere {min_days}")
    if margin_pct is not None and margin_pct < target_pct:
        return dict(days=days, sold=sold, per_day=per_day, suggestion="sai", why=f"margem de {margin_pct:g}% abaixo da meta de {target_pct:g}%")
    if (per_day or 0) < min_per_day:
        return dict(days=days, sold=sold, per_day=per_day, suggestion="sai", why=f"{per_day} vendas por dia, abaixo de {min_per_day:g}")
    return dict(days=days, sold=sold, per_day=per_day, suggestion="mantem", why="vende e dá a margem esperada")
