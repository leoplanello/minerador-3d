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
