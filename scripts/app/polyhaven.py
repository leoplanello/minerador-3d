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
# Três ambientes, escolhidos pelo tipo de produto (render.room_for). wall/floor = (textura, ladrilho em mm, tom que multiplica a cor ou None);
# hdri = (nome, giro em graus, força); support = o móvel baixo onde o produto fica ou acima do qual ele é fixado (asset, x, y, giro);
# items = objetos de vida real sobre o móvel, fora do foco (asset, x, giro); extras = móveis no chão (asset, x, y, giro); door_x = onde fica o vão da porta.
ROOMS = {
    "sala": dict(label="Sala", wall=("painted_plaster_wall", 2400, (1.0, 0.95, 0.86)), floor=("herringbone_parquet", 1000, None), hdri=("reading_room", 200, 1.5),
                 support=("modern_wooden_cabinet", 0, -270, 0), items=[("ceramic_vase_03", -950, 0), ("book_encyclopedia_set_01", -480, 0), ("potted_plant_04", 900, 0), ("standing_picture_frame_01", 520, -8)],
                 extras=[("modern_arm_chair_01", 2000, -700, -35)], door_x=-1900),
    "entrada": dict(label="Entrada", wall=("castle_brick_02_white", 1500, (1.0, 0.97, 0.92), 0.42), floor=("floor_tiles_02", 900, None), hdri=("entrance_hall", 0, 1.3),
                    support=("painted_wooden_cabinet", 0, -310, 0), items=[("planter_pot_clay", -380, 0), ("wicker_basket_02", 400, 0)], extras=[], door_x=1700),
    "escritorio": dict(label="Escritório", wall=("beige_wall_001", 2200, (1.0, 0.96, 0.88)), floor=("wooden_floor_02", 1200, None), hdri=("small_empty_room_3", 120, 1.6),
                       support=("wooden_table_02", 0, -360, 0), items=[("alarm_clock_01", -430, 15), ("potted_plant_04", 440, 0)],
                       extras=[("dining_chair_02", 650, -820, 165)], door_x=-1250),
    "quarto": dict(label="Quarto", wall=("painted_plaster_wall", 2400, (0.84, 0.89, 0.95)), floor=("laminate_floor_02", 1700, None), hdri=("hotel_room", 160, 1.5),
                   support=("painted_wooden_nightstand", 0, -300, 0), items=[("alarm_clock_01", -150, 20), ("potted_plant_04", 170, 0)],
                   extras=[("vintage_day_bed", 1500, -500, 0)], door_x=-1900),
    "cozinha": dict(label="Cozinha", wall=("floor_tiles_02", 650, (1.0, 0.98, 0.94)), floor=("wooden_floor_02", 1200, None), hdri=("small_empty_room_4", 80, 1.6),
                    support=("wooden_table_02", 0, -360, 0), items=[("vintage_electric_kettle", 360, 160), ("wooden_bowl_01", -350, 0)],
                    extras=[("wooden_stool_01", 700, -900, 20)], door_x=-1900),
    "oficina": dict(label="Bancada de oficina", wall=("concrete_wall_003", 2000, None), floor=("concrete_floor_painted", 1500, None), hdri=("small_workshop", 40, 1.4),
                    support=("WoodenTable_03", 0, -300, 0), items=[("metal_toolbox", -430, 0), ("adjustable_wrench", 400, 70)],
                    extras=[("metal_stool_02", 800, -800, 0)], door_x=2100),
}


def _assets():
    out = {}
    for r in ROOMS.values():
        out[r["wall"][0]] = ("texture", "parede")
        out[r["floor"][0]] = ("texture", "piso")
        out[r["hdri"][0]] = ("hdri", "luz natural e reflexos")
        for a in [r["support"][0]] + [x[0] for x in r["items"]] + [x[0] for x in r["extras"]]:
            out[a] = ("model", "móvel ou objeto de decoração")
    return out


ASSETS = _assets()  # id -> (tipo, uso); tudo em 1k, que basta: a sala sai desfocada atrás da peça
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
    # o registro também guarda os móveis do catálogo da sala virtual (sala.baixar_modelo): não se tira nada dele aqui
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
