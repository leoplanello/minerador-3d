"""Gera as fotos do anúncio a partir do modelo 3D usando o Blender portátil (tools/blender)."""
import json
import re
import polyhaven
import salas
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
         "uso": (26, 10, 1.0), "uso_perto": (-34, 12, 0.6), "uso_medio": (-22, 9, 1.0), "uso_aberto": (32, 12, 1.0),
         "cena": (-34, 12, 1.0), "cena_frontal": (0, 4, 1.0), "cena_close": (-25, 10, 1.0), "cena_orbital": (0, 10, 1.0)}  # "uso*": a peça instalada no cenário (parede ou mesa)
VIEW_LABELS = {"frente": "Frente 3/4", "lado": "Lado", "cima": "De cima", "tras": "Trás 3/4", "frontal": "Frontal", "topo": "Topo", "perfil": "Perfil", "detalhe": "Detalhe (zoom)",
               "uso": "Em uso (com o objeto)", "uso_perto": "Em uso, detalhe de perto", "uso_medio": "Ambiente médio", "uso_aberto": "Ambiente aberto"}
QUALITY = {"rapido": (16, 12), "normal": (32, 24), "alta": (64, 64)}  # amostras EEVEE, Cycles
CENA_FINAL_AMOSTRAS = 128  # imagem final da sala virtual
FILL = {"perto": 2.4, "medio": 3.2, "longe": 3.8}  # distância da câmera em tamanhos da peça: quanto menor, mais a peça enche a imagem
RENDER_DEFAULT = dict(color="#3a3a3a", finish="matte", background="white", views=["frente", "uso_perto", "uso", "uso_medio", "uso_aberto"], size=1200,
                      quality="normal", light="normal", shadow=True, fill="medio", turn=0, contexto="auto", ambiente="auto")
WALL_WORDS = ("parede", "wall", "suporte", "porta-", "porta ", "prateleira", "gancho", "cabide", "organizador")  # o que se instala na parede
CHOICES = dict(finish=("matte", "gloss", "silk"), background=("white", "gray", "warm"), quality=tuple(QUALITY), light=("soft", "normal", "strong"), fill=tuple(FILL), contexto=("auto", "parede", "mesa"), ambiente=("auto", "sala", "entrada", "escritorio"))


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


PROPS = {"chaves": ("chave", "chaveiro", "key"), "modem": ("roteador", "modem", "router")}  # objeto que a peça segura ou sustenta, pelo título; o modem é um bloco em escala, com a peça de cada lado


def prop_for(title):
    t = title.lower()
    return next((k for k, words in PROPS.items() if any(w in t for w in words)), "")


ROOM_WORDS = {"entrada": ("chave", "chaveiro", "corredor", "entrada", "casaco", "guarda-chuva", "bolsa"),
              "escritorio": ("roteador", "modem", "cabo", "fone", "monitor", "notebook", "celular", "caneta", "headset", "mouse")}  # o resto vai para a sala


def room_for(cfg, title=""):
    """Ambiente das vistas 'em uso' (polyhaven.ROOMS): o escolhido na tela ou, no automático, pelo tipo de produto no título."""
    if cfg["ambiente"] != "auto":
        return cfg["ambiente"]
    t = title.lower()
    return next((r for r, words in ROOM_WORDS.items() if any(w in t for w in words)), "sala")


def room_cfg(cfg, title):
    """O que o Blender precisa da sala: o ambiente, o objeto que acompanha a peça e como a peça é montada (fixada na parede ou aparelho em pé sobre o móvel)."""
    obj = prop_for(title)
    return dict(sala=polyhaven.ROOMS[room_for(cfg, title)], objeto=obj, montagem="sobre_movel" if obj == "modem" else "parede_alta")


def finish_photo(path):
    """Vinheta leve e um pouco de grão nas fotos 'em uso': tira o ar de render limpo demais."""
    from PIL import Image, ImageChops
    im = Image.open(path).convert("RGB")
    w, h = im.size
    vig = Image.radial_gradient("L").resize((w, h)).point(lambda v: 255 - int(0.30 * v))
    im = ImageChops.multiply(im, Image.merge("RGB", (vig,) * 3))
    im = ImageChops.add(im, Image.effect_noise((w, h), 5).convert("RGB"), 1, -128)
    im.save(path, quality=93)


def scene_for(cfg, title=""):
    """Cenário das vistas 'em uso': o escolhido na tela ou, no automático, parede quando o título fala de parede/suporte, senão mesa."""
    if cfg["contexto"] != "auto":
        return cfg["contexto"]
    t = title.lower()
    return "parede" if "parede" in t or "wall" in t or (any(w in t for w in WALL_WORDS) and "mesa" not in t and "bancada" not in t) else "mesa"


CENA_DEFAULT = dict(ambiente="sala", colocacao="mesa", escala_pct=100, giro=0, referencia="nenhuma", camera="3/4", luz="dia", modelo="produto", limite_s=600)
CENA_CHOICES = dict(ambiente=tuple(polyhaven.ROOMS) + tuple(salas.SALAS), colocacao=("chao", "mesa", "parede", "prateleira"), referencia=("nenhuma", "moeda", "caneca", "celular"),
                    camera=("3/4", "frontal", "close", "orbital"), luz=("dia", "tarde", "noite"), modelo=("produto", "enviado"))
CENA_VIEW = {"3/4": "cena", "frontal": "cena_frontal", "close": "cena_close", "orbital": "cena"}  # a câmera orbital só se move no vídeo; na imagem vale o 3/4


def clean_cena(d):
    """Valida a sala virtual vinda da tela e completa com o padrão. Levanta ValueError com o motivo."""
    c = CENA_DEFAULT | {k: v for k, v in (d or {}).items() if k in CENA_DEFAULT}
    for k, ok in CENA_CHOICES.items():
        if c[k] not in ok:
            raise ValueError(f"{k}: opção inválida")
    try:
        esc, giro = float(c["escala_pct"]), int(c["giro"])
    except (TypeError, ValueError):
        raise ValueError("escala ou giro inválido")
    if not 10 <= esc <= 500:
        raise ValueError("a escala deve ficar entre 10% e 500%")
    if not 0 <= giro < 360:
        raise ValueError("o giro deve ficar entre 0 e 359 graus")
    try:
        lim = int(c["limite_s"])
    except (TypeError, ValueError):
        raise ValueError("limite de tempo inválido")
    if not 30 <= lim <= 7200:
        raise ValueError("o limite de tempo do render deve ficar entre 30 segundos e 2 horas")
    return c | dict(escala_pct=esc, giro=giro, limite_s=lim)


def cena_cfg(c):
    """O que o Blender recebe da sala virtual: o ambiente escolhido e os controles; sem o objeto automático (modem, chaves) do produto."""
    if c["ambiente"] in salas.SALAS:  # sala 3D importada (GLB/FBX): o Blender importa o arquivo e acha onde pôr a peça
        f = salas.modelo(c["ambiente"])
        if not f:
            raise ValueError(f"baixe a sala {salas.SALAS[c['ambiente']]['label']} antes de usar")
        return dict(cena=c, sala=dict(importada=str(f), id=c["ambiente"]), objeto="", montagem="", polyhaven=str(polyhaven.ROOT))
    return dict(cena=c, sala=polyhaven.ROOMS[c["ambiente"]], objeto="", montagem="")


def orbit_path(n):
    """Câmera orbital do vídeo: dá meia volta suave em volta da peça (de -70 a +70 graus), com começo e fim lentos."""
    out = []
    for i in range(n):
        x = i / max(n - 1, 1)
        t = x * x * (3 - 2 * x)
        out.append((-70 + 140 * t, 12 - 4 * t, t))
    return out


def render_cena(model, outdir, cena, preview=False, title=""):
    """Imagem da sala virtual com a peça (a do produto ou uma enviada). preview=True: EEVEE em 640 px e poucas amostras, em segundos;
    senão 1200 px em Cycles com denoiser. Devolve o caminho do JPG (render_1.jpg em outdir)."""
    c = clean_cena(cena)
    cfg = dict(views=[CENA_VIEW[c["camera"]]], size=640 if preview else 1200, quality="rapido" if preview else "normal", background="gray", fill="perto")
    files = render_images(model, outdir, cfg, title=title, cena=c, preview=preview)
    return files[0]


BLEND_SCRIPT = RESOURCES / "scripts" / "app" / "blender_blend.py"
BLEND_VIEWS = ("cena", "cena_frontal", "cena_close")


def _blender(args, timeout=900):
    """Roda o Blender sem janela (headless) e levanta ValueError com o fim do log se falhar."""
    try:
        r = proc.run([str(BLENDER), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except proc.TimeoutExpired:
        raise ValueError("o Blender passou do tempo limite")
    return r


def gerar_blend(model, blend, cena, title=""):
    """Monta a sala virtual (ambiente, móveis, luz, peça) e a salva como sala.blend: cada móvel é um objeto separado, com 3 câmeras (3/4, frontal, close).
    Texturas e HDRI vão empacotados dentro do arquivo, então ele abre em qualquer pasta. Devolve o caminho."""
    if not BLENDER.exists():
        raise ValueError("Blender não encontrado em tools/blender")
    c = clean_cena(cena)
    if c["ambiente"] not in salas.SALAS and not polyhaven.available():
        raise ValueError("os ativos da sala (Poly Haven) ainda não foram baixados")
    blend = Path(blend)
    blend.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cfg = clean_render_cfg(dict(views=["uso"], size=640, quality="rapido", background="gray", fill="perto"))
        scene_cfg = cfg | dict(polyhaven=str(polyhaven.ROOT), views=[(v, *VIEWS[v]) for v in BLEND_VIEWS], contexto=scene_for(cfg, title), **room_cfg(cfg, title),
                               samples_eevee=1, samples_cycles=1, dist=FILL[cfg["fill"]], still_cycles=False, salvar=str(blend))
        scene_cfg |= cena_cfg(c)
        cfgfile = Path(tmp) / "cfg.json"
        cfgfile.write_text(json.dumps(scene_cfg), encoding="utf-8")
        stl = Path(model)
        if stl.suffix.lower() == ".3mf":
            stl = Path(tmp) / "modelo.stl"
            threemf_to_stl(model, stl)
        tmp_blend = blend.with_suffix(".novo.blend")
        scene_cfg["salvar"] = str(tmp_blend)  # só troca o arquivo bom quando o novo ficou pronto
        cfgfile.write_text(json.dumps(scene_cfg), encoding="utf-8")
        r = _blender(["-b", "-P", str(SCENE), "--", str(stl), str(Path(tmp)), str(cfgfile), "EEVEE"])
        if not tmp_blend.is_file():
            raise ValueError(f"o Blender não gerou a sala: {(r.stderr or r.stdout)[-300:]}")
        tmp_blend.replace(blend)
    return blend


def blend_adicionar(blend, itens):
    """Põe móveis e modelos na sala.blend (sem janela). itens: [{nome, caminho, tipo, fonte, x, y, z, giro}]."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "itens.json"
        f.write_text(json.dumps(itens), encoding="utf-8")
        r = _blender(["-b", str(blend), "-P", str(BLEND_SCRIPT), "--", "adicionar", str(f)])
    if r.returncode != 0 or "Traceback" in (r.stderr or "") + (r.stdout or ""):
        raise ValueError(f"o Blender não conseguiu adicionar ao arquivo: {(r.stderr or r.stdout)[-300:]}")


def blend_layout(blend, saida):
    """Escreve o layout em mm (id, tipo, fonte, posição, giro, escala de cada objeto) do que está na sala.blend."""
    r = _blender(["-b", str(blend), "-P", str(BLEND_SCRIPT), "--", "exportar", str(saida)], timeout=300)
    if not Path(saida).is_file():
        raise ValueError(f"não consegui ler o arquivo da sala: {(r.stderr or r.stdout)[-300:]}")


def _render_blend(blend, outdir, cfg, engine, timeout):
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("render_*.jpg"):
        old.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "cfg.json"
        f.write_text(json.dumps(cfg), encoding="utf-8")
        r = _blender(["-b", str(blend), "-P", str(BLEND_SCRIPT), "--", "renderizar", str(outdir), str(f), engine], timeout=timeout)
    return r


def render_blend(blend, outdir, camera="cena", preview=False, engine=None, limite_s=600):
    """Imagem da sala.blend com a câmera e a luz que estão no arquivo (a câmera: cena, cena_frontal ou cena_close). Devolve o JPG."""
    q = QUALITY["rapido" if preview else "normal"]
    cfg = dict(cameras=[f"cam-{camera}"], res=[640, 640] if preview else [1200, 1200], samples_eevee=q[0], samples_cycles=q[1] if preview else CENA_FINAL_AMOSTRAS,
               time_limit=0 if preview else limite_s)
    r = _render_blend(blend, outdir, cfg, engine or ("EEVEE" if preview else "CYCLES"), 900)
    f = outdir / "render_1.jpg"
    if not f.is_file():
        raise ValueError(f"o Blender não gerou a imagem: {(r.stderr or r.stdout)[-300:]}")
    finish_photo(f)
    return f


def render_blend_frames(blend, outdir, n, engine="EEVEE", res=(1080, 1920), on_time=lambda spf: None, timeout=6 * 3600):
    """Quadros do vídeo orbital em volta do objeto 'peca' da sala.blend, na altura e distância da câmera 3/4 do arquivo."""
    q = QUALITY["rapido"]
    t0 = time.time()
    cfg = dict(cameras=["cam-cena"], res=list(res), samples_eevee=q[0], samples_cycles=q[1], orbita=orbit_path(n))
    r = _render_blend(blend, outdir, cfg, engine, timeout)
    files = [outdir / f"render_{i}.jpg" for i in range(1, n + 1)]
    if not all(f.is_file() for f in files):
        raise ValueError(f"o Blender não gerou os quadros do vídeo: {(r.stderr or r.stdout)[-300:]}")
    on_time((time.time() - t0) / n)
    return files


def render_images(model, outdir, cfg=None, title="", cena=None, preview=False):
    """Devolve a lista de JPGs gerados (render_1.jpg...). Tenta EEVEE e cai para Cycles (CPU) se a placa de vídeo não aceitar.
    cfg: dict de clean_render_cfg ou, por compatibilidade, só a cor '#rrggbb'. title: título do anúncio, escolhe o cenário das vistas 'em uso'."""
    if not BLENDER.exists():
        raise ValueError("Blender não encontrado em tools/blender")
    cfg = clean_render_cfg(dict(color=cfg) if isinstance(cfg, str) else cfg)
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("render_*.jpg"):
        old.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        scene_cfg = cfg | dict(polyhaven=str(polyhaven.ROOT) if polyhaven.available() else "", views=[(v, *VIEWS[v]) for v in cfg["views"]], contexto=scene_for(cfg, title), **room_cfg(cfg, title), samples_eevee=QUALITY[cfg["quality"]][0], samples_cycles=QUALITY[cfg["quality"]][1], dist=FILL[cfg["fill"]])
        scene_cfg |= (cena_cfg(cena) | dict(still_cycles=not preview)) if cena else {}
        if cena and not preview:  # imagem final da sala virtual: Cycles com denoiser, no mínimo 128 amostras, parando no limite de tempo
            scene_cfg |= dict(samples_cycles=CENA_FINAL_AMOSTRAS, time_limit=clean_cena(cena)["limite_s"])
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
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
            except proc.TimeoutExpired:
                raise ValueError("a geração das imagens passou de 15 minutos")
            files = sorted(outdir.glob("render_*.jpg"))
            if len(files) == len(cfg["views"]):
                if cfg["background"] == "white":  # a foto principal do ML precisa de fundo branco puro
                    for f, v in zip(files, cfg["views"]):
                        if not v.startswith(("uso", "cena")):  # o cenário em uso mantém a cor do ambiente
                            whiten(f)
                for f, v in zip(files, cfg["views"]):
                    if v.startswith(("uso", "cena")):
                        finish_photo(f)
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


def render_frames(model, outdir, n, engine="EEVEE", res=(1080, 1920), title="", cfg=None, on_time=lambda spf: None, timeout=6 * 3600, cena=None):
    """Quadros do vídeo em outdir/render_1.jpg... (câmera em movimento no cenário 'em uso'). engine: 'EEVEE' (rápido) ou 'CYCLES' (demora horas).
    on_time recebe os segundos por quadro medidos, para a estimativa da próxima vez. Devolve os caminhos em ordem."""
    if not BLENDER.exists():
        raise ValueError("Blender não encontrado em tools/blender")
    cfg = clean_render_cfg(dict(cfg or {}, views=["uso"]))
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("render_*.jpg"):
        old.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        scene_cfg = cfg | dict(polyhaven=str(polyhaven.ROOT) if polyhaven.available() else "", contexto=scene_for(cfg, title), **room_cfg(cfg, title), still_cycles=False, res=list(res),
                               views=[("cena_orbital" if cena else "uso", az, el, 1.0, t) for az, el, t in (orbit_path(n) if cena else camera_path(n))],
                               samples_eevee=QUALITY[cfg["quality"]][0], samples_cycles=QUALITY[cfg["quality"]][1], dist=FILL[cfg["fill"]])
        scene_cfg |= (cena_cfg(clean_cena(cena)) | dict(still_cycles=False)) if cena else {}
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
                r = proc.run([str(BLENDER), "-b", "-P", str(SCENE), "--", str(stl), str(outdir), str(cfgfile), eng], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            except proc.TimeoutExpired:
                raise ValueError("a geração dos quadros do vídeo passou do tempo limite")
            files = [outdir / f"render_{i}.jpg" for i in range(1, n + 1)]
            if all(f.is_file() for f in files):
                on_time((time.time() - t0) / n)
                return files
            err = (r.stderr or r.stdout)[-300:]
    raise ValueError(f"o Blender não gerou os quadros do vídeo: {err}")
