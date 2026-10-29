"""Roda DENTRO do Blender, sobre a sala.blend de um produto (a sala que o Leonardo edita no Blender com interface).
  blender -b sala.blend -P blender_blend.py -- adicionar <itens.json>               põe móveis e modelos na sala e salva
  blender -b sala.blend -P blender_blend.py -- exportar <layout.json>               escreve o layout (em mm) do que está na sala
  blender -b sala.blend -P blender_blend.py -- renderizar <pasta> <cfg.json> <EEVEE|CYCLES>   imagens ou quadros do vídeo com a câmera e a luz do arquivo
Também é importado por blender_scene.py: cada móvel entra na sala como UM objeto (fácil de selecionar e mover), com a origem na base."""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

TIPOS = ("movel", "peca", "referencia", "decor", "estrutura", "luz", "camera")


def bounds(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type == "MESH" for c in o.bound_box]
    return Vector((min(p[i] for p in pts) for i in range(3))), Vector((max(p[i] for p in pts) for i in range(3)))


def juntar(novos, nome, escala, x, y, z, giro_graus=0.0, tipo="movel", fonte=""):
    """Junta tudo o que o importador criou num único objeto em mm, com a origem no centro da base, em (x, y) e com a base em z.
    escala: 1000 para modelos em metros (glTF), 1 para STL (já em mm). Devolve (objeto, altura em mm)."""
    malhas = [o for o in novos if o.type == "MESH"]
    if not malhas:
        raise ValueError("o arquivo não tem nenhuma malha 3D")
    S = Vector((escala, escala, escala))
    for o in malhas:
        o.data = o.data.copy()  # dados próprios: a junção e a aplicação de escala não afetam outros objetos
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        o.scale = Vector(a * b for a, b in zip(o.scale, S))
        o.location = o.location * escala
    for o in novos:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in malhas:
        o.select_set(True)
    bpy.context.view_layer.objects.active = malhas[0]
    if len(malhas) > 1:
        bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.context.view_layer.update()
    lo, hi = bounds([o])
    bpy.context.scene.cursor.location = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    o.rotation_mode = "XYZ"
    o.rotation_euler = (0, 0, math.radians(giro_graus))
    o.location = (x, y, z)
    o.name = nome
    o["m3d_tipo"], o["m3d_fonte"] = tipo, fonte
    bpy.context.view_layer.update()
    return o, hi.z - lo.z


def importar(caminho):
    """Importa um arquivo (.glb, .gltf, .stl, .blend) e devolve (objetos novos, escala para mm)."""
    antes = set(bpy.data.objects)
    ext = Path(caminho).suffix.lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(caminho))
        escala = 1000
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=str(caminho))
        escala = 1
    elif ext == ".blend":
        with bpy.data.libraries.load(str(caminho)) as (de, para):
            para.objects = list(de.objects)
        for o in para.objects:
            if o is not None and o.type == "MESH":
                bpy.context.collection.objects.link(o)
        novos = [o for o in bpy.data.objects if o not in antes]
        lo, hi = bounds(novos) if any(o.type == "MESH" for o in novos) else (Vector(), Vector())
        return novos, (1000 if max(hi - lo) < 20 else 1)  # arquivo em metros ou em mm
    else:
        raise ValueError(f"formato não suportado: {ext}")
    return [o for o in bpy.data.objects if o not in antes], escala


def cm(valor):
    return [round(v, 1) for v in valor]


def exportar(saida):
    objs = []
    for o in bpy.data.objects:
        tipo = o.get("m3d_tipo") or ("luz" if o.type == "LIGHT" else "camera" if o.type == "CAMERA" else None)
        if not tipo:
            continue
        objs.append(dict(id=o.name, tipo=tipo, fonte=o.get("m3d_fonte", ""), pos=cm(o.matrix_world.translation), rot=[round(math.degrees(o.matrix_world.to_euler().z), 1)],
                         escala=cm(o.matrix_world.to_scale())))
    Path(saida).write_text(json.dumps(dict(versao=1, unidade="mm", objetos=objs), ensure_ascii=False, indent=1), encoding="utf-8")


def adicionar(itens_json):
    """Cada item: {nome, caminho, tipo, fonte, x, y, z, giro}. A posição inicial é à frente da câmera principal, sobre o piso."""
    for it in json.loads(Path(itens_json).read_text(encoding="utf-8")):
        novos, escala = importar(it["caminho"])
        juntar(novos, it["nome"], escala, it.get("x", 0), it.get("y", -900), it.get("z", 0), it.get("giro", 0), it.get("tipo", "movel"), it.get("fonte", ""))
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_mainfile(compress=True)


def aim(o, alvo):
    o.rotation_euler = (alvo - o.location).to_track_quat("-Z", "Y").to_euler()


def renderizar(pasta, cfg_json, motor):
    cfg = json.loads(Path(cfg_json).read_text(encoding="utf-8"))
    scene = bpy.context.scene
    scene.render.engine = "CYCLES" if motor == "CYCLES" else "BLENDER_EEVEE_NEXT"
    if motor == "CYCLES":
        scene.cycles.samples, scene.cycles.device, scene.cycles.use_denoising, scene.cycles.denoiser = cfg["samples_cycles"], "CPU", True, "OPENIMAGEDENOISE"
    else:
        scene.eevee.taa_render_samples = cfg["samples_eevee"]
    scene.render.resolution_x, scene.render.resolution_y = cfg["res"]
    scene.render.image_settings.file_format, scene.render.image_settings.quality = "JPEG", 92
    if cfg.get("orbita"):
        peca = bpy.data.objects.get("peca")
        if peca is None:
            raise ValueError("a sala não tem o objeto 'peca'")
        lo, hi = bounds([peca])
        centro = (lo + hi) / 2
        base = bpy.data.objects[cfg["cameras"][0]]
        rel = base.matrix_world.translation - centro
        raio, az0 = math.hypot(rel.x, rel.y), math.atan2(rel.y, rel.x)
        cam = base.copy()
        cam.data = base.data.copy()
        bpy.context.scene.collection.objects.link(cam)
        scene.camera = cam
        cam.data.shift_y = 0
        for i, (graus, elev, _t) in enumerate(cfg["orbita"], 1):
            a, e = az0 + math.radians(graus), math.radians(elev)
            cam.location = centro + Vector((raio * math.cos(a), raio * math.sin(a), raio * math.tan(e)))
            aim(cam, centro)
            cam.data.dof.focus_distance = (cam.location - centro).length
            scene.render.filepath = f"{pasta}/render_{i}.jpg"
            bpy.ops.render.render(write_still=True)
        return
    for i, nome in enumerate(cfg["cameras"], 1):
        scene.camera = bpy.data.objects[nome]
        scene.render.filepath = f"{pasta}/render_{i}.jpg"
        bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    modo, *args = sys.argv[sys.argv.index("--") + 1:]
    {"adicionar": adicionar, "exportar": exportar, "renderizar": renderizar}[modo](*args)
