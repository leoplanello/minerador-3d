"""Estúdio do produto: a partir do modelo 3D, gera no Blender as fotos 1:1 em fundo branco (1920 px), a imagem com régua e
medidas, e o giro de 360° em 1080x1920 (9:16) com o ffmpeg. Só usa as ferramentas portáteis já instaladas pelo app."""
import json
import math
import re
import shutil
import struct
import tempfile
from pathlib import Path

import proc
import video
from paths import RESOURCES, TOOLS

SCENE = RESOURCES / "scripts" / "app" / "estudio_blender.py"


def _blender():
    from render import BLENDER
    return BLENDER


def modelo_para_stl(src, dst):
    """3MF -> STL binário com as peças do arquivo montadas: aplica a transformação de cada componente e do item do build.
    (O conversor da sala ignora as transformações; aqui elas contam, porque um modelo pode ter várias peças.)"""
    import zipfile
    z = zipfile.ZipFile(src)

    def mat(t):  # 12 números do 3MF: linhas 3x3 + translação; p (linha) @ M
        v = [float(x) for x in t.split()]
        return [[v[0], v[1], v[2], 0.0], [v[3], v[4], v[5], 0.0], [v[6], v[7], v[8], 0.0], [v[9], v[10], v[11], 1.0]]

    def ap(p, M):
        return tuple(p[0] * M[0][i] + p[1] * M[1][i] + p[2] * M[2][i] + M[3][i] for i in range(3))

    def mul(A, B):
        return [[sum(A[i][k] * B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

    ident = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    modelo_xml = z.read("3D/3dmodel.model").decode("utf-8", "replace")
    objetos = {}  # id -> lista de (arquivo, id do objeto no arquivo, transformação)
    for m in re.finditer(r'<object id="(\d+)"[^>]*>(.*?)</object>', modelo_xml, re.S):
        objetos[m.group(1)] = [(c[0].lstrip("/"), c[1], mat(c[2]) if c[2] else ident) for c in
                               re.findall(r'<component p:path="([^"]+)" objectid="(\d+)"[^>]*?transform="([^"]+)"', m.group(2))]
        if not objetos[m.group(1)]:  # malha direta no próprio arquivo
            objetos[m.group(1)] = [("3D/3dmodel.model", m.group(1), ident)]
    itens = []
    for m in re.finditer(r"<item ([^>]*)/>", modelo_xml):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        itens.append((attrs["objectid"], mat(attrs["transform"]) if "transform" in attrs else ident))
    if not itens:
        raise ValueError("o arquivo 3MF não tem peças para montar")
    cache, tris = {}, []
    for oid, Mb in itens:
        for arquivo, cid, Mc in objetos.get(oid, []):
            chave = (arquivo, cid)
            if chave not in cache:
                dados = modelo_xml if arquivo == "3D/3dmodel.model" else z.read(arquivo).decode("utf-8", "replace")
                blk = re.search(r'<object id="%s"[^>]*>(.*?)</object>' % cid, dados, re.S)
                if not blk:
                    raise ValueError("peça não encontrada no 3MF")
                vs = [tuple(float(x) for x in (a, b, c)) for a, b, c in re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', blk.group(1))]
                ts = [tuple(int(x) for x in t) for t in re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"', blk.group(1))]
                cache[chave] = (vs, ts)
            vs, ts = cache[chave]
            M = mul(Mc, Mb)
            pts = [ap(p, M) for p in vs]
            tris += [(pts[a], pts[b], pts[c]) for a, b, c in ts]
    if not tris:
        raise ValueError("o arquivo 3MF não tem triângulos")
    with open(dst, "wb") as f:
        f.write(b"Minerador 3D estudio".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            f.write(struct.pack("<3f3f3f3f H", 0, 0, 0, *a, *b, *c, 0))
    return len(tris)


def sobre_branco(arquivo):
    """Põe a imagem (com fundo transparente, do Blender) sobre branco puro e grava em RGB. A sombra continua, o fundo fica #FFFFFF."""
    from PIL import Image
    with Image.open(arquivo) as im:
        base = Image.new("RGB", im.size, (255, 255, 255))
        base.paste(im.convert("RGBA"), (0, 0), im.convert("RGBA"))
        base.save(arquivo)


COR_PADRAO = "#E8478B"  # rosa: é a cor que o produto sai na impressão; a tela deixa trocar


def cor_linear(hexa):
    """#RRGGBB (como a cor aparece na tela) -> cor RGBA linear, que é o que o Blender usa no material."""
    h = hexa.strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", h):
        raise ValueError("cor inválida: use #RRGGBB")
    canais = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in canais]
    return lin + [1.0]


def _fonte(tamanho):
    from PIL import ImageFont
    for nome in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default(size=tamanho)


def cotas_2d(arquivo, medidas):
    """Desenha sobre a imagem as três medidas em mm (largura, profundidade e altura) como linhas de cota e texto 2D.
    Os cantos vêm do Blender já em pixels; não há régua nem objeto 3D."""
    from PIL import Image, ImageDraw
    c = {k: tuple(v) for k, v in medidas["cantos"].items()}
    dx, dy, dz = medidas["dimensoes_mm"]
    im = Image.open(arquivo).convert("RGB")
    d = ImageDraw.Draw(im)
    tam = im.width / 34
    fonte = _fonte(int(tam))
    cor = (34, 34, 34)
    cotas = [
        (c["000"], c["100"], (0, tam * 2.2), f"Largura {dx:.0f} mm"),       # frente, embaixo
        (c["100"], c["110"], (tam * 2.2, 0), f"Profundidade {dy:.0f} mm"),  # lado direito, embaixo
        (c["000"], c["001"], (-tam * 2.2, 0), f"Altura {dz:.0f} mm"),       # aresta vertical da frente esquerda
    ]
    for p0, p1, (ox, oy), texto in cotas:
        q0, q1 = (p0[0] + ox, p0[1] + oy), (p1[0] + ox, p1[1] + oy)
        d.line([p0, q0], fill=cor, width=2)  # linhas de extensão
        d.line([p1, q1], fill=cor, width=2)
        d.line([q0, q1], fill=cor, width=3)  # linha de cota
        for ponta, outra in ((q0, q1), (q1, q0)):  # setas nas duas pontas
            vx, vy = outra[0] - ponta[0], outra[1] - ponta[1]
            n = max((vx * vx + vy * vy) ** 0.5, 1)
            ux, uy = vx / n, vy / n
            for ang in (0.5, -0.5):
                ca, sa = math.cos(ang), math.sin(ang)
                ax, ay = ux * ca - uy * sa, ux * sa + uy * ca
                d.line([ponta, (ponta[0] + ax * tam * 0.6, ponta[1] + ay * tam * 0.6)], fill=cor, width=3)
        mx, my = (q0[0] + q1[0]) / 2, (q0[1] + q1[1]) / 2
        larg = d.textlength(texto, font=fonte)
        caixa = [mx - larg / 2 - 10, my - tam * 0.75, mx + larg / 2 + 10, my + tam * 0.75]
        d.rectangle(caixa, fill=(255, 255, 255))
        d.text((mx - larg / 2, my - tam * 0.6), texto, fill=cor, font=fonte)
    im.save(arquivo)


def gerar(modelo, pasta, cor=COR_PADRAO, amostras=256, frames=120, fps=30):
    """modelo: .stl ou .3mf. Gera tudo em pasta/ e devolve os caminhos e as medidas (mm)."""
    modelo, pasta = Path(modelo), Path(pasta)
    blender = _blender()
    if not blender.exists():
        raise ValueError("Blender portátil não instalado: abra Configurações e instale as ferramentas")
    if not video.FFMPEG or not Path(video.FFMPEG).exists():
        raise ValueError("ffmpeg não instalado: ele é necessário para montar o vídeo de 360°")
    pasta.mkdir(parents=True, exist_ok=True)
    trabalho = Path(tempfile.mkdtemp(prefix="estudio-"))
    try:
        stl = trabalho / "modelo.stl"
        if modelo.suffix.lower() == ".3mf":
            modelo_para_stl(modelo, stl)
        else:
            shutil.copyfile(modelo, stl)
        cfg = trabalho / "cfg.json"
        cfg.write_text(json.dumps(dict(cor=cor_linear(cor), amostras=amostras, frames=frames, fps=fps, quadrado=1920, vertical_w=1080, vertical_h=1920)), encoding="utf-8")
        r = proc.run([str(blender), "-b", "--factory-startup", "-P", str(SCENE), "--", str(stl), str(pasta), str(cfg)],
                     capture_output=True, text=True, timeout=6 * 3600)
        m = re.search(r"CONCLUIDO (\{.*\})", r.stdout or "")
        if r.returncode != 0 or not m:
            raise ValueError("o Blender não terminou o estúdio: " + ((r.stderr or r.stdout or "")[-300:]))
        dims = json.loads(m.group(1))["dimensoes_mm"]
        frames_dir = pasta / "orbita"
        mp4 = pasta / "giro-360-9x16.mp4"
        for arquivo in sorted(pasta.glob("angulo_*.png")) + [pasta / "medidas.png"] + sorted(frames_dir.glob("frame_*.png")):
            sobre_branco(arquivo)  # antes do vídeo: o fundo transparente vira branco puro
        cotas_2d(pasta / "medidas.png", json.loads((pasta / "medidas.json").read_text(encoding="utf-8")))
        r = proc.run([str(video.FFMPEG), "-y", "-v", "error", "-framerate", str(fps), "-i", str(frames_dir / "frame_%04d.png"),
                      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", str(mp4)],
                     capture_output=True, text=True, timeout=1800)
        if r.returncode != 0 or not mp4.is_file():
            raise ValueError("ffmpeg não montou o vídeo: " + (r.stderr or "")[-300:])
        shutil.rmtree(frames_dir, ignore_errors=True)
        fotos = sorted(pasta.glob("angulo_*.png"))
        return dict(imagens=[str(f) for f in fotos], medidas=str(pasta / "medidas.png"), video=str(mp4), dimensoes_mm=dims)
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)
