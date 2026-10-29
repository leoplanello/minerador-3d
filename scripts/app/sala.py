"""Sala virtual editável: cada produto tem uma sala.blend em products/<id>/cena/ que o Leonardo abre no Blender, edita e salva.
O app gera o arquivo, abre o Blender com janela, lê o layout (mm) quando ele fecha, põe móveis do catálogo do Poly Haven (CC0) e
modelos dele (.glb, .stl, .3mf, .blend) e renderiza imagens e vídeo a partir do arquivo salvo. Nada aqui apaga arquivo do usuário."""
import json
import re
import shutil
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import polyhaven
import proc
import render as renderizar

EXT_MODELO = (".glb", ".gltf", ".stl", ".3mf", ".blend")
ABERTOS = {}  # lid -> {"proc": Popen, "desde": float}: Blenders com janela que ainda estão abertos
_cache = {}


def blend_path(d):
    return Path(d) / "sala.blend"


def dentro(d, rel):
    """Caminho dentro da pasta da cena; levanta ValueError para qualquer coisa que escape dela."""
    base = Path(d).resolve()
    p = (base / rel).resolve()
    if base != p and base not in p.parents:
        raise ValueError("caminho fora da pasta da sala virtual")
    return p


def estado(lid, d):
    b = blend_path(d)
    lay = Path(d) / "layout.json"
    objetos = []
    if lay.is_file():
        try:
            objetos = [o for o in json.loads(lay.read_text(encoding="utf-8"))["objetos"] if o["tipo"] in ("movel", "decor", "peca", "referencia")]
        except (ValueError, KeyError):
            pass
    aberto = lid in ABERTOS and ABERTOS[lid]["proc"].poll() is None
    return dict(existe=b.is_file(), tamanho_mb=round(b.stat().st_size / 1e6, 1) if b.is_file() else 0, aberto=aberto,
                salvo_em=datetime.fromtimestamp(b.stat().st_mtime).isoformat(timespec="seconds") if b.is_file() else None,
                objetos=objetos, modelos=sorted(p.name for p in (Path(d) / "modelos").glob("*")) if (Path(d) / "modelos").is_dir() else [])


def lid_aberto(d):
    """True se a sala desta pasta está aberta num Blender com janela."""
    return any(Path(d) == Path(v["pasta"]) and v["proc"].poll() is None for v in ABERTOS.values())


def gerar(d, model, cena, title="", refazer=False):
    """Gera sala.blend. Com refazer, o arquivo atual vira sala-anterior-<data>.blend (nada é apagado)."""
    b = blend_path(d)
    Path(d).mkdir(parents=True, exist_ok=True)
    if lid_aberto(d):
        raise ValueError("feche o Blender (salvando) antes de refazer a sala")
    if b.is_file():
        if not refazer:
            raise ValueError("a sala já existe: abra no Blender ou use Refazer a sala")
        shutil.move(b, Path(d) / f"sala-anterior-{datetime.now():%Y%m%d-%H%M%S}.blend")
    try:
        renderizar.gerar_blend(model, b, cena, title)
    finally:
        if not b.is_file():  # falhou depois de guardar a antiga: devolve a mais recente
            antigos = sorted(Path(d).glob("sala-anterior-*.blend"))
            if antigos and refazer:
                shutil.move(antigos[-1], b)
    renderizar.blend_layout(b, Path(d) / "layout.json")
    return b


def abrir(lid, d, popen=None):
    """Abre a sala no Blender com janela. Quando o Blender fecha, o layout é lido de novo (thread). Devolve quando o processo subiu."""
    b = blend_path(d)
    if not b.is_file():
        raise ValueError("gere a sala primeiro")
    if not renderizar.BLENDER.exists():
        raise ValueError("Blender não encontrado em tools/blender")
    if lid in ABERTOS and ABERTOS[lid]["proc"].poll() is None:
        raise ValueError("a sala já está aberta no Blender: salve (Ctrl+S) e feche a janela")
    p = (popen or proc.popen)([str(renderizar.BLENDER), str(b)], show=True)  # único programa com janela intencional
    ABERTOS[lid] = dict(proc=p, desde=time.time(), pasta=str(d))

    def espera():
        p.wait()
        try:
            renderizar.blend_layout(b, Path(d) / "layout.json")
        except ValueError:
            pass
    threading.Thread(target=espera, daemon=True).start()


def catalogo(categoria="furniture", get=polyhaven._get):
    """Modelos CC0 do Poly Haven de uma categoria: [{id, nome, categorias, largura_mm...}], em cache por categoria."""
    if not re.fullmatch(r"[a-z ]{2,30}", categoria):
        raise ValueError("categoria inválida")
    if categoria not in _cache:
        dados = json.loads(get(f"{polyhaven.API}/assets?t=models&c={urllib.parse.quote(categoria)}"))
        _cache[categoria] = sorted(({"id": k, "nome": v["name"], "categorias": v["categories"], "dimensoes_mm": [round(x) for x in v.get("dimensions", [])]} for k, v in dados.items()),
                                   key=lambda x: x["nome"])
    return _cache[categoria]


def baixar_modelo(asset, root=None, get=polyhaven._get, fetch=polyhaven._fetch):
    """Baixa um modelo do catálogo (gltf 1k, MD5 conferido) para tools/polyhaven/<id>/ e registra a origem. Devolve o caminho do .gltf."""
    if not re.fullmatch(r"[A-Za-z0-9_]{2,60}", asset):
        raise ValueError("modelo inválido")
    root = Path(root or polyhaven.ROOT)
    gltf = root / asset / f"{asset}.gltf"
    reg_path = root / "registry.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.is_file() else {}
    if asset in reg and gltf.is_file():
        return gltf
    files = json.loads(get(f"{polyhaven.API}/files/{asset}"))
    info = json.loads(get(f"{polyhaven.API}/info/{asset}"))
    if "gltf" not in files:
        raise ValueError("esse item do Poly Haven não é um modelo 3D")
    got = []
    for url, md5, rel in polyhaven.file_list(asset, "model", files):
        fetch(url, md5, root / asset / rel)
        got.append(dict(path=rel, url=url, md5=md5))
    reg[asset] = dict(type="model", name=info.get("name", asset), authors=list(info.get("authors", {})), license="CC0 1.0", page=f"https://polyhaven.com/a/{asset}",
                      use="móvel escolhido no catálogo da sala virtual", files=got)
    reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    return gltf


def guardar_modelo(d, nome, dados, max_bytes=200 * 1024 * 1024):
    """Copia um modelo do usuário para cena/modelos/. 3MF vira STL (a conversão que o app já usa). Devolve o caminho relativo à pasta da cena."""
    nome = re.sub(r"[^\w.\- ]", "_", Path(nome).name)
    ext = Path(nome).suffix.lower()
    if ext not in EXT_MODELO:
        raise ValueError("formatos aceitos: .glb, .gltf, .stl, .3mf e .blend")
    if not 0 < len(dados) <= max_bytes:
        raise ValueError("arquivo vazio ou maior que 200 MB")
    pasta = Path(d) / "modelos"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / nome
    destino.write_bytes(dados)
    if ext == ".3mf":
        stl = destino.with_suffix(".stl")
        renderizar.threemf_to_stl(destino, stl)
        destino = stl
    return destino.relative_to(d).as_posix()


def adicionar(lid, d, itens):
    """Põe itens na sala.blend, à frente da câmera e no chão. itens: [{fonte: 'polyhaven:<id>' | 'arquivo:modelos/<nome>', nome?}]."""
    if lid in ABERTOS and ABERTOS[lid]["proc"].poll() is None:
        raise ValueError("feche o Blender (salvando) antes de adicionar: ele é quem guarda a sala")
    b = blend_path(d)
    if not b.is_file():
        raise ValueError("gere a sala primeiro")
    prontos = []
    for i, it in enumerate(itens):
        tipo, _, ref = str(it.get("fonte", "")).partition(":")
        if tipo == "polyhaven":
            caminho, nome = baixar_modelo(ref), ref
        elif tipo == "arquivo":
            caminho = dentro(d, ref)
            if not caminho.is_file():
                raise ValueError("arquivo não encontrado na pasta da sala virtual")
            nome = Path(ref).stem
        else:
            raise ValueError("fonte inválida")
        prontos.append(dict(nome=it.get("nome") or nome, caminho=str(caminho), tipo="movel", fonte=f"{tipo}:{ref}", x=-600 + 450 * (i % 4), y=-900, z=0))
    renderizar.blend_adicionar(b, prontos)
    renderizar.blend_layout(b, Path(d) / "layout.json")
