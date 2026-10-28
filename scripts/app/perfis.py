"""Perfis do Chrome para a leitura de lojas e a busca de modelos.

Dois conceitos que não se misturam:
- perfis do SEU Chrome (pasta User Data): só listados, para você saber quais existem. O app nunca lê senhas nem cookies deles e nunca copia nada.
  Desde o Chrome 136 o Chrome ignora a depuração remota (o que o Playwright usa) na pasta padrão, então o app não consegue usá-los direto
  (https://developer.chrome.com/blog/remote-debugging-port).
- perfis do APP (db/profiles/<nome>): pastas só do Minerador 3D, onde você entra nas contas uma vez. São eles que a leitura e a busca usam."""
import json
import os
import re
import threading
import time
from pathlib import Path

import proc
from store_reader import PROFILES_DIR, chrome_path

CHROME_USER_DATA = Path(os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"))
PREFIX = "Minerador 3D - "
SERVICES = {  # onde abrir a página de login de cada serviço
    "mercadolivre": ("Mercado Livre", "https://www.mercadolivre.com.br/login"),
    "shopee": ("Shopee", "https://shopee.com.br/buyer/login"),
    "makerworld": ("MakerWorld", "https://makerworld.com/pt/login"),
    "printables": ("Printables", "https://www.printables.com/login"),
    "thingiverse": ("Thingiverse", "https://www.thingiverse.com/login"),
    "google": ("Conta Google", "https://accounts.google.com/"),
}
_open = {}  # nome do perfil do app -> estado do login em andamento (só em memória)


def system_profiles(user_data=None):
    """Perfis do Chrome do usuário, lidos só do `Local State` (nomes e e-mails). Não abre Cookies, Login Data nem nenhum outro arquivo do perfil."""
    ls = (user_data or CHROME_USER_DATA) / "Local State"
    try:
        info = json.loads(ls.read_text(encoding="utf-8"))["profile"]
    except (OSError, ValueError, KeyError):
        return []
    last = info.get("last_used")
    out = [dict(pasta=k, nome=v.get("name") or k, email=v.get("user_name") or "", conta=v.get("gaia_name") or "", ultimo=k == last) for k, v in info.get("info_cache", {}).items()]
    return sorted(out, key=lambda p: (not p["ultimo"], p["nome"].lower()))


def clean_nickname(nick):
    """Apelido do perfil: letras, números, espaço, hífen e sublinhado, de 2 a 40 caracteres. O nome da pasta é 'Minerador 3D - <apelido>'."""
    n = re.sub(r"\s+", " ", str(nick or "")).strip()
    if not re.fullmatch(r"[\w\- ]{2,40}", n, re.UNICODE):
        raise ValueError("apelido inválido: use de 2 a 40 letras, números, espaço ou hífen")
    return n


def app_profiles(base=None):
    """Perfis do app (pastas em db/profiles) com o estado do login em andamento, se houver."""
    base = base or PROFILES_DIR
    names = sorted(d.name for d in base.iterdir() if d.is_dir()) if base.exists() else []
    return [dict(nome=n, apelido=n[len(PREFIX):] if n.startswith(PREFIX) else n, dedicado=n.startswith(PREFIX), login=_open.get(n)) for n in names]


def add_profile(nickname, service, base=None, popen=None, chrome=None):
    """Cria o perfil 'Minerador 3D - <apelido>' e abre o Chrome numa janela nova, só dele, na página de login do serviço. Uma thread espera você entrar e
    fechar a janela; aí o perfil passa a 'pronto'. Devolve o nome do perfil. Nada de outro perfil é copiado."""
    base, popen = base or PROFILES_DIR, popen or proc.popen
    if service not in SERVICES:
        raise ValueError("serviço desconhecido")
    nome = PREFIX + clean_nickname(nickname)
    if (base / nome).exists() and _open.get(nome, {}).get("estado") == "aberto":
        raise ValueError("esse perfil já está aberto; entre na conta e feche a janela")
    (base / nome).mkdir(parents=True, exist_ok=True)
    label, url = SERVICES[service]
    p = popen([chrome or chrome_path(), f"--user-data-dir={base / nome}", "--no-first-run", "--no-default-browser-check", "--new-window", url], show=True)
    _open[nome] = dict(estado="aberto", servico=label, desde=time.strftime("%H:%M"))

    def esperar():
        try:
            p.wait()
        finally:
            _open[nome] = dict(estado="pronto", servico=label, desde=time.strftime("%H:%M"))
    threading.Thread(target=esperar, daemon=True).start()
    return nome
