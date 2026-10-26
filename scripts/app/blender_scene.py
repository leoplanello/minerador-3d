"""Roda DENTRO do Blender: blender -b -P blender_scene.py -- <modelo.stl> <pasta de saída> <config.json> <EEVEE|CYCLES>
Gera uma imagem quadrada por ângulo pedido na config (render.RENDER_DEFAULT descreve os campos)."""
import json
import math
import sys

import bpy
from mathutils import Vector

model, outdir, cfgfile, engine = sys.argv[sys.argv.index("--") + 1:][:4]
cfg = json.load(open(cfgfile, encoding="utf-8"))
color = cfg["color"]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=model)
obj = bpy.context.selected_objects[0]
bpy.context.view_layer.objects.active = obj
bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))  # cantos vivos ficam vivos, curvas ficam lisas

# centraliza no eixo XY e apoia na mesa (z = 0)
corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
lo = Vector((min(c[i] for c in corners) for i in range(3)))
hi = Vector((max(c[i] for c in corners) for i in range(3)))
obj.location -= Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
size = max(hi - lo)  # a peça maior define a distância da câmera
center = Vector((0, 0, (hi.z - lo.z) / 2))

hexc = color.lstrip("#")
rgb = [int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4)]
mat = bpy.data.materials.new("peca")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (*rgb, 1)
rough, spec, metal = {"matte": (0.7, 0.2, 0.0), "gloss": (0.18, 0.6, 0.0), "silk": (0.3, 0.5, 0.45)}[cfg["finish"]]
bsdf.inputs["Roughness"].default_value = rough
bsdf.inputs["Specular IOR Level"].default_value = spec
bsdf.inputs["Metallic"].default_value = metal
obj.data.materials.append(mat)

# fundo: mundo e mesa na mesma cor; sem sombra a mesa nem existe e a peça "flutua"
bg = {"white": (1, 1, 1), "gray": (0.82, 0.82, 0.84), "warm": (0.96, 0.93, 0.87)}[cfg["background"]]
if cfg["shadow"]:
    bpy.ops.mesh.primitive_plane_add(size=size * 12)
    floor = bpy.context.object
    fm = bpy.data.materials.new("mesa")
    fm.use_nodes = True
    fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*bg, 1)
    fm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1
    floor.data.materials.append(fm)
world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (*bg, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.85
bpy.context.scene.world = world
boost = {"soft": 0.65, "normal": 1.0, "strong": 1.5}[cfg["light"]]

for loc, k in [((size * 2, -size * 2, size * 3), 25 * boost), ((-size * 3, -size, size * 2), 10 * boost)]:
    bpy.ops.object.light_add(type="AREA", location=loc)
    light = bpy.context.object
    light.data.energy = k * size ** 2  # irradiância ~ potência / distância²; a distância é proporcional ao tamanho da peça
    light.data.size = size * 2
    light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()

scene = bpy.context.scene
scene.render.engine = "CYCLES" if engine == "CYCLES" else "BLENDER_EEVEE_NEXT"
if engine == "CYCLES":
    scene.cycles.samples = cfg["samples_cycles"]
    scene.cycles.device = "CPU"
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
for i, (az, el, zoom) in enumerate(cfg["views"], 1):
    dist = size * 3.8 * zoom
    a, e = math.radians(az), math.radians(el)
    cam.location = center + Vector((dist * math.cos(e) * math.cos(a), dist * math.cos(e) * math.sin(a), dist * math.sin(e)))
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = f"{outdir}/render_{i}.jpg"
    bpy.ops.render.render(write_still=True)
