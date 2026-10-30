"""Estúdio do produto no Blender (sem janela): modelo sozinho em fundo branco, com luz de área, sol para a sombra e
sombra de contato. Gera as fotos quadradas em vários ângulos, a imagem com régua e medidas, e a sequência do giro de 360°
no formato vertical. Uso: blender -b --factory-startup -P estudio_blender.py -- <modelo.stl> <pasta de saída> <config.json>"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

stl, saida, cfg_path = sys.argv[sys.argv.index("--") + 1:][:3]
cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
OUT = Path(saida)
OUT.mkdir(parents=True, exist_ok=True)
QUAD = cfg.get("quadrado", 1920)                 # fotos 1:1
VERT = (cfg.get("vertical_w", 1080), cfg.get("vertical_h", 1920))   # vídeo 9:16
AMOSTRAS = cfg.get("amostras", 256)
AMOSTRAS_VIDEO = cfg.get("amostras_video", 64)
LENTE = 85                                        # mm: perspectiva de produto, sem distorção

bpy.ops.wm.read_factory_settings(use_empty=True)
cena = bpy.context.scene
cena.render.engine = "CYCLES"
cena.cycles.device = "CPU"
try:  # com placa de vídeo (NVIDIA, AMD, Apple), o render sai bem mais rápido; sem ela, fica no processador
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for tipo in ("OPTIX", "CUDA", "HIP", "METAL"):
        prefs.compute_device_type = tipo
        prefs.get_devices()
        for d in prefs.devices:
            d.use = d.type != "CPU"
        if any(d.type != "CPU" for d in prefs.devices):
            cena.cycles.device = "GPU"
            break
        prefs.compute_device_type = "NONE"
except (KeyError, TypeError, AttributeError):
    pass
cena.cycles.use_denoising = True
cena.cycles.denoiser = "OPENIMAGEDENOISE"
cena.cycles.use_adaptive_sampling = True
cena.view_settings.view_transform = "Standard"    # o branco da imagem sai branco, sem a curva do AgX
cena.view_settings.look = "None"
cena.render.image_settings.file_format = "PNG"
cena.render.film_transparent = True          # fundo transparente: o branco puro entra depois, na composição (estudio.py)
cena.render.image_settings.color_mode = "RGBA"

# ---- modelo: STL em mm -> metros, centrado em x/y e apoiado em z = 0
bpy.ops.wm.stl_import(filepath=stl)
modelo = bpy.context.selected_objects[0]
modelo.name = "Produto"
modelo.scale = (0.001, 0.001, 0.001)
bpy.context.view_layer.update()
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
pts = [modelo.matrix_world @ Vector(c) for c in modelo.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
modelo.location = (-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z)
bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
pts = [modelo.matrix_world @ Vector(c) for c in modelo.bound_box]  # caixa depois de mover: é ela que vai para a cota
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
bpy.ops.object.shade_smooth()
dims_mm = [round((h - l) * 1000, 1) for l, h in zip(lo, hi)]
centro = Vector((0, 0, (hi.z - lo.z) / 2))
raio = Vector((hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)).length / 2

# material plástico (PLA) com textura de camada e sombra de contato (oclusão ambiente no tom)
mat = bpy.data.materials.new("Plástico")
mat.use_nodes = True
nt = mat.node_tree
b = nt.nodes["Principled BSDF"]
cor = cfg.get("cor", [0.86, 0.86, 0.84, 1.0])
b.inputs["Base Color"].default_value = cor
b.inputs["Roughness"].default_value = 0.42
ruido = nt.nodes.new("ShaderNodeTexNoise")
ruido.inputs["Scale"].default_value = 300
ruido.inputs["Detail"].default_value = 8
bump = nt.nodes.new("ShaderNodeBump")
bump.inputs["Strength"].default_value = 0.005
bump.inputs["Distance"].default_value = 0.0015
nt.links.new(ruido.outputs["Fac"], bump.inputs["Height"])
nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
ao.inputs["Distance"].default_value = 0.012
mult = nt.nodes.new("ShaderNodeMixRGB")
mult.blend_type = "MULTIPLY"
mult.inputs[0].default_value = 1.0
mult.inputs[1].default_value = cor
nt.links.new(ao.outputs["Color"], mult.inputs[2])
nt.links.new(mult.outputs["Color"], b.inputs["Base Color"])
modelo.data.materials.append(mat)

# ---- chão branco que só mostra a sombra (fundo branco contínuo)
bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, 0))
chao = bpy.context.object
chao.name = "Chão"
chao.is_shadow_catcher = True
mat_chao = bpy.data.materials.new("Branco")
mat_chao.use_nodes = True
mat_chao.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (1, 1, 1, 1)
chao.data.materials.append(mat_chao)

# ---- fundo branco e luz real: céu branco de fundo, luz de área grande (chave), preenchimento e sol para a sombra
mundo = bpy.data.worlds.new("Estúdio branco")
cena.world = mundo
mundo.use_nodes = True
mundo.node_tree.nodes["Background"].inputs["Color"].default_value = (1, 1, 1, 1)
mundo.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.12  # luz de preenchimento só para a peça


def luz_area(nome, pos, tamanho, energia, alvo):
    dados = bpy.data.lights.new(nome, "AREA")
    dados.energy = energia
    dados.size = tamanho
    dados.shape = "SQUARE"
    obj = bpy.data.objects.new(nome, dados)
    cena.collection.objects.link(obj)
    obj.location = pos
    obj.rotation_euler = (Vector(alvo) - Vector(pos)).to_track_quat("-Z", "Y").to_euler()
    return obj


luz_area("Chave", (-0.8, -1.0, 1.4), 1.2, 35, centro)
luz_area("Preenchimento", (1.2, -0.6, 0.9), 1.6, 8, centro)
luz_area("Recorte", (0.4, 1.4, 1.1), 0.8, 20, centro)
sol = bpy.data.lights.new("Sol", "SUN")
sol.energy = 0.9
sol.angle = math.radians(1.5)                  # sombra com borda suave, como luz de janela
sol_obj = bpy.data.objects.new("Sol", sol)
cena.collection.objects.link(sol_obj)
sol_obj.rotation_euler = Vector((0.35, 0.25, -1.0)).to_track_quat("-Z", "Y").to_euler()

# ---- câmera
cam_dados = bpy.data.cameras.new("Câmera")
cam_dados.lens = LENTE
camera = bpy.data.objects.new("Câmera", cam_dados)
cena.collection.objects.link(camera)
cena.camera = camera


def posicionar(az, el, distancia=None, alvo=centro):
    """Câmera em volta do produto: az = giro horizontal em graus, el = altura em graus."""
    meia = math.atan(18 / LENTE)
    d = distancia or raio / math.sin(meia) * 1.18
    a, e = math.radians(az), math.radians(el)
    camera.location = alvo + Vector((d * math.cos(e) * math.sin(a), -d * math.cos(e) * math.cos(a), d * math.sin(e)))
    camera.rotation_euler = (alvo - camera.location).to_track_quat("-Z", "Y").to_euler()


def render(arquivo, largura, altura, amostras):
    cena.render.resolution_x, cena.render.resolution_y = largura, altura
    cena.render.resolution_percentage = 100
    cena.cycles.samples = amostras
    cena.render.filepath = str(arquivo)
    bpy.ops.render.render(write_still=True)


# ---- imagens 1:1 em vários ângulos
angulos = cfg.get("angulos", [(0, 12), (45, 18), (90, 10), (135, 20), (180, 12), (225, 18), (270, 10), (315, 25), (0, 70)])
for i, (az, el) in enumerate(angulos, 1):
    posicionar(az, el)
    render(OUT / f"angulo_{i:02d}.png", QUAD, QUAD, AMOSTRAS)
    print("FOTO", i, flush=True)

# ---- imagem com régua e medidas (vista de frente, levemente de cima)
posicionar(20, 22, alvo=centro + Vector((0, 0, 0.0)))
cena.camera.data.lens = LENTE
render(OUT / "medidas.png", QUAD, QUAD, AMOSTRAS)
# cantos da caixa do produto na imagem (pixels): a cota em 2D é desenhada por estudio.py, sem objeto 3D
from bpy_extras.object_utils import world_to_camera_view
cantos = {}
for nome, (x, y, z) in {"000": (lo.x, lo.y, lo.z), "100": (hi.x, lo.y, lo.z), "010": (lo.x, hi.y, lo.z), "001": (lo.x, lo.y, hi.z),
                        "110": (hi.x, hi.y, lo.z), "101": (hi.x, lo.y, hi.z), "011": (lo.x, hi.y, hi.z), "111": (hi.x, hi.y, hi.z)}.items():
    v = world_to_camera_view(cena, camera, Vector((x, y, z)))
    cantos[nome] = [round(v.x * QUAD, 1), round((1 - v.y) * QUAD, 1)]
# silhueta do produto na imagem: os pontos mais à esquerda, à direita, no topo e na base (pixels), vindos dos vértices
extremos = {"esq": None, "dir": None, "topo": None, "base": None}
mw = modelo.matrix_world
for vert in modelo.data.vertices:
    v = world_to_camera_view(cena, camera, mw @ vert.co)
    p = (v.x * QUAD, (1 - v.y) * QUAD)
    if extremos["esq"] is None or p[0] < extremos["esq"][0]:
        extremos["esq"] = p
    if extremos["dir"] is None or p[0] > extremos["dir"][0]:
        extremos["dir"] = p
    if extremos["topo"] is None or p[1] < extremos["topo"][1]:
        extremos["topo"] = p
    if extremos["base"] is None or p[1] > extremos["base"][1]:
        extremos["base"] = p
silhueta = {k: [round(p[0], 1), round(p[1], 1)] for k, p in extremos.items()}
(OUT / "medidas.json").write_text(json.dumps(dict(cantos=cantos, silhueta=silhueta, dimensoes_mm=dims_mm, tamanho=QUAD)), encoding="utf-8")
print("MEDIDAS", flush=True)

# ---- giro de 360° no formato vertical 9:16: a câmera dá a volta completa, com a luz e o chão fixos
frames = int(cfg.get("frames", 120))
pasta_video = OUT / "orbita"
pasta_video.mkdir(exist_ok=True)
cena.frame_start, cena.frame_end = 1, frames
cena.render.fps = int(cfg.get("fps", 30))
cena.render.resolution_x, cena.render.resolution_y = VERT
cena.render.resolution_percentage = 100
cena.cycles.samples = AMOSTRAS_VIDEO
cena.render.image_settings.file_format = "PNG"
cena.render.filepath = str(pasta_video / "frame_")
for f in range(1, frames + 1):
    cena.frame_set(f)
    posicionar(360 * (f - 1) / frames, 14)
    camera.keyframe_insert("location", frame=f)
    camera.keyframe_insert("rotation_euler", frame=f)
bpy.context.scene.frame_set(1)
bpy.ops.render.render(animation=True)
print("VIDEO", frames, flush=True)
print("CONCLUIDO", json.dumps(dict(dimensoes_mm=dims_mm)), flush=True)
