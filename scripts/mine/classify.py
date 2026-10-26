import re

PRINT_MATERIALS = re.compile(r"\b(pla|petg|tpu|resina)\b", re.I)  # ABS fica fora: também é plástico injetado
PRINT_WORDS = re.compile(r"impress[aã]o 3d|impresso em 3d|filamento|camadas|3d print", re.I)


def parse_sold(text):
    """'+100 vendidos' -> 100; '3 vendidos' -> 3; sem informação -> 0."""
    m = re.search(r"(?:\+\s*)?(\d[\d.]*)\s*(mil)?\s+vendidos?", text, re.I)
    if not m:
        return 0
    n = int(m.group(1).replace(".", ""))
    return n * 1000 if m.group(2) else n


def parse_reviews(text):
    m = re.search(r"(\d[\d.]*)\s+(?:avalia[cç][õo]es|opini[õo]es)", text, re.I)
    return int(m.group(1).replace(".", "")) if m else 0


def parse_price(text):
    """O ML quebra o preço em linhas ('R$\\n22\\n,\\n90'); com desconto vêm dois preços seguidos, vale o menor."""
    ms = list(re.finditer(r"R\$\s*([\d.]+)(?:\s*,\s*(\d{2}))?", text))
    if not ms:
        return None
    val = lambda m: float(m.group(1).replace(".", "") + "." + (m.group(2) or "00"))
    best = val(ms[0])
    if len(ms) > 1 and ms[1].start() - ms[0].end() < 30:
        best = min(best, val(ms[1]))
    return best


def parse_material(text):
    m = re.search(r"Material\s*\n?\s*([^\n]{1,40})", text)
    return m.group(1).strip() if m else ""


def is_3d(material, text):
    """Ficha técnica é o sinal forte; texto livre só confirma. shortcut: regex, trocar por Haiku se errar muito."""
    return int(bool(PRINT_MATERIALS.search(material)) or bool(PRINT_WORDS.search(text)))


def score(sold, reviews, price, is3d, rank, growth=0):
    """Maior = melhor. Pesos de chute inicial, ajustar com dados reais."""
    if not is3d:
        return 0.0
    s = min(sold, 1000) ** 0.5 * 2 + min(reviews, 500) ** 0.5 + growth * 3
    s += max(0, 10 - rank) * 0.5
    if price is not None and not 20 <= price <= 55:  # faixa de docs/founder/pricing.md
        s *= 0.6
    return round(s, 1)


def _num(s, mil=None):
    n = float(s.replace(".", "").replace(",", "."))
    return int(n * 1000) if mil else int(n)


def parse_store_info(text):
    """Dados públicos da página da loja, só o que o texto traz; o que faltar fica vazio. shortcut: regex sobre o texto da página, ajustar com páginas reais."""
    t = text[:6000]
    info = {}
    m = re.search(r"MercadoL[ií]der\s*(Platinum|Gold|Ouro|Prata)?", t, re.I)
    if m:
        info["reputation"] = ("MercadoLíder " + (m.group(1) or "")).strip()
    m = re.search(r"\+\s*(\d[\d.,]*)\s*(mil)?\s+vendas", t, re.I) or re.search(r"(\d[\d.,]*)\s*(mil)?\s+vendas", t, re.I)
    if m:
        info["sales"] = _num(m.group(1), m.group(2))
    m = re.search(r"(\d[\d.,]*)\s*(mil)?\s+seguidores", t, re.I)
    if m:
        info["followers"] = _num(m.group(1), m.group(2))
    m = re.search(r"\b([1-5][.,]\d)\s*(?:/\s*5|estrelas?)", t, re.I)
    if m:
        info["rating"] = float(m.group(1).replace(",", "."))
    m = re.search(r"Localiza[cç][aã]o\s*:?\s*\n?\s*([^\n]{2,60})", t)
    if m:
        info["location"] = m.group(1).strip()
    m = re.search(r"(?:Vende|Vendendo|Na plataforma)[^\n]{0,20}?(?:h[aá]|desde)\s+([^\n]{2,40})", t, re.I)
    if m:
        info["since_text"] = m.group(1).strip()
    return info
