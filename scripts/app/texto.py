"""Gera título, descrição, bullets e roteiros de um produto com o Claude Code em modo `-p` (plano Pro, sem chave de API)."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

RULES = """Escreva em português do Brasil, como uma pessoa que vende o produto, sem tom de propaganda.
Evite: contrastes do tipo "não é X, é Y", frases de efeito no fim, listas de três adjetivos, travessão (—), palavras como
"incrível", "perfeito", "revolucionário", "elevar", "transformar", emojis e CAIXA ALTA. Frases curtas e concretas.
Não invente medidas, certificações, resistência ou prazos que não estejam nos dados. Diga com clareza que a peça é impressa em 3D
sob encomenda (camadas visíveis são normais). Título do anúncio: até 60 caracteres, sem marca nem "frete grátis"."""


def build_prompt(p):
    """p: dict com title, price, material, minutes, grams, brand, colors, sizes, days."""
    horas = f"{p['minutes'] // 60} h {p['minutes'] % 60} min"
    return f"""{RULES}

Dados do produto (use só o que está aqui):
- Produto parecido que vende bem: {p['title']}
- Material: {p['material'] or 'PLA'}
- Tempo de impressão: {horas}; filamento: {p['grams']} g
- Preço-alvo: R$ {p['price']:.2f}
- Cores disponíveis: {p['colors'] or 'não informado (não cite cores)'}
- Medidas: {p['sizes'] or 'não informado (não cite medidas)'}
- Prazo de produção: {p['days']} dias úteis (impressa depois da compra)
- Nome da loja: {p['brand'] or 'não informado (não cite o nome)'}

Responda SOMENTE com um JSON, sem texto antes ou depois, neste formato:
{{"title": "...", "description": "texto corrido de 3 a 5 parágrafos curtos", "bullets": ["3 a 6 itens curtos"],
 "scripts": ["1 a 3 roteiros de vídeo de 20 a 30 segundos, para a pessoa falar em voz alta"], "keywords": ["5 a 10 palavras de busca"]}}"""


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
    out = dict(title=clean(d.get("title", "")), description=clean(d.get("description", "")),
               bullets=[clean(b) for b in d.get("bullets", [])], scripts=[clean(s) for s in d.get("scripts", [])],
               keywords=[clean(k) for k in d.get("keywords", [])])
    if not 5 <= len(out["title"]) <= 60:
        raise ValueError(f"título com {len(out['title'])} caracteres (precisa de 5 a 60); tente de novo")
    if len(out["description"]) < 80 or not 3 <= len(out["bullets"]) <= 6 or not out["scripts"]:
        raise ValueError("a resposta veio incompleta (descrição, bullets ou roteiro); tente de novo")
    return out


def generate(p):
    r = subprocess.run([_cmd(), "-p"], input=build_prompt(p), capture_output=True, text=True, timeout=240, encoding="utf-8")
    if "not logged in" in (r.stdout + r.stderr).lower():
        raise ValueError(f"o Claude da linha de comando não está logado. Abra um terminal, rode `{_cmd()}` e digite /login uma vez.")
    if r.returncode != 0:
        raise ValueError(f"o Claude retornou erro: {(r.stderr or r.stdout)[:200]}")
    return parse_reply(r.stdout)
