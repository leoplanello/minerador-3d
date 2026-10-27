"""Ativos CC0 do Poly Haven (https://polyhaven.com, licença CC0) para a sala das imagens e do vídeo.
Baixados pela API pública (api.polyhaven.com) para TOOLS/polyhaven/<id>/, com conferência de MD5 e registro de origem em registry.json.
Sem os ativos, o Blender cai no cenário procedural simples: nada quebra."""
import hashlib
import json
import urllib.request
from pathlib import Path

from paths import TOOLS

API = "https://api.polyhaven.com"
UA = "minerador-3d (github.com/leoplanello/minerador-3d)"
ROOT = TOOLS / "polyhaven"
# id -> (tipo, para que serve). 1k basta: a sala sai desfocada atrás da peça.
ASSETS = {
    "brown_photostudio_05": ("hdri", "luz natural e reflexos de ambiente interno"),
    "plastered_wall_04": ("texture", "parede da sala"),
    "laminate_floor_02": ("texture", "piso da sala"),
    "Sofa_01": ("model", "sofá encostado na parede"),
    "side_table_01": ("model", "mesa lateral"),
    "potted_plant_01": ("model", "vaso de planta no canto"),
}
TEXTURE_MAPS = {"Diffuse": "diff", "nor_gl": "nor", "Rough": "rough"}
RES = "1k"


def _get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read()


def _fetch(url, md5, dst):
    """Baixa e confere o MD5 antes de gravar; levanta ValueError se não bater."""
    data = _get(url)
    if hashlib.md5(data).hexdigest() != md5:
        raise ValueError(f"o arquivo {Path(url).name} veio corrompido (MD5 não confere)")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)


def file_list(asset, kind, files):
    """[(url, md5, caminho relativo)] do que o Blender precisa para o ativo, a partir da resposta de /files/<id>."""
    if kind == "hdri":
        f = files["hdri"][RES]["hdr"]
        return [(f["url"], f["md5"], Path(f["url"]).name)]
    if kind == "texture":
        out = []
        for key, tag in TEXTURE_MAPS.items():
            f = files[key][RES]["jpg"]
            out.append((f["url"], f["md5"], f"{tag}.jpg"))
        return out
    g = files["gltf"][RES]["gltf"]
    return [(g["url"], g["md5"], f"{asset}.gltf")] + [(v["url"], v["md5"], rel) for rel, v in g["include"].items()]


def ensure(root=ROOT, get=_get, fetch=_fetch):
    """Baixa o que falta e devolve o registro {id: {...}}. Idempotente: o que já está em disco não baixa de novo."""
    root.mkdir(parents=True, exist_ok=True)
    reg_path = root / "registry.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.is_file() else {}
    reg = {a: v for a, v in reg.items() if a in ASSETS}  # tira do registro o que saiu da lista
    for asset, (kind, use) in ASSETS.items():
        if asset in reg and all((root / asset / f["path"]).is_file() for f in reg[asset]["files"]):
            continue
        files = json.loads(get(f"{API}/files/{asset}"))
        info = json.loads(get(f"{API}/info/{asset}"))
        got = []
        for url, md5, rel in file_list(asset, kind, files):
            fetch(url, md5, root / asset / rel)
            got.append(dict(path=rel, url=url, md5=md5))
        reg[asset] = dict(type=kind, name=info.get("name", asset), authors=list(info.get("authors", {})), license="CC0 1.0",
                          page=f"https://polyhaven.com/a/{asset}", use=use, files=got)
        reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    return reg


def available(root=ROOT):
    """True quando todos os ativos da sala estão em disco; o Blender só usa a sala nesse caso."""
    try:
        reg = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return all(a in reg and all((root / a / f["path"]).is_file() for f in reg[a]["files"]) for a in ASSETS)


def credits_markdown(reg):
    """Texto para docs/ativos-polyhaven.md: origem, autor, licença e URL de cada arquivo baixado."""
    lines = ["# Ativos do Poly Haven usados na sala", "",
             "Todos CC0 1.0 (domínio público, uso comercial livre, sem atribuição obrigatória): https://polyhaven.com/license. Baixados pela API pública em resolução 1k.", ""]
    for a, v in reg.items():
        lines += [f"## {v['name']} (`{a}`, {v['type']})", f"- Uso: {v['use']}", f"- Página: {v['page']}", f"- Autor: {', '.join(v['authors']) or 'não informado'}", f"- Licença: {v['license']}"]
        lines += [f"- Arquivo `{f['path']}`: {f['url']} (md5 {f['md5']})" for f in v["files"]]
        lines.append("")
    return "\n".join(lines)
