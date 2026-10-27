"""Roda DENTRO do Blender: blender -b -P blender_scene.py -- <modelo.stl> <pasta de saída> <config.json> <EEVEE|CYCLES>
Gera uma imagem quadrada por vista pedida na config (render.RENDER_DEFAULT descreve os campos).
Vistas de estúdio: peça sobre fundo liso (a foto principal do ML). Vistas "uso*": a peça instalada num cenário
(parede ou mesa) com luz de janela e profundidade de campo, para mostrar o produto pronto no ambiente."""
import json
import math
import sys

import bpy
from mathutils import Matrix, Vector

model, outdir, cfgfile, engine = sys.argv[sys.argv.index("--") + 1:][:4]
cfg = json.load(open(cfgfile, encoding="utf-8"))
color = cfg["color"]
ctx_kind = cfg["contexto"]  # "parede" ou "mesa" (render.py já resolveu o "auto")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=model)
obj = bpy.context.selected_objects[0]
bpy.context.view_layer.objects.active = obj
bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))  # cantos vivos ficam vivos, curvas ficam lisas


def bounds(o):
    corners = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return Vector((min(c[i] for c in corners) for i in range(3))), Vector((max(c[i] for c in corners) for i in range(3)))


def back_axis(o):
    """Direção local da face de trás: o eixo mais fino do modelo, no lado que tem mais área plana (a placa que encosta na parede)."""
    lo, hi = bounds(o)
    dims = hi - lo
    ax = min(range(3), key=lambda i: dims[i])
    area = {1: 0.0, -1: 0.0}
    for p in o.data.polygons:
        for s in (1, -1):
            edge = hi[ax] if s == 1 else lo[ax]
            if p.normal[ax] * s > 0.95 and abs(p.center[ax] - edge) < 0.08 * dims[ax] + 1e-6:
                area[s] += p.area
    s = 1 if area[1] >= area[-1] else -1
    return Vector((s if i == ax else 0) for i in range(3)), ax, dims


# peça de estúdio: centralizada no XY e apoiada na mesa (z = 0)
lo, hi = bounds(obj)
back, back_ax, dims0 = back_axis(obj)
obj.location -= Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
size = max(hi - lo)  # a peça maior define a distância da câmera
center = Vector((0, 0, (hi.z - lo.z) / 2))

hexc = color.lstrip("#")
rgb = [(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4) for c in (int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))]  # hex é sRGB, o Blender quer linear
mat = bpy.data.materials.new("peca")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (*rgb, 1)
rough, spec, metal = {"matte": (0.7, 0.2, 0.0), "gloss": (0.18, 0.6, 0.0), "silk": (0.3, 0.5, 0.45)}[cfg["finish"]]
bsdf.inputs["Roughness"].default_value = rough
bsdf.inputs["Specular IOR Level"].default_value = spec
bsdf.inputs["Metallic"].default_value = metal
obj.data.materials.append(mat)


def make_mat(name, rough=0.9, **inputs):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = rough
    for k, v in inputs.items():
        b.inputs[k.replace("_", " ")].default_value = v
    return m, b


def procedural(m, b, scale, colors, kind="WAVE", bump=0.15):
    """Textura procedural (sem arquivos de imagem): madeira em faixas ou parede com leve granulação."""
    nt = m.node_tree
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tex = nt.nodes.new("ShaderNodeTexWave" if kind == "WAVE" else "ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    if kind == "WAVE":
        tex.inputs["Distortion"].default_value = 6
        tex.inputs["Detail"].default_value = 3
        tex.wave_type = "BANDS"
        tex.bands_direction = "X"
    nt.links.new(tc.outputs["Object"], tex.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*colors[0], 1)
    ramp.color_ramp.elements[1].color = (*colors[1], 1)
    nt.links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    bm = nt.nodes.new("ShaderNodeBump")
    bm.inputs["Strength"].default_value = bump
    nt.links.new(tex.outputs["Fac"], bm.inputs["Height"])
    nt.links.new(bm.outputs["Normal"], b.inputs["Normal"])


def plane(location, rotation, dim, material, name):
    bpy.ops.mesh.primitive_plane_add(size=1, location=location, rotation=rotation)
    p = bpy.context.object
    p.name = name
    p.scale = (dim[0], dim[1], 1)
    p.data.materials.append(material)
    return p


def aim(o, target):
    o.rotation_euler = (target - o.location).to_track_quat("-Z", "Y").to_euler()


# ---------- estúdio: fundo e mesa na mesma cor; sem sombra a mesa nem existe e a peça "flutua" ----------
studio, ctx = [], []
bg = {"white": (1, 1, 1), "gray": (0.82, 0.82, 0.84), "warm": (0.96, 0.93, 0.87)}[cfg["background"]]
if cfg["shadow"]:
    fm, fb = make_mat("mesa", 1, Base_Color=(*bg, 1))
    studio.append(plane((0, 0, 0), (0, 0, 0), (size * 12, size * 12), fm, "chao"))
world_studio = bpy.data.worlds.new("estudio")
world_studio.use_nodes = True
world_studio.node_tree.nodes["Background"].inputs["Color"].default_value = (*bg, 1)
world_studio.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.85
boost = {"soft": 0.65, "normal": 1.0, "strong": 1.5}[cfg["light"]]
for loc, k in [((size * 2, -size * 2, size * 3), 25 * boost), ((-size * 3, -size, size * 2), 10 * boost)]:
    bpy.ops.object.light_add(type="AREA", location=loc)
    light = bpy.context.object
    light.data.energy = k * size ** 2  # irradiância ~ potência / distância²; a distância é proporcional ao tamanho da peça
    light.data.size = size * 2
    aim(light, center)
    studio.append(light)

# ---------- cenário "em uso" ----------
world_ctx = bpy.data.worlds.new("ambiente")
world_ctx.use_nodes = True
world_ctx.node_tree.nodes["Background"].inputs["Color"].default_value = (0.78, 0.84, 0.95, 1)  # céu claro entrando pela janela
world_ctx.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.9

obj_ctx = obj.copy()  # mesma malha e material, posição própria
bpy.context.collection.objects.link(obj_ctx)
ctx.append(obj_ctx)
wall_m, wall_b = make_mat("parede", 0.95)
procedural(wall_m, wall_b, 400, [(0.55, 0.50, 0.44), (0.64, 0.59, 0.52)], kind="NOISE", bump=0.05)
if ctx_kind == "parede":
    # a face de trás encosta na parede (y = 0); o maior lado restante fica na vertical
    up_ax = max((i for i in range(3) if i != back_ax), key=lambda i: dims0[i])
    up = Vector((1 if i == up_ax else 0) for i in range(3))
    rot = Matrix((back.cross(up), back, up))  # linhas: x, y, z do mundo em coordenadas locais (y = para a parede)
    obj_ctx.rotation_mode = "QUATERNION"
    obj_ctx.rotation_quaternion = rot.to_quaternion()
    obj_ctx.location = (0, 0, 0)
    bpy.context.view_layer.update()
    clo, chi = bounds(obj_ctx)
    obj_ctx.location = Vector((-(clo.x + chi.x) / 2, -chi.y, -(clo.z + chi.z) / 2))  # costas em y = 0, centrado
    bpy.context.view_layer.update()
    clo, chi = bounds(obj_ctx)
    target = (clo + chi) / 2
    ctx.append(plane((0, 0.02 * size, 0), (math.radians(90), 0, 0), (size * 30, size * 30), wall_m, "parede"))
else:
    # mesa de madeira: a peça fica como sai da impressora, apoiada no tampo
    obj_ctx.location = obj.location
    wood_m, wood_b = make_mat("madeira", 0.55)
    procedural(wood_m, wood_b, 25, [(0.30, 0.17, 0.08), (0.52, 0.32, 0.16)], kind="WAVE", bump=0.1)
    ctx.append(plane((0, 0, -0.001 * size), (0, 0, 0), (size * 30, size * 30), wood_m, "mesa-madeira"))
    ctx.append(plane((0, size * 9, size * 5), (math.radians(90), 0, 0), (size * 40, size * 20), wall_m, "fundo"))
    target = center

# luz de janela: sol suave de fora, com caixilho que projeta sombra
sun_dir = Vector((-0.55, 0.65, -0.55)) if ctx_kind == "parede" else Vector((-0.5, 0.35, -0.8))
sun_dir.normalize()
bpy.ops.object.light_add(type="SUN", location=target - sun_dir * size * 8)
sun = bpy.context.object
sun.data.energy = {"soft": 1.0, "normal": 1.5, "strong": 2.2}[cfg["light"]]
sun.data.angle = math.radians(2.5)
sun.data.color = (1.0, 0.94, 0.84)
sun.rotation_euler = sun_dir.to_track_quat("-Z", "Y").to_euler()
ctx.append(sun)
q = sun_dir.to_track_quat("-Z", "Y")
bars = [  # (x, y, largura, altura) no plano da janela, em tamanhos da peça: moldura com cruz
    (-20, 0, 12, 60), (20, 0, 12, 60), (0, 16, 60, 12), (0, -16, 60, 12), (-1.6, 0, 0.5, 20), (1.4, 0, 0.5, 20), (0, 0.6, 20, 0.5)]
for ox, oy, w, h in bars:
    bpy.ops.mesh.primitive_cube_add(size=1)
    b = bpy.context.object
    b.location = target - sun_dir * size * 5 + q @ Vector((ox * size - 0.6 * size, oy * size + 0.3 * size, 0))
    b.rotation_euler = q.to_euler()
    b.scale = (w * size, h * size, 0.05 * size)
    b.visible_camera = False  # só projeta sombra, a câmera não vê a "janela"
    ctx.append(b)

scene = bpy.context.scene
scene.render.engine = "CYCLES" if engine == "CYCLES" else "BLENDER_EEVEE_NEXT"
if engine == "CYCLES":
    scene.cycles.samples = cfg["samples_cycles"]
    scene.cycles.device = "CPU"
    scene.cycles.use_denoising = True
else:
    scene.eevee.taa_render_samples = cfg["samples_eevee"]
scene.render.resolution_x = scene.render.resolution_y = cfg["size"]
scene.render.image_settings.file_format = "JPEG"
scene.render.image_settings.quality = 92
scene.view_settings.view_transform = "Standard"

bpy.ops.object.camera_add()
cam = bpy.context.object
scene.camera = cam
cam.data.lens = 50
for i, (name, az, el, zoom) in enumerate(cfg["views"], 1):
    in_use = name.startswith("uso")
    for o in studio:
        o.hide_render = in_use
    obj.hide_render = in_use
    for o in ctx:
        o.hide_render = not in_use
    scene.world = world_ctx if in_use else world_studio
    dist = size * cfg["dist"] * zoom
    focus = target if in_use else center
    a, e = math.radians(az + (-90 if in_use else cfg["turn"])), math.radians(el)
    cam.location = focus + Vector((dist * math.cos(e) * math.cos(a), dist * math.cos(e) * math.sin(a), dist * math.sin(e)))
    aim(cam, focus)
    cam.data.dof.use_dof = in_use  # fundo desfocado dá a cara de foto de ambiente
    cam.data.dof.focus_distance = (cam.location - focus).length
    cam.data.dof.aperture_fstop = 2.8
    scene.render.filepath = f"{outdir}/render_{i}.jpg"
    bpy.ops.render.render(write_still=True)
