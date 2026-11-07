"""Gera o anúncio de um produto (título por marketplace, descrição, ficha, perguntas e palavras-chave) com o Claude Code em modo `-p`
(plano Pro, sem chave de API). Medidas, material, peso, prazo e créditos vêm dos dados do app, nunca do Claude."""
import io
import json
import os
import re
import shutil
import struct
import zipfile
import proc
from pathlib import Path

TITULO_MAX = {"ml": 60, "shopee": 120}  # Mercado Livre: 60 caracteres; Shopee: 120 (conferir na Central do Vendedor)
RULES = """Escreva em português do Brasil, como uma pessoa que vende o produto, tom direto de vendedor brasileiro, sem tom de propaganda.
Evite: contrastes do tipo "não é X, é Y", frases de efeito de uma linha no fim de parágrafo, listas de três adjetivos, travessão (—),
palavras como "incrível", "perfeito", "revolucionário", "elevar", "transformar", "ideal para todos", emojis e CAIXA ALTA.
Frases curtas e concretas. Não invente medidas, certificações, resistência, cores ou prazos que não estejam nos dados.
Não cite tempo de impressão: só o prazo de produção. Diga com clareza que a peça é impressa em 3D sob encomenda
(camadas visíveis são normais). Não coloque links, contatos, telefone ou nome de outra loja no texto."""


def build_prompt(p):
    """p: title, price, material, days, colors, brand, pecas (peças por venda)."""
    return f"""{RULES}

Dados do produto (use só o que está aqui):
- Produto parecido que vende bem: {p['title']}
- Material: {p['material']}
- Preço-alvo: R$ {p['price']:.2f}
- Peças por venda: {p.get('pecas', 1)}
- Cores disponíveis: {p['colors'] or 'não informado (não cite cores)'}
- Prazo de produção: {p['days']} dias úteis, impresso depois da compra
- Nome da loja: {p['brand'] or 'não informado (não cite o nome)'}

Responda SOMENTE com um JSON, sem texto antes ou depois, neste formato:
{{"titulo_ml": "até 60 caracteres, produto e uso no começo, sem marca",
 "titulo_shopee": "até 120 caracteres, pode trazer mais palavras de busca",
 "descricao": "3 a 5 parágrafos curtos, o que é e para que serve",
 "bullets": ["3 a 6 itens curtos, cada um uma característica concreta"],
 "uso": "como usar ou montar, em 1 a 3 frases",
 "cuidados": "1 a 2 frases",
 "perguntas": [{{"pergunta": "...", "resposta": "..."}}],
 "palavras_chave": ["5 a 10 palavras de busca"],
 "roteiros": ["1 a 3 roteiros de 20 a 30 segundos, para a pessoa falar em voz alta"]}}
Perguntas: 2 a 4, do que o comprador perguntaria antes de comprar."""


def _cmd():
    """CLAUDE_CMD, o `claude` do PATH ou o claude.exe embutido no app Claude para Windows (a pasta muda a cada versão)."""
    exe = os.environ.get("CLAUDE_CMD") or shutil.which("claude")
    if not exe:
        found = sorted(Path(os.environ.get("LOCALAPPDATA", "")).glob("Claude-Data/*/claude-code/*/*/claude.exe"), key=lambda f: f.stat().st_mtime)
        exe = str(found[-1]) if found else None
    if not exe:
        raise ValueError("não achei o comando `claude`; defina a variável CLAUDE_CMD com o caminho dele")
    return exe


def parse_reply(text):
    """Extrai e valida o JSON da resposta. Levanta ValueError com o motivo."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("a resposta do Claude não trouxe JSON")
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise ValueError("o JSON da resposta veio quebrado; tente de novo")
    clean = lambda s: str(s).replace("—", ",").strip()
    out = dict(titulo_ml=clean(d.get("titulo_ml", "")), titulo_shopee=clean(d.get("titulo_shopee", "")), descricao=clean(d.get("descricao", "")),
               bullets=[clean(b) for b in d.get("bullets", [])], uso=clean(d.get("uso", "")), cuidados=clean(d.get("cuidados", "")),
               perguntas=[dict(pergunta=clean(q.get("pergunta", "")), resposta=clean(q.get("resposta", ""))) for q in d.get("perguntas", []) if isinstance(q, dict)],
               roteiros=[clean(s) for s in d.get("roteiros", [])], palavras_chave=[clean(k) for k in d.get("palavras_chave", [])])
    if not 5 <= len(out["titulo_ml"]) <= TITULO_MAX["ml"]:
        raise ValueError(f"título do Mercado Livre com {len(out['titulo_ml'])} caracteres (precisa de 5 a 60); tente de novo")
    if not 5 <= len(out["titulo_shopee"]) <= TITULO_MAX["shopee"]:
        raise ValueError(f"título da Shopee com {len(out['titulo_shopee'])} caracteres (precisa de 5 a 120); tente de novo")
    if len(out["descricao"]) < 80 or not 3 <= len(out["bullets"]) <= 6 or not out["roteiros"] or not out["palavras_chave"]:
        raise ValueError("a resposta veio incompleta (descrição, bullets, palavras-chave ou roteiro); tente de novo")
    return out


def dimensoes(path):
    """Tamanho da peça em mm, (x, y, z), lido do STL (binário ou ASCII) ou do 3MF. None se não der para ler."""
    try:
        data = Path(path).read_bytes()
        if str(path).lower().endswith(".3mf"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("3D/3dmodel.model").decode("utf-8", "replace")
            pts = [tuple(map(float, t)) for t in re.findall(r'<vertex\s+x="([^"]+)"\s+y="([^"]+)"\s+z="([^"]+)"', xml)]
        else:
            n = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else -1
            if n > 0 and len(data) == 84 + 50 * n:  # STL binário: 50 bytes por triângulo
                pts = [struct.unpack_from("<3f", data, 84 + 50 * i + 12 + 12 * k) for i in range(n) for k in range(3)]
            else:
                pts = [tuple(map(float, t)) for t in re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data.decode("latin-1"))]
        if not pts:
            return None
        return tuple(round(max(a) - min(a), 1) for a in zip(*pts))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, struct.error):
        return None


def num_br(x):
    return f"{round(x, 1):g}".replace(".", ",")


def ficha_tecnica(p):
    """Campos da ficha com dados reais. Sem tempo de impressão: ele não entra no anúncio."""
    f = [("Material", p["material"]), ("Acompanha", f"{p.get('pecas', 1)} peça(s) impressa(s) em 3D")]
    if p.get("dims"):
        f.append(("Dimensões", " x ".join(num_br(v) for v in p["dims"]) + " mm"))
    f.append(("Peso aproximado", f"{num_br(p['grams'])} g"))
    if p["colors"]:
        f.append(("Cores", p["colors"]))
    f.append(("Compatibilidade", "confira as medidas do seu aparelho antes de comprar"))
    f.append(("Produção", f"{p['days']} dias úteis, impresso depois da compra"))
    return f


def compose(d, p):
    """Anúncio final: texto do Claude mais ficha, uso, cuidados, créditos e perguntas com os dados do app.
    p: material, grams, dims, colors, pecas, days, creditos."""
    blocos = [d["descricao"], "Ficha técnica\n" + "\n".join(f"{k}: {v}" for k, v in ficha_tecnica(p))]
    if d["uso"]:
        blocos.append("Como usar e montar\n" + d["uso"])
    if d["cuidados"]:
        blocos.append("Cuidados\n" + d["cuidados"])
    blocos.append("Créditos do modelo\n" + p["creditos"])
    if d["perguntas"]:
        blocos.append("Perguntas frequentes\n" + "\n\n".join(f"{q['pergunta']}\n{q['resposta']}" for q in d["perguntas"]))
    return dict(title=d["titulo_ml"], titulo_shopee=d["titulo_shopee"], description="\n\n".join(blocos), bullets=d["bullets"],
                scripts=d["roteiros"], keywords=d["palavras_chave"])


def generate(p):
    r = proc.run([_cmd(), "-p"], input=build_prompt(p), capture_output=True, text=True, timeout=300, encoding="utf-8")
    if "not logged in" in (r.stdout + r.stderr).lower():
        raise ValueError(f"o Claude da linha de comando não está logado. Abra um terminal, rode `{_cmd()}` e digite /login uma vez.")
    if r.returncode != 0:
        raise ValueError(f"o Claude retornou erro: {(r.stderr or r.stdout)[:200]}")
    return compose(parse_reply(r.stdout), p)
