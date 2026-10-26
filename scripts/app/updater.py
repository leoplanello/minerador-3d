"""Atualização automática pelo GitHub Releases: consulta a última versão, baixa o instalador, confere o SHA-256 e roda em modo silencioso.
Só funciona instalado (.exe); rodando do código, mostra a versão nova mas não instala."""
import hashlib
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

import paths

REPO = "leoplanello/minerador-3d"
API = os.environ.get("MINERADOR_UPDATE_API") or f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_RE = re.compile(r"Minerador3D-Setup-[\w.\-]+\.exe")
ALLOWED_HOSTS = ("github.com", "githubusercontent.com")  # o link de download vem da API; só aceito GitHub
UA = {"User-Agent": "Minerador3D-updater", "Accept": "application/vnd.github+json"}


def parse_version(v):
    """'v1.2.3' / '1.2.3-dev' -> (1, 2, 3); sem número, (0,)."""
    nums = re.match(r"v?(\d+(?:\.\d+)*)", str(v).strip())
    return tuple(int(x) for x in nums.group(1).split(".")) if nums else (0,)


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _host_ok(url):
    u = urllib.parse.urlparse(url)
    h = u.hostname or ""
    return u.scheme == "https" and any(h == d or h.endswith("." + d) for d in ALLOWED_HOSTS)


def check(current=None):
    """Consulta a última release. Devolve dict com current, latest, newer, notes e, se houver, asset_url, sha_url e size."""
    current = current or paths.version()
    try:
        req = urllib.request.Request(API, headers=UA)
        rel = json.load(urllib.request.urlopen(req, timeout=15))
    except Exception as e:
        return dict(current=current, error=f"não consegui consultar as atualizações: {e}")
    latest = str(rel.get("tag_name", "")).lstrip("v")
    out = dict(current=current, latest=latest, newer=bool(latest) and is_newer(latest, current), notes=(rel.get("body") or "")[:2000], page_url=rel.get("html_url", ""))
    assets = {a["name"]: a for a in rel.get("assets", [])}
    exe = next((a for n, a in assets.items() if ASSET_RE.fullmatch(n)), None)
    if exe and exe["name"] + ".sha256" in assets:
        out |= dict(asset_url=exe["browser_download_url"], asset_name=exe["name"], sha_url=assets[exe["name"] + ".sha256"]["browser_download_url"], size=exe.get("size"))
    return out


def _fetch(url, limit):
    if not _host_ok(url):
        raise ValueError("endereço de download não permitido")
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]}), timeout=60)


def download(info, progress=lambda done, total: None, dest_dir=None):
    """Baixa o instalador e confere o SHA-256 publicado na release. Devolve o caminho. Levanta ValueError se algo não bater."""
    if not info.get("asset_url") or not info.get("sha_url"):
        raise ValueError("a release não tem o instalador com o arquivo .sha256")
    expected = _fetch(info["sha_url"], 1024).read(1024).decode("utf-8", "replace").split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("o arquivo .sha256 da release está inválido")
    dest_dir = Path(dest_dir or paths.UPDATES)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / info["asset_name"]
    h, done = hashlib.sha256(), 0
    r = _fetch(info["asset_url"], None)
    total = int(r.headers.get("Content-Length") or info.get("size") or 0)
    with open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            progress(done, total)
    if h.hexdigest() != expected:
        dest.unlink(missing_ok=True)
        raise ValueError("o instalador baixado não confere com o SHA-256 da release; não instalei")
    return dest


def launch_installer(path):
    """Roda o instalador silencioso (por usuário, sem administrador) pedindo que reabra o app no fim. Quem chama encerra o app logo depois."""
    if not paths.FROZEN:
        raise ValueError("a instalação automática só funciona no app instalado (.exe)")
    subprocess.Popen([str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
