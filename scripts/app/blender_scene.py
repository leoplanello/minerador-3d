"""Roda DENTRO do Blender: blender -b -P blender_scene.py -- <modelo.stl> <pasta de saída> <config.json> <EEVEE|CYCLES>
Gera uma imagem quadrada por vista pedida na config (render.RENDER_DEFAULT descreve os campos).
Vistas de estúdio: peça sobre fundo liso (a foto principal do ML). Vistas "uso*": a peça instalada num cenário
(parede ou mesa) com luz de janela e profundidade de campo, para mostrar o produto pronto no ambiente."""
import json
import math
import sys
from pathlib import Path

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


# ---------- sala realista (ativos CC0 do Poly Haven em cfg["polyhaven"]; sem eles, o cenário procedural abaixo) ----------
PH = Path(cfg["polyhaven"]) if cfg.get("polyhaven") else None


def tex_material(name, folder, tile, axes):
    """Material com as texturas do Poly Haven (cor, rugosidade, normal) projetadas pela posição no mundo, em mm: tile = tamanho real de um ladrilho."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt, b = m.node_tree, m.node_tree.nodes["Principled BSDF"]
    sep, comb, mp = nt.nodes.new("ShaderNodeSeparateXYZ"), nt.nodes.new("ShaderNodeCombineXYZ"), nt.nodes.new("ShaderNodeMapping")
    nt.links.new(nt.nodes.new("ShaderNodeNewGeometry").outputs["Position"], sep.inputs[0])
    nt.links.new(sep.outputs[axes[0]], comb.inputs["X"])
    nt.links.new(sep.outputs[axes[1]], comb.inputs["Y"])
    mp.inputs["Scale"].default_value = (1 / tile,) * 3
    nt.links.new(comb.outputs[0], mp.inputs["Vector"])

    def image(fname, color):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(str(folder / fname))
        if not color:
            n.image.colorspace_settings.name = "Non-Color"
        nt.links.new(mp.outputs[0], n.inputs["Vector"])
        return n
    nt.links.new(image("diff.jpg", True).outputs["Color"], b.inputs["Base Color"])
    nt.links.new(image("rough.jpg", False).outputs["Color"], b.inputs["Roughness"])
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(image("nor.jpg", False).outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
    return m


def furniture(asset, x, y, rot_deg, z=0.0):
    """Importa um modelo glTF do Poly Haven (metros) para a cena em mm, com o centro em (x, y) e a base em z. Devolve os objetos criados."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(PH / asset / f"{asset}.gltf"))
    new = [o for o in bpy.data.objects if o not in before]
    grp = bpy.data.objects.new(asset, None)
    bpy.context.collection.objects.link(grp)
    for o in new:
        if o.parent is None:
            o.parent = grp
    grp.scale = (1000, 1000, 1000)
    grp.rotation_euler.z = math.radians(rot_deg)
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in new if o.type == "MESH" for c in o.bound_box]
    lo_, hi_ = Vector((min(p[i] for p in pts) for i in range(3))), Vector((max(p[i] for p in pts) for i in range(3)))
    grp.location += Vector((x - (lo_.x + hi_.x) / 2, y - (lo_.y + hi_.y) / 2, z - lo_.z))
    bpy.context.view_layer.update()
    return new + [grp], hi_.z - lo_.z + z


def solid(name, color, rough=0.5, metal=0.0):
    m, b = make_mat(name, rough, Base_Color=(*color, 1))
    b.inputs["Metallic"].default_value = metal
    return m


def prim(kind, loc, scale, mat, rot=(0, 0, 0), name="prop", **kw):
    getattr(bpy.ops.mesh, f"primitive_{kind}_add")(location=loc, rotation=rot, **kw)
    o = bpy.context.object
    o.name, o.scale = name, scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)  # o chanfro (modifier) trabalha em medidas reais, não na caixa unitária
    o.data.materials.append(mat)
    return o


def make_prop(kind, lo_, hi_):
    """Objeto que a peça segura, feito de primitivas (o Poly Haven não tem chaves nem roteador). lo_/hi_ = caixa da peça já na parede. 'chaves': argola e chaves
    penduradas na frente da peça; 'roteador': aparelho em pé, apoiado na peça. Posição por heurística: confira a imagem."""
    cx, front, top, bottom = (lo_.x + hi_.x) / 2, lo_.y, hi_.z, lo_.z
    out = []
    if kind == "chaves":
        metal = solid("chave", (0.78, 0.74, 0.62), 0.28, 1.0)
        fob = solid("controle", (0.03, 0.03, 0.035), 0.35)
        ay, az = front - 7, top - 4  # ponto de onde a argola pende
        out.append(prim("torus", (cx, ay, az - 10), (1, 1, 1), metal, rot=(math.radians(90), 0, 0), name="argola", major_radius=10, minor_radius=1.1))
        for k, (dx, ln, ang) in enumerate(((-9, 36, 6), (1, 40, -3), (10, 32, -8))):
            a = math.radians(ang)
            y0 = ay + (k - 1) * 2.4
            hx, hz = cx + dx + math.sin(a) * 6, az - 21 - math.cos(a) * 6  # a cabeça (argola pequena) da chave
            out.append(prim("torus", (hx, y0, hz), (1, 1, 1), metal, rot=(math.radians(90), 0, 0), name="cabeca-chave", major_radius=5.2, minor_radius=1.7))
            bx, bz = hx - math.sin(a) * (ln / 2 + 6.5), hz - math.cos(a) * (ln / 2 + 6.5)
            out.append(prim("cube", (bx, y0, bz), (2.6, 0.8, ln / 2), metal, rot=(0, math.radians(-ang), 0), name="lamina-chave", size=2))
            for tooth in range(4):  # dentes da chave
                tz = bz - ln / 2 + 3 + tooth * 7
                out.append(prim("cube", (bx + 2.6 + (tooth % 2) * 0.8, y0, tz), (1.0, 0.8, 1.6), metal, name="lamina-chave", size=2))
        out.append(prim("cube", (cx + 16, ay + 4, az - 40), (22, 7, 36), fob, rot=(0, math.radians(-10), 0), name="controle", size=1))
        out[-1].modifiers.new("chanfro", "BEVEL").width = 2.5
    elif kind == "roteador":
        body = solid("roteador", (0.025, 0.025, 0.03), 0.45)
        w, d, h = 175, 38, 215
        out.append(prim("cube", (cx, front - d / 2 - 2, bottom + h / 2 + 10), (w / 2, d / 2, h / 2), body, name="roteador", size=2))
        out[-1].modifiers.new("chanfro", "BEVEL").width = 3
        led = solid("led", (0.05, 0.9, 0.2), 0.3)
        out.append(prim("cube", (cx - w / 2 + 14, front - d - 2.4, bottom + h - 22), (5, 1, 5), led, name="led", size=1))
    return out


def room_scene():
    """Parede e piso com texturas reais, sofá, mesa lateral e planta em escala real, HDRI de ambiente. Devolve o ponto que a câmera mira (a peça)."""
    wall = tex_material("sala-parede", PH / "plastered_wall_04", 3200, ("X", "Z"))
    floor = tex_material("sala-piso", PH / "laminate_floor_02", 1700, ("X", "Y"))
    ctx.append(plane((0, 0.5, 2500), (math.radians(90), 0, 0), (24000, 5000), wall, "parede-sala"))  # a câmera nunca vê a borda: parede, piso e teto passam do quadro
    ctx.append(plane((0, -9000, 0), (0, 0, 0), (24000, 18000), floor, "piso-sala"))
    sofa, sofa_top = furniture("Sofa_01", 300, -520, 0)
    plant, _ = furniture("potted_plant_01", 2150, -400, 0)
    ctx.extend(sofa + plant)
    if ctx_kind == "mesa":  # a peça sobre a mesa lateral, à frente do sofá
        tbl, top = furniture("side_table_01", -150, -900, 0)
        ctx.extend(tbl)
        obj_ctx.location = (-150, -900, top)
        bpy.context.view_layer.update()
        lo2, hi2 = bounds(obj_ctx)
        obj_ctx.location += Vector((-150 - (lo2.x + hi2.x) / 2, -900 - (lo2.y + hi2.y) / 2, top - lo2.z))
    else:
        tbl, _ = furniture("side_table_01", -1550, -300, 0)
        ctx.extend(tbl)
        up_ax = max((i for i in range(3) if i != back_ax), key=lambda i: dims0[i])
        up = Vector((1 if i == up_ax else 0) for i in range(3))
        obj_ctx.rotation_mode = "QUATERNION"
        obj_ctx.rotation_quaternion = Matrix((back.cross(up), back, up)).to_quaternion()
        obj_ctx.location = (0, 0, 0)
        bpy.context.view_layer.update()
        clo, chi = bounds(obj_ctx)
        obj_ctx.location = Vector((-(clo.x + chi.x) / 2, -chi.y, 1250 - (clo.z + chi.z) / 2))  # costas na parede, centro a 1,25 m do piso
    bpy.context.view_layer.update()
    clo, chi = bounds(obj_ctx)
    if cfg.get("objeto"):
        ctx.extend(make_prop(cfg["objeto"], clo, chi))
    nt = world_ctx.node_tree
    nt.nodes.clear()
    env, bg, out, tc, mp = (nt.nodes.new(t) for t in ("ShaderNodeTexEnvironment", "ShaderNodeBackground", "ShaderNodeOutputWorld", "ShaderNodeTexCoord", "ShaderNodeMapping"))
    env.image = bpy.data.images.load(str(next((PH / "brown_photostudio_05").glob("*.hdr"))))
    mp.inputs["Rotation"].default_value[2] = math.radians(cfg.get("hdri_rot", 200))
    bg.inputs["Strength"].default_value = 1.6
    nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    nt.links.new(mp.outputs[0], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    return (clo + chi) / 2
wall_m, wall_b = make_mat("parede", 0.95)
procedural(wall_m, wall_b, 400, [(0.55, 0.50, 0.44), (0.64, 0.59, 0.52)], kind="NOISE", bump=0.05)
if PH:
    target = room_scene()
elif ctx_kind == "parede":
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
sun.data.energy = ({"soft": 3.0, "normal": 4.5, "strong": 6.5} if PH else {"soft": 1.0, "normal": 1.5, "strong": 2.2})[cfg["light"]]  # na sala o sol da janela faz a sombra de contato
sun.data.angle = math.radians(6 if PH else 2.5)
sun.data.color = (1.0, 0.88, 0.72) if PH else (1.0, 0.94, 0.84)
sun.rotation_euler = sun_dir.to_track_quat("-Z", "Y").to_euler()
ctx.append(sun)
q = sun_dir.to_track_quat("-Z", "Y")
bars = [  # (x, y, largura, altura) no plano da janela, em tamanhos da peça: moldura com cruz
    (-20, 0, 12, 60), (20, 0, 12, 60), (0, 16, 60, 12), (0, -16, 60, 12), (-1.6, 0, 0.5, 20), (1.4, 0, 0.5, 20), (0, 0.6, 20, 0.5)]
for ox, oy, w, h in ([] if PH else bars):  # na sala a janela é o HDRI; o caixilho de sombra é só do cenário simples
    bpy.ops.mesh.primitive_cube_add(size=1)
    b = bpy.context.object
    b.location = target - sun_dir * size * 5 + q @ Vector((ox * size - 0.6 * size, oy * size + 0.3 * size, 0))
    b.rotation_euler = q.to_euler()
    b.scale = (w * size, h * size, 0.05 * size)
    b.visible_camera = False  # só projeta sombra, a câmera não vê a "janela"
    ctx.append(b)

if PH:
    plo, phi = bounds(obj_ctx)
    part_span = max(phi - plo)
    props = [o for o in ctx if o.type == "MESH" and o.name.split(".")[0] in ("argola", "cabeca-chave", "lamina-chave", "controle", "roteador", "led")]
    pts = [o.matrix_world @ Vector(c) for o in [obj_ctx] + props for c in o.bound_box]
    framed_span = max(max(p[k] for p in pts) - min(p[k] for p in pts) for k in range(3))
scene = bpy.context.scene
scene.render.engine = "CYCLES" if engine == "CYCLES" else "BLENDER_EEVEE_NEXT"
if engine == "CYCLES":
    scene.cycles.samples = cfg["samples_cycles"]
    scene.cycles.device = "CPU"
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
else:
    scene.eevee.taa_render_samples = cfg["samples_eevee"]
scene.render.resolution_x, scene.render.resolution_y = cfg.get("res") or (cfg["size"], cfg["size"])  # "res" = [largura, altura] dos quadros do vídeo
scene.render.image_settings.file_format = "JPEG"
scene.render.image_settings.quality = 92
scene.view_settings.view_transform = "Standard"

bpy.ops.object.camera_add()
cam = bpy.context.object
scene.camera = cam
cam.data.lens = 50
cam.data.clip_start, cam.data.clip_end = 1, 100000  # a cena é em mm: o padrão (100) cortaria a sala
for i, (name, az, el, zoom, *rest) in enumerate(cfg["views"], 1):
    t = rest[0] if rest else None  # vídeo: 0 = câmera aberta, 1 = de perto; a posição é contínua entre os quadros
    in_use = name.startswith("uso")
    for o in studio:
        o.hide_render = in_use
    obj.hide_render = in_use
    for o in ctx:
        o.hide_render = not in_use
    scene.world = world_ctx if in_use else world_studio
    scene.view_settings.view_transform = "AgX" if in_use and PH else "Standard"  # o estúdio fica em Standard (fundo branco puro); a sala em AgX, com mais gama nas luzes
    if in_use and cfg.get("still_cycles", True) and engine != "CYCLES":  # as fotos "em uso" saem em Cycles com denoiser; o estúdio é rápido no EEVEE
        scene.render.engine = "CYCLES"
        scene.cycles.samples = cfg["samples_cycles"]
        scene.cycles.device = "CPU"
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
    elif engine != "CYCLES":
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    focus = target if in_use else center
    a, e = math.radians(az + (-90 if in_use else cfg["turn"])), math.radians(el)
    if PH and in_use:
        # a peça ocupa uma fração da altura do quadro (perto 40 %, uso 30 %, médio 20 %, aberto 8 %); a distância sai da lente: d = tamanho * lente / (sensor * fração)
        frac, fst, lens = {"uso": (0.30, 2.5, 50), "uso_perto": (0.40, 1.8, 50), "uso_medio": (0.20, 3.2, 50), "uso_aberto": (0.08, 5.0, 28)}[name]
        if t is not None:  # vídeo: da cena (14 %) até a peça (38 %), a lente fecha junto
            frac, fst, lens = 0.14 + 0.24 * t, 4.0 - 2.2 * t, 35 + 15 * t
        span = framed_span if name == "uso" or t is not None else part_span  # com o objeto na cena, o enquadramento inclui o objeto
        dist = span * lens / (36 * frac)
        if t is None:  # peça pequena: o médio e o aberto ainda mostram o ambiente (a peça fica menor que a fração pedida)
            dist = max(dist, {"uso_medio": 900, "uso_aberto": 2700}.get(name, 0))
        cam.data.lens, cam.data.dof.aperture_fstop = lens, fst
    else:
        dist = size * cfg["dist"] * zoom
        cam.data.lens, cam.data.dof.aperture_fstop = 50, 2.8
    cam.location = focus + Vector((dist * math.cos(e) * math.cos(a), dist * math.cos(e) * math.sin(a), dist * math.sin(e)))
    aim(cam, focus)
    if PH and in_use:  # regra dos terços: a peça fica no terço esquerdo e um pouco abaixo do centro
        right = cam.matrix_world.to_quaternion() @ Vector((1, 0, 0))
        up_ = cam.matrix_world.to_quaternion() @ Vector((0, 1, 0))
        frame_h = dist * 36 / cam.data.lens
        aim(cam, focus + right * frame_h / 6 - up_ * frame_h / 14)
    cam.data.dof.use_dof = in_use  # fundo desfocado dá a cara de foto de ambiente
    cam.data.dof.focus_distance = (cam.location - focus).length
    scene.render.filepath = f"{outdir}/render_{i}.jpg"
    bpy.ops.render.render(write_still=True)
