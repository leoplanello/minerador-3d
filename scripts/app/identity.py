"""Nota de identidade: o modelo 3D candidato é o mesmo produto das fotos do anúncio?
O Claude (`claude -p`, com a ferramenta Read para ver as imagens) compara as fotos do anúncio com a prévia de cada candidato."""
import io
import json
import re
import tempfile
import urllib.request
from pathlib import Path

import proc
import texto

THRESHOLD = 85  # só aceita sozinho com nota igual ou maior; abaixo disso a pessoa decide
MAX_CANDIDATES = 10
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def save_jpg(data, dst):
    """Qualquer imagem (JPG, PNG, WEBP, .img do ML) vira JPG de até 640 px: o Claude lê menos pixels e a conversa fica mais rápida."""
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((640, 640))
    im.save(dst, quality=88)
    return dst


def download(url, dst):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return save_jpg(urllib.request.urlopen(req, timeout=15).read(3_000_000), dst)


def build_prompt(title, ad_paths, cands):
    ads = "\n".join(f"- A{i}: {p}" for i, p in enumerate(ad_paths, 1))
    cs = "\n".join(f"- C{i}: {p}  (título do modelo: {c['title'][:90]})" for i, (c, p) in enumerate(cands, 1))
    return f"""Use a ferramenta Read para ver cada imagem abaixo. Anúncio de venda: «{title[:120]}».
Fotos do anúncio (o produto que queremos imprimir em 3D):
{ads}
Prévias dos modelos 3D candidatos:
{cs}

Para cada candidato dê uma nota de identidade de 0 a 100: 100 = é o mesmo produto (mesma forma, proporções e detalhes marcantes);
70 a 84 = muito parecido, mas com diferença visível; abaixo de 60 = outro produto da mesma categoria. Compare a FORMA, não a cor nem o fundo da foto.
Se a prévia for só um render genérico ou não der para saber, dê nota baixa e diga isso. Seja rigoroso: parecido não é idêntico.
Responda SOMENTE com JSON: {{"candidatos": [{{"id": "C1", "nota": 0, "motivo": "uma frase em português"}}]}}"""


def parse_reply(text, n):
    """{indice: {score, reason}}; o que o Claude não devolveu fica de fora. Levanta ValueError se não vier JSON."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("a resposta do Claude não trouxe JSON")
    try:
        items = json.loads(m.group(0))["candidatos"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise ValueError("o JSON da comparação veio quebrado")
    if not isinstance(items, list):
        raise ValueError("o JSON da comparação veio quebrado")
    out = {}
    for it in items:
        k = re.fullmatch(r"C(\d+)", str(it.get("id", "")))
        try:
            score = max(0, min(100, int(it["nota"])))
        except (KeyError, TypeError, ValueError):
            continue
        if k and 1 <= int(k.group(1)) <= n:
            out[int(k.group(1)) - 1] = dict(score=score, reason=str(it.get("motivo", "")).replace("—", ",").strip()[:240])
    return out


def ask_claude(prompt, workdir):
    r = proc.run([texto._cmd(), "-p", "--allowedTools", "Read", "--add-dir", str(workdir)], input=prompt, capture_output=True, text=True, timeout=300, encoding="utf-8")
    if r.returncode != 0:
        raise ValueError(f"o Claude retornou erro: {(r.stderr or r.stdout)[:200]}")
    return r.stdout


def verdict(results):
    """(índice do melhor, 'identico' | 'sem_identico'). Só vale 'identico' com nota >= THRESHOLD e licença que não proíbe o uso comercial."""
    ok = [(r["identity"]["score"], i) for i, r in enumerate(results) if r.get("identity") and r.get("commercial") is not False]
    best = max(ok, default=None)
    return (best[1], "identico") if best and best[0] >= THRESHOLD else (best[1] if best else None, "sem_identico")


def score_candidates(title, ad_images, results, ask=ask_claude):
    """ad_images: caminhos de imagens do anúncio. results: lista de resultados da busca (com 'thumb'); recebe 'identity' em cada um comparado.
    Devolve (índice do melhor, veredito). Candidatos sem prévia não são comparados."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ads = [save_jpg(Path(p).read_bytes(), tmp / f"anuncio{i}.jpg") for i, p in enumerate(ad_images, 1)]
        cands = []
        for r in results:
            if len(cands) >= MAX_CANDIDATES or not r.get("thumb", "").startswith("https://"):
                continue
            try:
                cands.append((r, download(r["thumb"], tmp / f"cand{len(cands) + 1}.jpg")))
            except Exception:
                continue  # sem prévia legível, sem nota
        if not ads or not cands:
            raise ValueError("faltam fotos para comparar (anúncio ou prévias dos modelos)")
        scores = parse_reply(ask(build_prompt(title, ads, cands), tmp), len(cands))
        for i, (r, _) in enumerate(cands):
            if i in scores:
                r["identity"] = scores[i]
    return verdict(results)


def visual_prompt(title, photo):
    return f"""Use a ferramenta Read para ver a imagem {photo}. É a foto de um anúncio de venda: «{title[:120]}».
Descreva o objeto vendido pelo que se VÊ (forma, partes, como se prende, o que segura), e dê termos de busca em inglês para achar o modelo 3D imprimível
dele no Printables, MakerWorld e Thingiverse. Os termos devem variar: um bem específico pela forma, outros pela função e outros por sinônimos usados por quem modela
(ex.: holder, mount, bracket, stand, rack, hanger, organizer), de 2 a 5 palavras cada, do mais provável ao mais amplo.
Responda SOMENTE com JSON: {{"descricao": "uma ou duas frases em português", "termos": ["6 a 8 termos em inglês"]}}"""


def parse_visual(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("a resposta do Claude não trouxe JSON")
    try:
        d = json.loads(m.group(0))
        terms = [re.sub(r"\s+", " ", str(t)).strip()[:60] for t in d["termos"] if str(t).strip()]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise ValueError("o JSON dos termos veio quebrado")
    return dict(descricao=str(d.get("descricao", "")).strip()[:300], termos=list(dict.fromkeys(terms))[:8])


def visual_terms(title, photo, ask=ask_claude):
    """Descrição e termos de busca tirados da FOTO do anúncio (o título em português nem sempre bate com o nome do modelo nos sites em inglês)."""
    with tempfile.TemporaryDirectory() as tmp:
        jpg = save_jpg(Path(photo).read_bytes(), Path(tmp) / "anuncio.jpg")
        return parse_visual(ask(visual_prompt(title, jpg), tmp))
