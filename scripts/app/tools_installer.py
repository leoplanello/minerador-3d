"""Baixa e instala Bambu Studio, Blender e ffmpeg em TOOLS (%LOCALAPPDATA%\\Minerador3D\\tools quando instalado), com progresso e conferência de SHA-256."""
import hashlib
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import paths

UA = {"User-Agent": "Minerador3D-tools"}
HOSTS = ("download.blender.org", "www.gyan.dev", "github.com", "githubusercontent.com")
# Cada ferramenta tem uma ou mais fontes, tentadas em ordem. Em cada fonte, o sha256 vem fixo (quando o fornecedor publica no release)
# ou de um arquivo de checksums ao lado do download (sha256_url; sha_name escolhe a linha certa quando o arquivo lista vários).
MANIFEST = {
    "bambustudio": dict(label="Bambu Studio 2.8.2", size_mb=473, mode="strip", exe="bambu-studio.exe", dest="bambustudio", sources=[
        dict(url="https://github.com/bambulab/BambuStudio/releases/download/v02.08.02.61/Bambu_Studio_win-v02.08.02.61-20260820225108.zip",
             sha256="3faaa194a90a2e7defa39a6a63f5a654b8cdb762c6a98556cf771fba582229f5")]),
    "blender": dict(label="Blender 4.2.3", size_mb=383, mode="keep", exe="blender.exe", dest="blender", sources=[
        dict(url="https://download.blender.org/release/Blender4.2/blender-4.2.3-windows-x64.zip",
             sha256_url="https://download.blender.org/release/Blender4.2/blender-4.2.3.sha256", sha_name="blender-4.2.3-windows-x64.zip")]),
    "ffmpeg": dict(label="ffmpeg", size_mb=114, mode="files", exe="ffmpeg.exe", dest="ffmpeg", files=("ffmpeg.exe", "ffprobe.exe"), sources=[
        dict(url="https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", sha256_url="https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256"),
        dict(url="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
             sha256_url="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256", sha_name="ffmpeg-master-latest-win64-gpl.zip")]),
}


def _host_ok(url):
    u = urllib.parse.urlparse(url)
    h = u.hostname or ""
    return u.scheme == "https" and any(h == d or h.endswith("." + d) for d in HOSTS)


def _open(url, extra=None):
    if not _host_ok(url):
        raise ValueError("endereço de download não permitido")
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA | (extra or {})), timeout=60)
    if not _host_ok(r.geturl()):  # depois dos redirecionamentos também
        raise ValueError("o download foi redirecionado para um endereço não permitido")
    return r


def installed(name):
    """Já instalada? Procura o executável onde o app o usa."""
    m = MANIFEST[name]
    base = paths.TOOLS / m["dest"]
    return base.is_dir() and any(base.rglob(m["exe"]))


def expected_sha(src):
    """SHA-256 esperado de uma fonte (dict de MANIFEST[...]["sources"])."""
    if src.get("sha256"):
        return src["sha256"].lower()
    text = _open_retry(src["sha256_url"]).read(200_000).decode("utf-8", "replace")
    for line in text.splitlines():  # "hash  nome" ou só o hash
        parts = line.split()
        if parts and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]) and (len(parts) == 1 or not src.get("sha_name") or parts[-1].lstrip("*") == src["sha_name"]):
            return parts[0].lower()
    raise ValueError("não achei o SHA-256 do download")


def _open_retry(url, tries=3, extra=None):
    """Servidores de download às vezes respondem 5xx por instantes: tenta de novo com espera crescente."""
    import time
    for i in range(tries):
        try:
            return _open(url, extra)
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def extract(zip_path, dest, m):
    """Extrai com proteção contra caminhos fora de dest. mode: strip (tira a pasta acima do exe), keep (mantém a estrutura), files (só os arquivos pedidos)."""
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if m["mode"] == "files":
            for want in m["files"]:
                member = next((n for n in names if n.split("/")[-1].lower() == want.lower()), None)
                if not member:
                    raise ValueError(f"{want} não está no arquivo baixado")
                dest.mkdir(parents=True, exist_ok=True)
                (dest / want).write_bytes(z.read(member))
            return
        prefix = ""
        if m["mode"] == "strip":
            exe = next((n for n in names if n.split("/")[-1].lower() == m["exe"].lower()), None)
            if not exe:
                raise ValueError(f"{m['exe']} não está no arquivo baixado")
            prefix = exe[: len(exe) - len(exe.split("/")[-1])]
        for n in names:
            if not n.startswith(prefix):
                continue
            target = (dest / n[len(prefix):]).resolve()
            if dest not in target.parents:
                raise ValueError("o arquivo baixado tem um caminho inválido")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)


def _download(src, zpath, progress):
    want = expected_sha(src)
    r = _open_retry(src["url"])
    total, done, h = int(r.headers.get("Content-Length") or 0), 0, hashlib.sha256()
    with open(zpath, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            progress("baixando", done, total)
    progress("conferindo", done, total)
    if h.hexdigest() != want:
        raise ValueError("o arquivo baixado não confere com o SHA-256 do fornecedor; não instalei")
    return done, total


def install(name, progress=lambda stage, done, total: None):
    """Baixa (tentando cada fonte em ordem), confere e instala. progress(stage, bytes_feitos, bytes_total), stage: baixando, conferindo, instalando."""
    if name not in MANIFEST:
        raise ValueError("ferramenta desconhecida")
    m = MANIFEST[name]
    work = paths.TOOLS / "_downloads"
    work.mkdir(parents=True, exist_ok=True)
    zpath = work / (name + ".zip")
    try:
        erros = []
        for src in m["sources"]:
            try:
                done, total = _download(src, zpath, progress)
                break
            except (OSError, ValueError) as e:  # HTTPError e erros de rede são OSError; SHA errado e host não permitido são ValueError
                erros.append(f"{urllib.parse.urlparse(src['url']).hostname}: {e}")
                zpath.unlink(missing_ok=True)
        else:
            raise ValueError("não consegui baixar: " + " | ".join(erros))
        progress("instalando", done, total)
        final, tmp = paths.TOOLS / m["dest"], paths.TOOLS / (m["dest"] + ".novo")
        shutil.rmtree(tmp, ignore_errors=True)
        extract(zpath, tmp, m)
        shutil.rmtree(final, ignore_errors=True)
        tmp.rename(final)
    finally:
        zpath.unlink(missing_ok=True)
        shutil.rmtree(paths.TOOLS / (m["dest"] + ".novo"), ignore_errors=True)
