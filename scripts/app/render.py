"""Gera as fotos do anúncio a partir do modelo 3D usando o Blender portátil (tools/blender)."""
import json
import re
import polyhaven
import proc
import tempfile
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from paths import RESOURCES, TOOLS

BLENDER = next((TOOLS / "blender").glob("*/blender.exe"), TOOLS / "blender" / "blender.exe")
SCENE = RESOURCES / "scripts" / "app" / "blender_scene.py"


def refresh():
    """Reavalia onde está o Blender (depois de instalado pelo app)."""
    global BLENDER
    BLENDER = next((TOOLS / "blender").glob("*/blender.exe"), TOOLS / "blender" / "blender.exe")


def threemf_to_stl(src, dst):
    """3MF -> STL ASCII com todas as malhas do arquivo. shortcut: ignora transformações de build/componentes, serve para peça única; trocar se houver várias peças."""
    verts, tris = [], []
    with zipfile.ZipFile(src) as z:
        for name in z.namelist():
            if not name.lower().endswith(".model"):
                continue
            for mesh in ET.fromstring(z.read(name)).iter():
                if not mesh.tag.endswith("}mesh") and mesh.tag != "mesh":
                    continue
                base = len(verts)
                for el in mesh.iter():
                    if el.tag.endswith("vertex"):
                        verts.append((float(el.get("x")), float(el.get("y")), float(el.get("z"))))
                    elif el.tag.endswith("triangle"):
                        tris.append((base + int(el.get("v1")), base + int(el.get("v2")), base + int(el.get("v3"))))
    if not tris:
        raise ValueError("o 3MF não tem nenhuma malha 3D")
    with open(dst, "w") as f:
        f.write("solid m\n")
        for t in tris:
            f.write("facet normal 0 0 0\nouter loop\n" + "".join("vertex %g %g %g\n" % verts[i] for i in t) + "endloop\nendfacet\n")
        f.write("endsolid m\n")


def whiten(path):
    """Leva o fundo (pixel do canto) a branco puro, mantendo as sombras proporcionais: o ML pede foto principal com fundo branco."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    bg = [max(1, v) for v in im.getpixel((5, 5))]
    chans = [ch.point(lambda v, b=b: min(255, round(v * 255 / b))) for ch, b in zip(im.split(), bg)]
    Image.merge("RGB", chans).save(path, quality=93)


# ângulo (azimute, elevação, zoom da câmera) de cada vista que dá para pedir
VIEWS = {"frente": (35, 28, 1.0), "lado": (125, 22, 1.0), "cima": (-50, 55, 1.0), "tras": (215, 25, 1.0),
         "frontal": (0, 12, 1.0), "topo": (0, 88, 1.0), "perfil": (90, 5, 1.0), "detalhe": (35, 20, 0.6),
         "uso": (18, 8, 1.0), "uso_perto": (-24, 6, 0.6), "uso_medio": (28, 10, 1.0), "uso_aberto": (38, 12, 1.0)}  # "uso*": a peça instalada no cenário (parede ou mesa)
VIEW_LABELS = {"frente": "Frente 3/4", "lado": "Lado", "cima": "De cima", "tras": "Trás 3/4", "frontal": "Frontal", "topo": "Topo", "perfil": "Perfil", "detalhe": "Detalhe (zoom)",
               "uso": "Em uso (com o objeto)", "uso_perto": "Em uso, detalhe de perto", "uso_medio": "Ambiente médio", "uso_aberto": "Ambiente aberto"}
QUALITY = {"rapido": (16, 12), "normal": (32, 24), "alta": (64, 64)}  # amostras EEVEE, Cycles
FILL = {"perto": 2.4, "medio": 3.2, "longe": 3.8}  # distância da câmera em tamanhos da peça: quanto menor, mais a peça enche a imagem
RENDER_DEFAULT = dict(color="#3a3a3a", finish="matte", background="white", views=["frente", "uso_perto", "uso", "uso_medio", "uso_aberto"], size=1200,
                      quality="normal", light="normal", shadow=True, fill="medio", turn=0, contexto="auto")
WALL_WORDS = ("parede", "wall", "suporte", "porta-", "porta ", "prateleira", "gancho", "cabide", "organizador")  # o que se instala na parede
CHOICES = dict(finish=("matte", "gloss", "silk"), background=("white", "gray", "warm"), quality=tuple(QUALITY), light=("soft", "normal", "strong"), fill=tuple(FILL), contexto=("auto", "parede", "mesa"))


def clean_render_cfg(d):
    """Valida o que veio da tela e completa com o padrão. Levanta ValueError com o motivo."""
    cfg = RENDER_DEFAULT | {k: v for k, v in (d or {}).items() if k in RENDER_DEFAULT}
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(cfg["color"])):
        raise ValueError("cor inválida")
    for k, ok in CHOICES.items():
        if cfg[k] not in ok:
            raise ValueError(f"{k}: opção inválida")
    views = list(dict.fromkeys(cfg["views"])) if isinstance(cfg["views"], list) else []
    if not 1 <= len(views) <= 8 or any(v not in VIEWS for v in views):
        raise ValueError("escolha de 1 a 8 vistas")
    size = int(cfg["size"])
    if not 600 <= size <= 2400:
        raise ValueError("o tamanho da imagem deve ficar entre 600 e 2400 px")
    turn = int(cfg["turn"])
    if not 0 <= turn < 360:
        raise ValueError("o giro da peça deve ficar entre 0 e 359 graus")
    return cfg | dict(views=views, size=size, shadow=bool(cfg["shadow"]), turn=turn)


PROPS = {"chaves": ("chave", "chaveiro", "key"), "roteador": ("roteador", "modem", "router")}  # objeto que a peça segura, pelo título


def prop_for(title):
    t = title.lower()
    return next((k for k, words in PROPS.items() if any(w in t for w in words)), "")


def scene_for(cfg, title=""):
    """Cenário das vistas 'em uso': o escolhido na tela ou, no automático, parede quando o título fala de parede/suporte, senão mesa."""
    if cfg["contexto"] != "auto":
        return cfg["contexto"]
    t = title.lower()
    return "parede" if "parede" in t or "wall" in t or (any(w in t for w in WALL_WORDS) and "mesa" not in t and "bancada" not in t) else "mesa"


def render_images(model, outdir, cfg=None, title=""):
    """Devolve a lista de JPGs gerados (render_1.jpg...). Tenta EEVEE e cai para Cycles (CPU) se a placa de vídeo não aceitar.
    cfg: dict de clean_render_cfg ou, por compatibilidade, só a cor '#rrggbb'. title: título do anúncio, escolhe o cenário das vistas 'em uso'."""
    if not BLENDER.exists():
        raise ValueError("Blender não encontrado em tools/blender")
    cfg = clean_render_cfg(dict(color=cfg) if isinstance(cfg, str) else cfg)
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("render_*.jpg"):
        old.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        scene_cfg = cfg | dict(polyhaven=str(polyhaven.ROOT) if polyhaven.available() else "", views=[(v, *VIEWS[v]) for v in cfg["views"]], contexto=scene_for(cfg, title), objeto=prop_for(title), samples_eevee=QUALITY[cfg["quality"]][0], samples_cycles=QUALITY[cfg["quality"]][1], dist=FILL[cfg["fill"]])
        cfgfile = Path(tmp) / "cfg.json"
        cfgfile.write_text(json.dumps(scene_cfg), encoding="utf-8")
        stl = Path(model)
        if stl.suffix.lower() == ".3mf":
            stl = Path(tmp) / "modelo.stl"
            threemf_to_stl(model, stl)
        err = ""
        for engine in ("EEVEE", "CYCLES"):
            try:
                r = proc.run([str(BLENDER), "-b", "-P", str(SCENE), "--", str(stl), str(outdir), str(cfgfile), engine],
                                   capture_output=True, text=True, timeout=900)
            except proc.TimeoutExpired:
                raise ValueError("a geração das imagens passou de 15 minutos")
            files = sorted(outdir.glob("render_*.jpg"))
            if len(files) == len(cfg["views"]):
                if cfg["background"] == "white":  # a foto principal do ML precisa de fundo branco puro
                    for f, v in zip(files, cfg["views"]):
                        if not v.startswith("uso"):  # o cenário em uso mantém a cor do ambiente
                            whiten(f)
                return files
            err = (r.stderr or r.stdout)[-300:]
    raise ValueError(f"o Blender não gerou as imagens: {err}")


def camera_path(n):
    """Trajetória do vídeo: n quadros (az, el, t) com a câmera abrindo na sala e fechando na peça, suavizada no começo e no fim (smoothstep)."""
    out = []
    for i in range(n):
        x = i / max(n - 1, 1)
        t = x * x * (3 - 2 * x)
        out.append((28 + (-24 - 28) * t, 10 + (6 - 10) * t, t))
    return out


def render_frames(model, outdir, n, engine="EEVEE", res=(1080, 1920), title="", cfg=None, on_time=lambda spf: None, timeout=6 * 3600):
    """Quadros do vídeo em outdir/render_1.jpg... (câmera em movimento no cenário 'em uso'). engine: 'EEVEE' (rápido) ou 'CYCLES' (demora horas).
    on_time recebe os segundos por quadro medidos, para a estimativa da próxima vez. Devolve os caminhos em ordem."""
    if not BLENDER.exists():
        raise ValueError("Blender não encontrado em tools/blender")
    cfg = clean_render_cfg(dict(cfg or {}, views=["uso"]))
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("render_*.jpg"):
        old.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        scene_cfg = cfg | dict(polyhaven=str(polyhaven.ROOT) if polyhaven.available() else "", contexto=scene_for(cfg, title), objeto=prop_for(title), still_cycles=False, res=list(res),
                               views=[("uso", az, el, 1.0, t) for az, el, t in camera_path(n)], samples_eevee=QUALITY[cfg["quality"]][0],
                               samples_cycles=QUALITY[cfg["quality"]][1], dist=FILL[cfg["fill"]])
        cfgfile = Path(tmp) / "cfg.json"
        cfgfile.write_text(json.dumps(scene_cfg), encoding="utf-8")
        stl = Path(model)
        if stl.suffix.lower() == ".3mf":
            stl = Path(tmp) / "modelo.stl"
            threemf_to_stl(model, stl)
        err = ""
        for eng in ((engine,) if engine == "CYCLES" else ("EEVEE", "CYCLES")):
            t0 = time.time()
            try:
                r = proc.run([str(BLENDER), "-b", "-P", str(SCENE), "--", str(stl), str(outdir), str(cfgfile), eng], capture_output=True, text=True, timeout=timeout)
            except proc.TimeoutExpired:
                raise ValueError("a geração dos quadros do vídeo passou do tempo limite")
            files = [outdir / f"render_{i}.jpg" for i in range(1, n + 1)]
            if all(f.is_file() for f in files):
                on_time((time.time() - t0) / n)
                return files
            err = (r.stderr or r.stdout)[-300:]
    raise ValueError(f"o Blender não gerou os quadros do vídeo: {err}")
