"""Roda DENTRO do Blender: blender -b -P blender_scene.py -- <modelo.stl> <pasta de saída> <config.json> <EEVEE|CYCLES>
Gera uma imagem quadrada por vista pedida na config (render.RENDER_DEFAULT descreve os campos).
Vistas de estúdio: peça sobre fundo liso (a foto principal do ML). Vistas "uso*": a peça instalada num cenário
(parede ou mesa) com luz de janela e profundidade de campo, para mostrar o produto pronto no ambiente."""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blender_blend as bb  # noqa: E402  (a sala editável: cada móvel vira um objeto só)

model, outdir, cfgfile, engine = sys.argv[sys.argv.index("--") + 1:][:4]
cfg = json.load(open(cfgfile, encoding="utf-8"))
color = cfg["color"]
ctx_kind = cfg["contexto"]  # "parede" ou "mesa" (render.py já resolveu o "auto")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=model)
obj = bpy.context.selected_objects[0]
obj.name = "modelo-original"  # o nome do arquivo (ex.: "peca") ficaria com o do objeto "peca" da sala editável
bpy.context.view_layer.objects.active = obj
bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))  # cantos vivos ficam vivos, curvas ficam lisas


def bounds(o):
    corners = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return Vector((min(c[i] for c in corners) for i in range(3))), Vector((max(c[i] for c in corners) for i in range(3)))


def back_axis(o):
    """Face de trás da peça: a das 6 direções com mais área plana encostada no extremo da caixa (a placa que vai na parede). Devolve (direção local, eixo, medidas)."""
    lo, hi = bounds(o)
    dims = hi - lo
    area = {}
    for p in o.data.polygons:
        for ax in range(3):
            for s in (1, -1):
                edge = hi[ax] if s == 1 else lo[ax]
                if p.normal[ax] * s > 0.95 and abs(p.center[ax] - edge) < 0.04 * dims[ax] + 0.5:
                    area[(ax, s)] = area.get((ax, s), 0.0) + p.area
    ax, s = max(area, key=area.get) if area else (min(range(3), key=lambda i: dims[i]), 1)
    return Vector((s if i == ax else 0) for i in range(3)), ax, dims


def up_direction(o, back_ax):
    """Direção local que vira 'cima' na parede: a que tem faces de apoio (prateleira, bandeja) abaixo da massa da peça. Sem faces de apoio, o maior lado restante."""
    polys = list(o.data.polygons)
    total = sum(p.area for p in polys) or 1.0
    best, best_score = None, 0.0
    for ax in (a for a in range(3) if a != back_ax):
        for sgn in (1, -1):
            d = Vector((sgn if i == ax else 0) for i in range(3))
            centroid = sum(p.area * p.center.dot(d) for p in polys) / total
            score = sum(p.area * (centroid - p.center.dot(d)) for p in polys if p.normal.dot(d) > 0.95)
            if score > best_score:
                best, best_score = d, score
    if best is None:
        lo, hi = bounds(o)
        ax = max((a for a in range(3) if a != back_ax), key=lambda a: (hi - lo)[a])
        best = Vector((1 if i == ax else 0) for i in range(3))
    return best


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


def tex_material(name, folder, tile, axes, tint=None, wash=0.0):
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
    diff = image("diff.jpg", True).outputs["Color"]
    if wash:  # caiação: mistura a textura com cal, o relevo e a junta continuam
        lime = nt.nodes.new("ShaderNodeMix")
        lime.data_type = "RGBA"
        lime.inputs["Factor"].default_value = wash
        lime.inputs["B"].default_value = (0.86, 0.84, 0.80, 1)
        nt.links.new(diff, lime.inputs["A"])
        diff = lime.outputs["Result"]
    if tint:  # tom da pintura/superfície multiplicado sobre a textura (a textura continua mandando no relevo e na variação)
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        mix.inputs["B"].default_value = (*tint, 1)
        nt.links.new(diff, mix.inputs["A"])
        diff = mix.outputs["Result"]
    nt.links.new(diff, b.inputs["Base Color"])
    nt.links.new(image("rough.jpg", False).outputs["Color"], b.inputs["Roughness"])
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(image("nor.jpg", False).outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
    return m


def furniture(asset, x, y, rot_deg, z=0.0, tipo="movel"):
    """Importa um modelo glTF do Poly Haven (metros) para a cena em mm, como um objeto só, com o centro em (x, y) e a base em z. Devolve os objetos criados."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(PH / asset / f"{asset}.gltf"))
    o, altura = bb.juntar([n for n in bpy.data.objects if n not in before], asset, 1000, x, y, z, rot_deg, tipo, f"polyhaven:{asset}")
    return [o], altura + z


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


def hero_objs():
    return [o for o in HERO]


def modem_material():
    m, b = make_mat("modem", 0.42, Base_Color=(0.30, 0.31, 0.33, 1))  # cinza médio: a peça preta do suporte é que chama o olho
    nt = m.node_tree
    tc, chk, bm = nt.nodes.new("ShaderNodeTexCoord"), nt.nodes.new("ShaderNodeTexChecker"), nt.nodes.new("ShaderNodeBump")
    chk.inputs["Scale"].default_value = 0.28  # grade de ventilação: um quadrado a cada ~3,5 mm
    bm.inputs["Strength"].default_value = 0.7
    nt.links.new(tc.outputs["Object"], chk.inputs["Vector"])
    nt.links.new(chk.outputs["Fac"], bm.inputs["Height"])
    nt.links.new(bm.outputs["Normal"], b.inputs["Normal"])
    return m


def make_modem(cx, bottom, w=190, d=42, h=205):
    """Aparelho de fibra em pé (bloco preto com grade de ventilação e LED), encostado na parede em y = 0. Medidas de um modem comum (o Poly Haven não tem roteador)."""
    out = [prim("cube", (cx, -d / 2 - 1, bottom + h / 2), (w / 2, d / 2, h / 2), modem_material(), name="modem", size=2)]
    out[-1].modifiers.new("chanfro", "BEVEL").width = 3.5
    led = solid("led", (0.05, 0.9, 0.25), 0.3)
    led.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = (0.1, 1, 0.3, 1)
    led.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 3
    out.append(prim("cube", (cx - w / 2 + 16, -d - 1.6, bottom + h - 24), (5, 1, 5), led, name="led", size=1))
    green = solid("porta", (0.12, 0.45, 0.14), 0.4)
    for k in range(4):  # as portas de rede na lateral, como no aparelho do anúncio
        out.append(prim("cube", (cx - w / 2 - 0.6, -d / 2 - 1, bottom + h * 0.46 - k * 18), (1.2, 7, 6), solid("porta-rede", (0.9, 0.7, 0.1) if k else (0.12, 0.45, 0.14), 0.4), name="led", size=1))
    return out


def top_face(o):
    """Maior face voltada para cima da peça já montada (a prateleira): centro no mundo. Onde se apoiam objetos."""
    m3 = o.matrix_world.to_3x3()
    best = max(((p.area, o.matrix_world @ p.center) for p in o.data.polygons if (m3 @ p.normal).z > 0.95), key=lambda t: t[0], default=None)
    return best[1] if best else None


def make_prop(kind, lo_, hi_, shelf):
    """Objetos de vida real que acompanham a peça, de primitivas (o Poly Haven não tem chaves nem roteador). 'chaves': chaveiro pendurado e, se há prateleira,
    um estojo de fone e uma chave de carro sobre ela. Posição por heurística: confira a imagem."""
    cx, front, top = lo_.x + 0.64 * (hi_.x - lo_.x), lo_.y, hi_.z
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
                out.append(prim("cube", (bx + 2.6 + (tooth % 2) * 0.8, y0, bz - ln / 2 + 3 + tooth * 7), (1.0, 0.8, 1.6), metal, name="lamina-chave", size=2))
        out.append(prim("cube", (cx + 16, ay + 4, az - 40), (22, 7, 36), fob, rot=(0, math.radians(-10), 0), name="controle", size=1))
        out[-1].modifiers.new("chanfro", "BEVEL").width = 2.5
        if shelf is not None:  # estojo de fone e chave de carro na bandeja, como no anúncio
            case = solid("estojo", (0.015, 0.015, 0.018), 0.25)
            bx0 = lo_.x + 0.22 * (hi_.x - lo_.x)
            out.append(prim("cube", (bx0, shelf.y - 4, shelf.z + 11), (31, 14, 11), case, rot=(0, 0, math.radians(8)), name="estojo", size=2))
            out[-1].modifiers.new("chanfro", "BEVEL").width = 6
            out.append(prim("cube", (bx0 + 62, shelf.y + 2, shelf.z + 5), (50, 22, 7), fob, rot=(0, 0, math.radians(-14)), name="controle", size=1))
            out[-1].modifiers.new("chanfro", "BEVEL").width = 3
    return out


def trim(door_x):
    """Rodapé, cantoneira de teto e vão de porta com batente e folha (pintura branca acetinada): as marcas de uma casa de verdade nas vistas abertas."""
    white = solid("pintura-branca", (0.88, 0.87, 0.84), 0.38)
    leaf = solid("porta", (0.82, 0.81, 0.77), 0.4)
    ctx.append(prim("cube", (0, -7.5, 55), (12000, 7.5, 55), white, name="rodape", size=2))
    ctx.append(prim("cube", (0, -45, 2640), (12000, 45, 55), white, name="cantoneira", size=2))
    for dx in (-490, 490):
        ctx.append(prim("cube", (door_x + dx, -12, 1060), (38, 12, 1060), white, name="batente", size=2))
    ctx.append(prim("cube", (door_x, -12, 2135), (528, 12, 38), white, name="batente", size=2))
    ctx.append(prim("cube", (door_x, -1, 1040), (452, 1, 1040), solid("vao-escuro", (0.03, 0.03, 0.03), 0.9), name="vao", size=2))  # a fresta entre a folha e o batente fica escura
    ctx.append(prim("cube", (door_x, -14, 1030), (436, 14, 1030), leaf, name="folha", size=2))
    for dx in (-215, 215):  # almofadas: duas em cima e duas embaixo, como numa porta de madeira pintada
        for z, h in ((1560, 330), (560, 400)):
            ctx.append(prim("cube", (door_x + dx, -29, z), (170, 3, h), white, name="almofada", size=2))
    ctx.append(prim("cube", (door_x + 360, -31, 1000), (22, 3, 60), solid("macaneta", (0.7, 0.7, 0.72), 0.25, 1.0), name="macaneta", size=2))  # espelho da maçaneta
    ctx.append(prim("cylinder", (door_x + 360, -52, 1000), (1, 1, 1), solid("macaneta", (0.7, 0.7, 0.72), 0.25, 1.0), rot=(math.radians(90), 0, 0), name="macaneta", radius=13, depth=44))


# luz do dia: (força do HDRI, cor da janela, altura da janela, fator da janela)
LUZ = {"dia": (1.0, (1.0, 0.82, 0.62), 1700, 1.0), "tarde": (0.65, (1.0, 0.52, 0.26), 750, 0.5), "noite": (0.03, (0.45, 0.58, 1.0), 1700, 0.06)}[(cfg.get("cena") or {}).get("luz", "dia")]


def reference_object(kind, x, base_z, y):
    """Objeto de referência de tamanho conhecido, ao lado da peça, para a escala ficar óbvia. Medidas reais em mm."""
    if kind == "moeda":
        return [prim("cylinder", (x + 13.5, y, base_z + 1), (1, 1, 1), solid("moeda", (0.72, 0.58, 0.28), 0.3, 1.0), name="moeda", radius=13.5, depth=2)]
    if kind == "caneca":
        ceramica = solid("caneca", (0.9, 0.9, 0.88), 0.25)
        return [prim("cylinder", (x + 40, y, base_z + 47.5), (1, 1, 1), ceramica, name="caneca", radius=40, depth=95),
                prim("torus", (x + 82, y, base_z + 47), (1, 1, 1), ceramica, rot=(math.radians(90), 0, 0), name="caneca", major_radius=20, minor_radius=5)]
    if kind == "celular":
        tela = prim("cube", (x + 36, y, base_z + 4), (36, 74, 4), solid("celular", (0.02, 0.02, 0.025), 0.2), name="celular", size=2)
        tela.modifiers.new("chanfro", "BEVEL").width = 5
        return [tela]
    return []


def pla(o):
    """Material de PLA mate: rugosidade média, linhas de camada bem fracas (ondas de 0,3 mm no eixo Z da peça), granulação mínima no relevo e na cor."""
    m = bpy.data.materials.new("PLA")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    rgb = [(int(cfg["color"][i:i + 2], 16) / 255) ** 2.2 for i in (1, 3, 5)]
    b.inputs["Roughness"].default_value = 0.52
    b.inputs["Specular IOR Level"].default_value = 0.35
    tc = nt.nodes.new("ShaderNodeTexCoord")
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type, wave.bands_direction, wave.wave_profile = "BANDS", "Z", "SAW"
    wave.inputs["Scale"].default_value, wave.inputs["Distortion"].default_value, wave.inputs["Detail"].default_value = 1 / 0.3, 0.5, 1.0
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value, noise.inputs["Detail"].default_value = 90, 6
    mix = nt.nodes.new("ShaderNodeMath")
    mix.operation, mix.inputs[1].default_value = "ADD", 0.0
    nt.links.new(tc.outputs["Object"], wave.inputs["Vector"])
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    w2 = nt.nodes.new("ShaderNodeMath")
    w2.operation, w2.inputs[1].default_value = "MULTIPLY", 0.7
    n2 = nt.nodes.new("ShaderNodeMath")
    n2.operation, n2.inputs[1].default_value = "MULTIPLY", 0.3
    nt.links.new(wave.outputs["Fac"], w2.inputs[0])
    nt.links.new(noise.outputs["Fac"], n2.inputs[0])
    nt.links.new(w2.outputs[0], mix.inputs[0])
    nt.links.new(n2.outputs[0], mix.inputs[1])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value, bump.inputs["Distance"].default_value = 0.06, 0.1
    nt.links.new(mix.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    cmix = nt.nodes.new("ShaderNodeMixRGB")
    cmix.blend_type = "MULTIPLY"
    cmix.inputs["Fac"].default_value = 0.08
    cmix.inputs["Color1"].default_value = (*rgb, 1)
    nt.links.new(noise.outputs["Color"], cmix.inputs["Color2"])
    nt.links.new(cmix.outputs["Color"], b.inputs["Base Color"])
    o.data = o.data.copy()
    o.data.materials.clear()
    o.data.materials.append(m)


def place_custom(C, sup_top, sy):
    """Sala virtual: coloca a peça (do produto ou enviada) onde a pessoa escolheu, na escala e no giro pedidos. Devolve (peça, objetos de referência)."""
    k = C["escala_pct"] / 100
    pla(obj_ctx)
    obj_ctx.scale = (k, k, k)
    mode, giro = C["colocacao"], math.radians(C["giro"])
    if mode == "parede":
        up = up_direction(obj, back_ax)
        obj_ctx.rotation_mode = "QUATERNION"
        obj_ctx.rotation_quaternion = Quaternion((0, 1, 0), giro) @ Matrix((back.cross(up), back, up)).to_quaternion()
        obj_ctx.location = (0, 0, 0)
        bpy.context.view_layer.update()
        clo, chi = bounds(obj_ctx)
        obj_ctx.location = Vector((-(clo.x + chi.x) / 2, -chi.y, max(1250, sup_top + 560) - (clo.z + chi.z) / 2))
        bpy.context.view_layer.update()
        return [], []
    obj_ctx.rotation_mode = "XYZ"
    obj_ctx.rotation_euler = (0, 0, giro)  # como sai da impressora, só girada em volta do eixo vertical
    obj_ctx.location = (0, 0, 0)
    bpy.context.view_layer.update()
    lo_, hi_ = bounds(obj_ctx)
    extra = []
    if mode == "mesa":
        x, y, z = 0, sy, sup_top
    elif mode == "prateleira":  # tábua flutuante na parede, a 1,3 m do piso
        board = prim("cube", (0, -120, 1288), (460, 120, 12), solid("tabua", (0.55, 0.38, 0.22), 0.5), name="tabua", size=2)
        board.modifiers.new("chanfro", "BEVEL").width = 4
        extra.append(board)
        x, y, z = 0, -120, 1300
    else:  # chão
        x, y, z = 0, -750, 0
    obj_ctx.location = Vector((x - (lo_.x + hi_.x) / 2, y - (lo_.y + hi_.y) / 2, z - lo_.z))
    bpy.context.view_layer.update()
    lo_, hi_ = bounds(obj_ctx)
    refs = reference_object(C["referencia"], hi_.x + 40, z, y)
    return extra, refs


def mapear_materiais(pasta_texturas, json_path, materiais):
    """Liga as texturas da pasta aos materiais importados (o FBX de Corona não traz os nós). Casa pelo nome: o material e a imagem com
    palavras em comum. Guarda o resultado em materiais.json ao lado da sala para reaproveitar. Material sem imagem fica com a cor do FBX."""
    import re
    arquivos = [f for f in Path(pasta_texturas).rglob("*") if f.suffix.lower() in (".jpg", ".png")] if pasta_texturas and Path(pasta_texturas).is_dir() else []
    if json_path.is_file():
        mapa = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        mapa = {}
        palavras = lambda t: set(re.findall(r"[a-z]{3,}", t.lower()))
        for m in materiais:
            pm = palavras(m.name)
            if not pm:
                continue
            pontos = {}
            for f in arquivos:
                n = f.name.lower()
                if "ao" in n.split("_") or "mask" in n or "opacity" in n or "logo" in n or "bump" in n:
                    continue
                k = len(pm & palavras(f.stem))
                if k:
                    papel = "nrm" if re.search(r"nrm|normal|_nor", n) else "gloss" if re.search(r"gloss|rough|refl", n) else "col"
                    if k > pontos.get(papel, (0, None))[0]:
                        pontos[papel] = (k, f)
            if "col" in pontos:
                mapa[m.name] = {papel: str(f) for papel, (k, f) in pontos.items()}
        json_path.write_text(json.dumps(mapa, ensure_ascii=False, indent=1), encoding="utf-8")
    for m in materiais:
        ent = mapa.get(m.name)
        if not ent or not m.use_nodes:
            continue
        nt = m.node_tree
        b = nt.nodes.get("Principled BSDF") or next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        if "col" in ent and Path(ent["col"]).is_file():
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = bpy.data.images.load(ent["col"], check_existing=True)
            nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        if "nrm" in ent and Path(ent["nrm"]).is_file():
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = bpy.data.images.load(ent["nrm"], check_existing=True)
            t.image.colorspace_settings.name = "Non-Color"
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nt.links.new(t.outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
        if "gloss" in ent and Path(ent["gloss"]).is_file():
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = bpy.data.images.load(ent["gloss"], check_existing=True)
            t.image.colorspace_settings.name = "Non-Color"
            inv = nt.nodes.new("ShaderNodeInvert")  # o brilho vira rugosidade
            nt.links.new(t.outputs["Color"], inv.inputs["Color"])
            nt.links.new(inv.outputs["Color"], b.inputs["Roughness"])
    return mapa


def imported_scene():
    """Sala 3D importada (GLB ou FBX de terceiros): vira o ambiente inteiro, em mm. Procura por raycast onde a peça cabe (chão, mesa, parede ou prateleira)
    com espaço livre para a câmera e move a SALA, não a peça, para o quadro padrão da cena (parede em y = 0 voltada para -y, piso em z = 0)."""
    global HERO
    S, C = cfg["sala"], cfg["cena"]
    before = set(bpy.data.objects)
    f = S["importada"]
    (bpy.ops.import_scene.fbx if f.lower().endswith(".fbx") else bpy.ops.import_scene.gltf)(filepath=f)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    lo, hi = bb.bounds(meshes)
    k = 1000 if max(hi - lo) < 200 else 10 if max(hi - lo) < 20000 else 1  # metros, centímetros ou milímetros
    roots = [o for o in new if o.parent is None]
    for r in roots:
        r.scale, r.location = r.scale * k, r.location * k
    bpy.context.view_layer.update()
    lo, hi = bb.bounds(meshes)
    print(f"[sala] importada: {len(meshes)} malhas, escala x{k}, tamanho {hi.x - lo.x:.0f} x {hi.y - lo.y:.0f} x {hi.z - lo.z:.0f} mm", flush=True)
    ctx.extend(new)
    mats = {sl.material for o in meshes for sl in o.material_slots if sl.material}
    pasta_f = Path(f).parent / "texturas" / "TEXTURES"
    if not pasta_f.is_dir():
        pasta_f = Path(f).parent / "texturas"
    mapear_materiais(pasta_f, Path(f).parent / "materiais.json", list(mats))
    for o in studio + [obj, obj_ctx]:
        o.hide_viewport = True  # a peça não entra na busca por raycast
    bpy.context.view_layer.update()
    dg = bpy.context.view_layer.depsgraph

    def cast(p, d, dist=6000):
        ok, loc, nor, *_ = bpy.context.scene.ray_cast(dg, Vector(p), Vector(d).normalized(), distance=dist)
        return (loc, nor) if ok else (None, None)
    step = max(250, math.sqrt((hi.x - lo.x) * (hi.y - lo.y) / 700))
    grid = [(lo.x + step * (i + 0.5), lo.y + step * (j + 0.5)) for i in range(int((hi.x - lo.x) / step)) for j in range(int((hi.y - lo.y) / step))]
    top = lo.z + 2000
    hits = []
    for x, y in grid:
        loc, nor = cast((x, y, top), (0, 0, -1), 4000)
        if loc is not None and nor.z > 0.9:
            hits.append((loc, nor))
    if not hits:
        raise ValueError("não achei piso na sala importada")
    zs = sorted(h[0].z for h in hits)
    floor_z = zs[int(len(zs) * 0.08)]
    print(f"[sala] piso em z={floor_z:.0f} mm; pé-direito até {hi.z - floor_z:.0f} mm; {len(hits)} pontos de apoio", flush=True)
    cx, cy = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2
    esp = max(size * C["escala_pct"] / 100, 60)
    need = min(3.97 * esp + 300, 3200)  # distância da câmera da cena (lente 50, peça em 35 % do quadro) mais folga
    cams = [(math.cos(math.radians(-124)), math.sin(math.radians(-124))), (0.0, -1.0)]  # direção da câmera 3/4 e da frontal no quadro padrão

    def free(p, psi):
        """Espaço livre de p até a câmera nas duas vistas, com a sala girada por psi (graus)."""
        c, s = math.cos(math.radians(-psi)), math.sin(math.radians(-psi))
        out = []
        for dx, dy in cams:
            d = (dx * c - dy * s, dx * s + dy * c, 0.15)
            loc, _ = cast(p, d, 3400)
            out.append(3400 if loc is None else (loc - Vector(p)).length)
        return min(out)

    def flat_down(x, y, z, tol=8):
        return all((lambda r: r[0] is not None and abs(r[0].z - z) < tol)(cast((x + dx, y + dy, z + 300), (0, 0, -1), 600)) for dx, dy in ((100, 0), (-100, 0), (0, 100), (0, -100)))
    modo = C["colocacao"]
    best = None  # (pontuação, ponto alvo, psi, parede)
    if modo in ("mesa", "chao"):
        alvo = (600, 950) if modo == "mesa" else (-30, 30)
        for loc, nor in hits:
            if not alvo[0] <= loc.z - floor_z <= alvo[1] or not flat_down(loc.x, loc.y, loc.z):
                continue
            if cast((loc.x, loc.y, loc.z + 15), (0, 0, 1), 700)[0] is not None and modo == "mesa":
                continue
            for psi in range(0, 360, 45):
                fr = free((loc.x, loc.y, loc.z + 200), psi)
                sc = min(fr, need) * 1000 - math.hypot(loc.x - cx, loc.y - cy)
                if best is None or sc > best[0]:
                    best = (sc, loc, psi, None)
    else:  # parede e prateleira: um trecho liso de parede com espaço na frente
        dirs = [(math.cos(math.radians(a)), math.sin(math.radians(a))) for a in range(0, 360, 45)]
        for loc, nor in hits:
            if abs(loc.z - floor_z) > 30:
                continue
            for dx, dy in dirs:
                w, wn = cast((loc.x, loc.y, floor_z + 1250), (dx, dy, 0), 5000)
                if w is None or abs(wn.z) > 0.25 or wn.x * dx + wn.y * dy > -0.8:
                    continue
                lat = (-dy, dx)
                ok = all((lambda r: r[0] is not None and abs((r[0] - w).dot(Vector((dx, dy, 0)))) < 20)(cast((loc.x + lat[0] * a, loc.y + lat[1] * a, floor_z + 1250 + b), (dx, dy, 0), 5000))
                         for a, b in ((250, 0), (-250, 0), (0, 250), (0, -250)))
                if not ok:
                    continue
                psi = -90 - math.degrees(math.atan2(wn.y, wn.x))
                fr = free((w.x + wn.x * 80, w.y + wn.y * 80, floor_z + 1250), psi)
                sc = min(fr, need) * 1000 - math.hypot(w.x - cx, w.y - cy)
                if best is None or sc > best[0]:
                    best = (sc, w, psi, True)
    if best is None:
        raise ValueError("não achei um lugar livre nessa sala para " + {"mesa": "pôr a peça sobre um móvel", "chao": "pôr a peça no chão", "parede": "fixar a peça na parede", "prateleira": "pôr a prateleira"}[modo])
    _, S0, psi, wall = best
    print(f"[sala] peça em ({S0.x:.0f}, {S0.y:.0f}, {S0.z - floor_z:.0f}) mm, giro da sala {psi:.0f} graus, modo {modo}", flush=True)
    y0 = 0 if wall else (-300 if modo == "mesa" else -750)
    M = Matrix.Translation((0, y0, 0)) @ Matrix.Rotation(math.radians(psi), 4, "Z") @ Matrix.Translation((-S0.x, -S0.y, -floor_z))
    for r in roots:
        r.matrix_world = M @ r.matrix_world
    for o in studio + [obj, obj_ctx]:
        o.hide_viewport = False
    bpy.context.view_layer.update()
    sup_top = (S0.z - floor_z) if modo == "mesa" else 0
    # a sala inteira passa de 20 milhões de vértices e derrubava o EEVEE: o que está longe do foco entra simplificado (o que aparece de perto fica quase inteiro)
    foco = Vector((0, y0, sup_top))
    for o in meshes:
        n = len(o.data.vertices)
        olo, ohi = bb.bounds([o])
        lim = 150000 if ((olo + ohi) / 2 - foco).length < 1200 else 30000
        if n > lim:
            md = o.modifiers.new("simplificar", "DECIMATE")
            md.ratio = lim / n
    obj_ctx.name, obj_ctx["m3d_tipo"], obj_ctx["m3d_fonte"] = "peca", "peca", "produto"
    extra, refs = place_custom(C, sup_top, y0)
    for o in refs:
        o["m3d_tipo"] = "referencia"
    for o in extra:
        o["m3d_tipo"] = "estrutura"
    ctx.extend(extra + refs)
    HERO = [obj_ctx] + refs
    nt = world_ctx.node_tree
    nt.nodes["Background"].inputs["Color"].default_value = (0.95, 0.93, 0.9, 1)
    nt.nodes["Background"].inputs["Strength"].default_value = 1.6 * LUZ[0]  # luz de ambiente: o interior fechado não recebe o céu
    pts = [o.matrix_world @ Vector(c) for o in HERO if o.type == "MESH" for c in o.bound_box]
    return (Vector((min(p[i] for p in pts) for i in range(3))) + Vector((max(p[i] for p in pts) for i in range(3)))) / 2


def room_scene():
    """Ambiente com materiais PBR do Poly Haven (parede, piso), móvel de apoio com objetos, rodapé, porta, HDRI de interior e luz de janela.
    Devolve o ponto que a câmera mira. A peça fica fixada na parede acima do móvel ou, para aparelhos, em pé sobre ele."""
    global HERO
    S = cfg["sala"]
    wall = tex_material("parede", PH / S["wall"][0], S["wall"][1], ("X", "Z"), S["wall"][2], S["wall"][3] if len(S["wall"]) > 3 else 0.0)
    floor = tex_material("piso", PH / S["floor"][0], S["floor"][1], ("X", "Y"), S["floor"][2])
    ctx.append(plane((0, 0.5, 2500), (math.radians(90), 0, 0), (24000, 5000), wall, "parede-sala"))  # parede e piso passam do quadro: a câmera nunca vê a borda
    ctx.append(plane((0, -9000, 0), (0, 0, 0), (24000, 18000), floor, "piso-sala"))
    trim(S["door_x"])
    sa, sx, sy, sr = S["support"]
    sup, sup_top = furniture(sa, sx, sy, sr)
    ctx.extend(sup)
    for asset, x, rot in S["items"]:  # objetos de vida real sobre o móvel, fora do foco
        o, _ = furniture(asset, x, sy, rot, z=sup_top, tipo="decor")
        ctx.extend(o)
    for asset, x, y, rot in S["extras"]:
        o, _ = furniture(asset, x, y, rot)
        ctx.extend(o)
    C = cfg.get("cena")
    if C:
        obj_ctx.name, obj_ctx["m3d_tipo"], obj_ctx["m3d_fonte"] = "peca", "peca", "produto"
        extra, refs = place_custom(C, sup_top, sy)
        for o in refs:
            o["m3d_tipo"] = "referencia"
        for o in extra + [w for w in ctx if w.name.endswith("-sala")]:
            o["m3d_tipo"] = "estrutura"
        ctx.extend(extra + refs)  # a tábua da prateleira só decora: o enquadramento mede a peça e o objeto de referência
        legs, props = [obj_ctx], refs
        clo, chi = bounds(obj_ctx)
        stand = False
    else:
        up = up_direction(obj, back_ax)
        rotq = Matrix((back.cross(up), back, up)).to_quaternion()
        obj_ctx.rotation_mode = "QUATERNION"
        obj_ctx.rotation_quaternion = rotq
        obj_ctx.location = (0, 0, 0)
        bpy.context.view_layer.update()
        clo, chi = bounds(obj_ctx)
        stand = cfg.get("montagem") == "sobre_movel"
        legs = [obj_ctx]
    if C:
        pass
    elif stand:  # aparelho em pé sobre o móvel, com a peça de cada lado (o par: a peça e a sua imagem espelhada)
        mw = 190
        lx = chi.x - clo.x
        obj_ctx.location = Vector((-(mw / 2 + 3 + lx / 2) - (clo.x + chi.x) / 2, -chi.y, sup_top - clo.z))
        other = obj_ctx.copy()
        other.scale.x = -1
        bpy.context.collection.objects.link(other)
        other.location = (0, 0, 0)
        ctx.append(other)
        bpy.context.view_layer.update()
        olo, ohi = bounds(other)
        other.location = Vector(((mw / 2 + 3 + lx / 2) - (olo.x + ohi.x) / 2, -chi.y, sup_top - clo.z))
        legs.append(other)
    else:
        obj_ctx.location = Vector((-(clo.x + chi.x) / 2, -chi.y, max(1250, sup_top + 560) - (clo.z + chi.z) / 2))  # costas na parede, acima do móvel
    bpy.context.view_layer.update()
    plo, phi = bounds(legs[0])
    for o in legs[1:]:
        a, b = bounds(o)
        plo, phi = Vector(min(x, y) for x, y in zip(plo, a)), Vector(max(x, y) for x, y in zip(phi, b))
    props = props if C else []
    if C:
        pass
    elif cfg.get("objeto") == "modem":
        props = make_modem(0, sup_top)
    elif cfg.get("objeto"):
        props = make_prop(cfg["objeto"], plo, phi, top_face(obj_ctx))
    ctx.extend(props)
    HERO = legs + props
    # HDRI de interior com janela
    hn, hrot, hstr = S["hdri"]
    nt = world_ctx.node_tree
    nt.nodes.clear()
    env, bgn, out, tc, mp = (nt.nodes.new(t) for t in ("ShaderNodeTexEnvironment", "ShaderNodeBackground", "ShaderNodeOutputWorld", "ShaderNodeTexCoord", "ShaderNodeMapping"))
    env.image = bpy.data.images.load(str(next((PH / hn).glob("*.hdr"))))
    mp.inputs["Rotation"].default_value[2] = math.radians(hrot)
    bgn.inputs["Strength"].default_value = hstr * LUZ[0]
    nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    nt.links.new(mp.outputs[0], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bgn.inputs["Color"])
    nt.links.new(bgn.outputs[0], out.inputs["Surface"])
    pts = [o.matrix_world @ Vector(c) for o in HERO if o.type == "MESH" for c in o.bound_box]
    return (Vector((min(p[i] for p in pts) for i in range(3))) + Vector((max(p[i] for p in pts) for i in range(3)))) / 2


HERO = []
wall_m, wall_b = make_mat("parede", 0.95)
procedural(wall_m, wall_b, 400, [(0.55, 0.50, 0.44), (0.64, 0.59, 0.52)], kind="NOISE", bump=0.05)
IMP = (cfg.get("sala") or {}).get("importada") if PH else None
if PH:
    target = imported_scene() if IMP else room_scene()
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

# luz: na sala, uma janela de área suave e quente (do lado esquerdo da câmera) mais um preenchimento fraco; no cenário simples, sol com caixilho de sombra
if IMP:  # sala importada: luz de área suave do lado da câmera (o interior é fechado e a câmera fica dentro dele) mais o ambiente do mundo
    k = {"soft": 0.6, "normal": 1.0, "strong": 1.5}[cfg["light"]] * LUZ[3]
    for loc, size_xy, watts, col in (((-900, -1500, 1500), (1500, 1500), 9000 * k, LUZ[1]), ((900, -1100, 1900), (1800, 1800), 3000 * k, (0.9, 0.93, 1.0))):
        bpy.ops.object.light_add(type="AREA", location=target + Vector(loc))
        lt = bpy.context.object
        lt.name = "Luz da janela" if loc[0] < 0 else "Luz de apoio"
        lt.data.shape, lt.data.size, lt.data.size_y = "RECTANGLE", size_xy[0], size_xy[1]
        lt.data.energy, lt.data.color = watts * 1000, col
        aim(lt, target)
        ctx.append(lt)
    if (cfg.get("cena") or {}).get("luz") == "noite":
        bpy.ops.object.light_add(type="POINT", location=target + Vector((-650, -750, 650)))
        lamp = bpy.context.object
        lamp.name = "Abajur"
        lamp.data.energy, lamp.data.color, lamp.data.shadow_soft_size = 3.2e5, (1.0, 0.72, 0.45), 60
        ctx.append(lamp)
elif PH:
    k = {"soft": 0.6, "normal": 1.0, "strong": 1.5}[cfg["light"]] * LUZ[3]
    for loc, size_xy, watts, col in (((-2400, -1500, LUZ[2]), (1500, 1900), 5200 * k, LUZ[1]), ((2200, -2600, 900), (2400, 1400), 480 * k * (0.25 if LUZ[3] < 1 else 1), (0.85, 0.9, 1.0))):
        bpy.ops.object.light_add(type="AREA", location=loc)
        lt = bpy.context.object
        lt.name = "Luz da janela" if loc[0] < 0 else "Luz de apoio"
        lt.data.shape, lt.data.size, lt.data.size_y = "RECTANGLE", size_xy[0], size_xy[1]
        lt.data.energy, lt.data.color = watts * 1000, col
        aim(lt, target)
        ctx.append(lt)
    if (cfg.get("cena") or {}).get("luz") == "noite":  # à noite a luz vem de um abajur ao lado da peça
        bpy.ops.object.light_add(type="POINT", location=target + Vector((-650, -750, 650)))
        lamp = bpy.context.object
        lamp.name = "Abajur"
        lamp.data.energy, lamp.data.color, lamp.data.shadow_soft_size = 3.2e5, (1.0, 0.72, 0.45), 60
        ctx.append(lamp)
else:
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
    bars = [(-20, 0, 12, 60), (20, 0, 12, 60), (0, 16, 60, 12), (0, -16, 60, 12), (-1.6, 0, 0.5, 20), (1.4, 0, 0.5, 20), (0, 0.6, 20, 0.5)]
    for ox, oy, w, h in bars:
        bpy.ops.mesh.primitive_cube_add(size=1)
        b = bpy.context.object
        b.location = target - sun_dir * size * 5 + q @ Vector((ox * size - 0.6 * size, oy * size + 0.3 * size, 0))
        b.rotation_euler = q.to_euler()
        b.scale = (w * size, h * size, 0.05 * size)
        b.visible_camera = False  # só projeta sombra, a câmera não vê a "janela"
        ctx.append(b)

if PH:
    def span_of(objs):
        pts = [o.matrix_world @ Vector(c) for o in objs if o.type == "MESH" for c in o.bound_box]
        return max(max(p[k] for p in pts) - min(p[k] for p in pts) for k in range(3))
    part_span = span_of(HERO[:2] if cfg.get("montagem") == "sobre_movel" else HERO[:1])
    leg_span = span_of(HERO[:1])  # a peça sozinha: no vídeo e no detalhe ela é a medida do quadro, nunca o aparelho
    framed_span = span_of(HERO)
    _p = [HERO[0].matrix_world @ Vector(c) for c in HERO[0].bound_box]
    FOCUS = (Vector((min(q[k] for q in _p) for k in range(3))) + Vector((max(q[k] for q in _p) for k in range(3)))) / 2
scene = bpy.context.scene
scene.render.engine = "CYCLES" if engine == "CYCLES" else "BLENDER_EEVEE_NEXT"
if engine == "CYCLES":
    scene.cycles.samples = cfg["samples_cycles"]
    scene.cycles.device = "CPU"
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    scene.cycles.time_limit = cfg.get("time_limit", 0)
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
    in_use = name.startswith(("uso", "cena"))
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
        scene.cycles.time_limit = cfg.get("time_limit", 0)
        scene.cycles.device = "CPU"
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
    elif engine != "CYCLES":
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    focus = (FOCUS if (cfg.get("montagem") == "sobre_movel" or cfg.get("cena")) else target) if (in_use and PH) else target if in_use else center
    a, e = math.radians(az + (-90 if in_use else cfg["turn"])), math.radians(el)
    if PH and in_use:
        # a peça ocupa uma fração da altura do quadro (perto 40 %, uso 30 %, médio 20 %, aberto 8 %); a distância sai da lente: d = tamanho * lente / (sensor * fração)
        frac, fst, lens = {"uso": (0.30, 2.5, 50), "uso_perto": (0.40, 1.8, 50), "uso_medio": (0.20, 3.2, 50), "uso_aberto": (0.08, 5.0, 28),
                           "cena": (0.35, 2.8, 50), "cena_frontal": (0.35, 2.8, 50), "cena_close": (0.70, 2.0, 60), "cena_orbital": (0.32, 2.8, 50)}[name]
        stand = cfg.get("montagem") == "sobre_movel"
        if t is not None and name != "cena_orbital":  # vídeo: da cena até a peça (que fica com 45 % da altura no fim), a lente fecha junto
            frac, fst, lens = (0.07 if stand else 0.14) + (0.38 if stand else 0.24) * t, 4.0 - 2.2 * t, 35 + 15 * t
        span = leg_span if (stand and (t is not None or name == "uso_perto")) else framed_span if name in ("uso", "cena", "cena_frontal", "cena_orbital") or t is not None else part_span  # com o objeto na cena, o enquadramento inclui o objeto
        if IMP:  # sala importada: a peça ocupa um pouco menos do quadro, para o cômodo aparecer em volta
            frac *= 0.6
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
        d_ = focus + right * frame_h / 6 - up_ * frame_h / 14 - cam.location  # verticais retas, como lente de arquitetura: a câmera olha na horizontal e o quadro sobe/desce pelo shift
        cam.rotation_euler.x = math.pi / 2
        cam.data.shift_y = d_.z / math.hypot(d_.x, d_.y) * cam.data.lens / 36
    else:
        cam.data.shift_y = 0
    cam.data.dof.use_dof = in_use  # fundo desfocado dá a cara de foto de ambiente
    cam.data.dof.focus_distance = (cam.location - focus).length
    if cfg.get("salvar"):  # sala editável: guarda a câmera no arquivo em vez de renderizar
        saved = cam.copy()
        saved.data = cam.data.copy()
        saved.name = f"cam-{name}"
        scene.collection.objects.link(saved)
        continue
    scene.render.filepath = f"{outdir}/render_{i}.jpg"
    bpy.ops.render.render(write_still=True)

if cfg.get("salvar"):  # sem o estúdio, a peça original e a câmera de trabalho; tudo visível; texturas e HDRI empacotados no arquivo
    for o in studio + [obj, cam]:
        bpy.data.objects.remove(o, do_unlink=True)
    luzes = bpy.data.collections.new("Luzes")  # as luzes ficam juntas, com nomes claros, para o painel Minerador e para quem for mexer nelas
    scene.collection.children.link(luzes)
    for o in ctx:
        o.hide_render = False
        if o.type == "LIGHT":
            for c in o.users_collection:
                c.objects.unlink(o)
            luzes.objects.link(o)
    scene.world = world_ctx
    scene.view_settings.view_transform = "AgX"
    for o in bpy.data.objects:  # a peça nasce selecionada, pronta para G, R e S
        o.select_set(False)
    bpy.context.view_layer.objects.active = bpy.data.objects["peca"]
    bpy.data.objects["peca"].select_set(True)
    scene.camera = bpy.data.objects["cam-cena"]
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=cfg["salvar"], compress=True)
