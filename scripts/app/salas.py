"""Salas 3D de terceiros (CGTrader, modelos gratuitos) que viram ambientes da Sala virtual. Não vão no instalador: o app baixa o pacote da
release salas-1 do GitHub na primeira vez que a sala é escolhida, confere o SHA-256, e extrai em DATA/salas/<id>. Os direitos são dos autores."""
import hashlib
import shutil
import urllib.error
from pathlib import Path

import paths
import tools_installer

RELEASE = "https://github.com/leoplanello/minerador-3d/releases/download/salas-1/"
SALAS = {
    "apartamento-3-quartos": dict(
        label="Apartamento 3 quartos", arquivo="sala-apartamento-3-quartos.zip", size_mb=1161, modelo="GLB/3 Bedroom Apartment.glb",
        sha256="0e569343527367b829194cc2de010c22625a1b0946365df02e2cded29f47d384", titulo="3 Bedroom Apartment", autor="nickadamsss",
        pagina="https://www.cgtrader.com/items/5592166/download-page", ram_gb=12),
    "escritorio-secretaria": dict(
        label="Escritório secretaria", arquivo="sala-escritorio-secretaria.zip", size_mb=150, modelo="KRON+SECRETARY.fbx",
        sha256="d5f9826e114f1c97bdc9befad8c7eda1147e4504f7b964a49cb172f0df2a1485", titulo="Modern Detailed Secretary Office", autor="serpilz",
        pagina="https://www.cgtrader.com/items/5251056/download-page", ram_gb=4),
}
FRASE = "Os direitos destes modelos são dos autores; se algum deles pedir a retirada, o modelo sai do app."


def root():
    return paths.DATA / "salas"


def pasta(sid):
    return root() / sid


def modelo(sid):
    """Caminho do arquivo da sala, ou None se ainda não foi baixada."""
    f = pasta(sid) / SALAS[sid]["modelo"]
    return f if f.is_file() else None


def lista(jobs=None):
    return [dict(id=k, label=m["label"], size_mb=m["size_mb"], instalada=modelo(k) is not None, titulo=m["titulo"], autor=m["autor"], pagina=m["pagina"],
                 ram_gb=m["ram_gb"], job=(jobs or {}).get(k)) for k, m in SALAS.items()]


def baixar(sid, progress=lambda stage, done, total: None, abrir=tools_installer._open_retry):
    """Baixa com retomada (o que já veio fica em _downloads/<arquivo>.parte e continua de onde parou), confere o SHA-256 e instala.
    Só mexe em DATA/salas: nunca em db, products nem inbox."""
    m = SALAS[sid]
    work = root() / "_downloads"
    work.mkdir(parents=True, exist_ok=True)
    parte = work / (m["arquivo"] + ".parte")
    h, pos = hashlib.sha256(), parte.stat().st_size if parte.is_file() else 0
    r = abrir(RELEASE + m["arquivo"], extra={"Range": f"bytes={pos}-"} if pos else None)
    if pos and getattr(r, "status", 200) != 206:  # o servidor ignorou a retomada: recomeça do zero
        pos = 0
    total = pos + int(r.headers.get("Content-Length") or 0)
    if pos:
        with open(parte, "rb") as f:
            while chunk := f.read(1 << 22):
                h.update(chunk)
    with open(parte, "ab" if pos else "wb") as f:
        done = pos
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            progress("baixando", done, total)
    progress("conferindo", done, total)
    if h.hexdigest() != m["sha256"]:
        parte.unlink(missing_ok=True)
        raise ValueError("o arquivo baixado não confere com o SHA-256 esperado; apaguei o download e não instalei")
    progress("instalando", done, total)
    novo = root() / (sid + ".novo")
    shutil.rmtree(novo, ignore_errors=True)
    tools_installer.extract(parte, novo, dict(mode="keep"))
    shutil.rmtree(pasta(sid), ignore_errors=True)  # só a pasta desta sala, que o próprio app criou
    novo.rename(pasta(sid))
    parte.unlink(missing_ok=True)


def creditos_markdown():
    linhas = ["# Créditos das salas 3D importadas", "", FRASE, "",
              "Modelos gratuitos do CGTrader, baixados pelo app da release `salas-1` na primeira vez que a sala é escolhida. Confira a licença de cada modelo na página dele antes de publicar imagem ou vídeo.", ""]
    for m in SALAS.values():
        linhas += [f"- **{m['label']}**: \"{m['titulo']}\", por {m['autor']}, CGTrader. {m['pagina']}"]
    return "\n".join(linhas) + "\n"
