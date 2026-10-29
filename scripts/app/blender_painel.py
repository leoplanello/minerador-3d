"""Roda DENTRO do Blender com janela, ao abrir a sala pelo app:
  blender sala.blend --python blender_painel.py -- <products/<id>/renders> <products/<id>/cena/previa.jpg>
Cria o painel "Minerador" na barra lateral (tecla N) com luz fácil (hora do dia, janela, temperatura de cor, HDRI, luz de apoio) e os botões
Prévia rápida e Render final, que salvam na pasta do produto. As luzes da sala ficam na coleção "Luzes"."""
import math
import sys
import time
from pathlib import Path

import bpy

PASTA_RENDERS, ARQ_PREVIA = (Path(p) for p in sys.argv[sys.argv.index("--") + 1:][:2])
HORAS = {  # hora do dia: (fator do HDRI/ambiente, fator da luz da janela, temperatura da janela em K, abajur aceso)
    "dia": (1.0, 1.0, 5200, False), "tarde": (0.65, 0.5, 3000, False), "noite": (0.05, 0.06, 7500, True)}


def kelvin_rgb(k):
    """Cor aproximada de um corpo negro (1000 a 12000 K), em RGB linear 0..1."""
    t = max(1000, min(12000, k)) / 100
    r = 255 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255 if t >= 66 else 0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    return tuple(((max(0, min(255, c)) / 255) ** 2.2) for c in (r, g, b))


def luz(nome):
    return bpy.data.objects.get(nome)


def base(o, chave, valor):
    """Valor original (guardado na primeira vez) de uma propriedade da luz ou do mundo."""
    if chave not in o:
        o[chave] = valor
    return o[chave]


def mundo():
    w = bpy.context.scene.world
    bg = next((n for n in w.node_tree.nodes if n.type == "BACKGROUND"), None) if w and w.use_nodes else None
    mp = next((n for n in w.node_tree.nodes if n.type == "MAPPING"), None) if bg else None
    return w, bg, mp


def aplicar(self, _ctx=None):
    p = bpy.context.scene.minerador
    f_mundo, f_janela, _k, abajur = HORAS[p.hora]
    w, bg, mp = mundo()
    if bg:
        bg.inputs["Strength"].default_value = base(w, "m3d_forca", bg.inputs["Strength"].default_value) * f_mundo * p.hdri_forca
    if mp:
        mp.inputs["Rotation"].default_value[2] = math.radians(p.hdri_rot)
    j = luz("Luz da janela")
    if j:
        j.data.energy = base(j, "m3d_energia", j.data.energy) * f_janela * p.janela
        j.data.color = kelvin_rgb(p.kelvin)
    a = luz("Luz de apoio")
    if a:
        a.hide_render = a.hide_viewport = not p.apoio
        a.data.energy = base(a, "m3d_energia", a.data.energy)
    ab = luz("Abajur")
    if ab:
        ab.hide_render = not abajur


def hora_mudou(self, ctx):
    self["kelvin"] = HORAS[self.hora][2]  # cada hora de dia traz a sua temperatura de cor, que ainda dá para ajustar
    aplicar(self, ctx)


class Props(bpy.types.PropertyGroup):
    hora: bpy.props.EnumProperty(name="Hora do dia", items=[("dia", "Dia", ""), ("tarde", "Tarde", ""), ("noite", "Noite", "")], default="dia", update=hora_mudou)
    janela: bpy.props.FloatProperty(name="Luz da janela", min=0.0, max=4.0, default=1.0, update=aplicar, description="Intensidade da luz da janela (1 = a da sala)")
    kelvin: bpy.props.IntProperty(name="Temperatura de cor (K)", min=1800, max=9000, default=5200, update=aplicar, description="Quente (baixo) a fria (alto)")
    hdri_rot: bpy.props.FloatProperty(name="Rotação do HDRI", min=0, max=360, default=0, update=aplicar)
    hdri_forca: bpy.props.FloatProperty(name="Força do HDRI", min=0.0, max=4.0, default=1.0, update=aplicar)
    apoio: bpy.props.BoolProperty(name="Luz de apoio", default=True, update=aplicar)
    limite_min: bpy.props.IntProperty(name="Limite do render final (min)", min=1, max=120, default=10)
    amostras: bpy.props.IntProperty(name="Amostras do render final", min=128, max=2048, default=128)


def proximo_arquivo():
    PASTA_RENDERS.mkdir(parents=True, exist_ok=True)
    n = 1 + max([int(f.stem.split("_")[1]) for f in PASTA_RENDERS.glob("cena_*.jpg")] or [0])
    return PASTA_RENDERS / f"cena_{n}.jpg"


def renderizar(self, final):
    sc = bpy.context.scene
    p = sc.minerador
    ant = (sc.render.engine, sc.render.resolution_x, sc.render.resolution_y, sc.cycles.samples, sc.cycles.time_limit, sc.render.resolution_percentage)
    t0 = time.time()
    try:
        sc.render.resolution_percentage = 100
        sc.render.resolution_x = sc.render.resolution_y = 1200 if final else 640
        sc.render.image_settings.file_format, sc.render.image_settings.quality = "JPEG", 92
        if final:  # Cycles com denoiser; AgX e profundidade de campo já vêm na sala
            sc.render.engine = "CYCLES"
            sc.cycles.device, sc.cycles.use_denoising, sc.cycles.denoiser = "CPU", True, "OPENIMAGEDENOISE"
            sc.cycles.samples, sc.cycles.time_limit = p.amostras, p.limite_min * 60
        else:
            sc.render.engine = "BLENDER_EEVEE_NEXT"
            sc.eevee.taa_render_samples = 16
        bpy.ops.render.render(write_still=False)
        destino = proximo_arquivo() if final else ARQ_PREVIA
        destino.parent.mkdir(parents=True, exist_ok=True)
        bpy.data.images["Render Result"].save_render(str(destino))
    finally:
        sc.render.engine, sc.render.resolution_x, sc.render.resolution_y, sc.cycles.samples, sc.cycles.time_limit, sc.render.resolution_percentage = ant
    self.report({"INFO"}, f"{'Render final' if final else 'Prévia'} salvo em {destino} ({time.time() - t0:.0f} s)")
    return {"FINISHED"}


class OT_Previa(bpy.types.Operator):
    bl_idname, bl_label, bl_description = "minerador.previa", "Prévia rápida", "Renderiza em EEVEE (alguns segundos) e salva como a prévia do produto"

    def execute(self, _ctx):
        return renderizar(self, False)


class OT_Final(bpy.types.Operator):
    bl_idname, bl_label, bl_description = "minerador.final", "Render final", "Renderiza em Cycles com denoiser e salva nas imagens do produto"

    def execute(self, _ctx):
        return renderizar(self, True)


class PT_Painel(bpy.types.Panel):
    bl_label, bl_idname, bl_space_type, bl_region_type, bl_category = "Minerador 3D", "MINERADOR_PT_painel", "VIEW_3D", "UI", "Minerador"

    def draw(self, ctx):
        p, col = ctx.scene.minerador, self.layout.column(align=True)
        col.label(text="Luz")
        col.row().prop(p, "hora", expand=True)
        for k in ("janela", "kelvin", "hdri_rot", "hdri_forca"):
            col.prop(p, k)
        col.prop(p, "apoio", toggle=True)
        col.separator()
        col.label(text="Imagem (a câmera ativa é a que vale)")
        col.operator("minerador.previa", icon="RENDER_STILL")
        col.prop(p, "amostras")
        col.prop(p, "limite_min")
        col.operator("minerador.final", icon="RENDER_RESULT")


def abrir_painel():
    for janela in bpy.context.window_manager.windows:
        for area in janela.screen.areas:
            if area.type == "VIEW_3D":
                sp = area.spaces[0]
                sp.show_region_ui = True  # a barra lateral (N) já aparece aberta
                sp.region_3d.view_perspective = "CAMERA"
                sp.shading.type = "SOLID"  # a sala importada é grande: sólido deixa a janela leve
    return None


for c in (Props, OT_Previa, OT_Final, PT_Painel):
    bpy.utils.register_class(c)
bpy.types.Scene.minerador = bpy.props.PointerProperty(type=Props)
if not bpy.app.background:
    bpy.app.timers.register(abrir_painel, first_interval=1.0)
