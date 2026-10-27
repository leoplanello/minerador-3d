"""Fatia um 3MF/STL com o Bambu Studio portátil (tools/bambustudio) e lê tempo e gramas do G-code."""
import json
import re
import proc
from pathlib import Path

from paths import TOOLS

SLICER = TOOLS / "bambustudio" / "bambu-studio.exe"
ORCA = TOOLS / "orcaslicer" / "orca-slicer.exe"
# Bambu Lab A1, bocal 0,4, camada 0,20 mm, PLA genérico (perfis que vêm dentro de cada fatiador)
PROFILES = ["machine/Bambu Lab A1 0.4 nozzle.json", "process/0.20mm Standard @BBL A1.json"]
FILAMENT = "filament/Generic PLA @BBL A1.json"
PLA_DENSITY = 1.24  # g/cm³; o perfil genérico traz densidade 0. shortcut: só PLA, ler do perfil quando houver PETG


def parse_gcode(text):
    """('... total estimated time: 1h 2m 3s', 'filament used [cm3] = 3.23') -> (minutos, gramas)."""
    t = re.search(r"total estimated time:\s*((?:\d+d\s*)?(?:\d+h\s*)?(?:\d+m\s*)?(?:\d+s)?)", text)
    cm3 = re.search(r"filament used \[cm3\]\s*=\s*([\d.]+)", text)  # formato do Orca
    mm3 = re.search(r"total filament volume \[cm\^3\]\s*:\s*([\d.]+)", text)  # Bambu Studio: o rótulo diz cm³, mas o valor vem em mm³
    if not t or not t.group(1).strip() or not (cm3 or mm3):
        raise ValueError("não achei tempo ou filamento no G-code")
    unit = {"d": 1440, "h": 60, "m": 1, "s": 1 / 60}
    minutes = round(sum(int(n) * unit[u] for n, u in re.findall(r"(\d+)([dhms])", t.group(1))))
    return minutes, round((float(cm3.group(1)) if cm3 else float(mm3.group(1)) / 1000) * PLA_DENSITY, 1)


def slice_model(model, outdir):
    """Devolve (minutos, gramas, caminho do .gcode). Erros viram ValueError com texto para a GUI."""
    slicer = SLICER if SLICER.exists() else ORCA  # shortcut: o OrcaSlicer só entra se já estiver em tools/, o app não o baixa mais
    if not slicer.exists():
        raise ValueError("Bambu Studio não encontrado em tools/bambustudio")
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("*.gcode"):  # evita ler o resultado de um fatiamento anterior
        old.unlink()
    bbl = slicer.parent / "resources" / "profiles" / "BBL"
    cmd = [str(slicer), "--slice", "0", "--outputdir", str(outdir), "--load-settings", ";".join(str(bbl / x) for x in PROFILES),
           "--load-filaments", str(bbl / FILAMENT), str(model)]
    try:
        r = proc.run(cmd, capture_output=True, text=True, timeout=600)
    except proc.TimeoutExpired:
        raise ValueError("o fatiamento passou de 10 minutos; o modelo pode ser grande demais")
    out = next(outdir.glob("*.gcode"), None)
    if not out:
        try:  # o Bambu Studio explica a falha no result.json
            why = json.loads((outdir / "result.json").read_text(encoding="utf-8"))["error_string"]
        except (OSError, ValueError, KeyError):
            why = ""
        if not why or "fully inside" in why:  # o texto dele é em inglês; este é o motivo de quase todo caso
            why = "o modelo não cabe na mesa da A1 (256 × 256 × 256 mm) ou está inválido; escolha um arquivo menor ou outro modelo"
        raise ValueError(f"o Bambu Studio não gerou G-code (código {r.returncode}): {why}")
    return *parse_gcode(out.read_text(encoding="utf-8", errors="replace")), out
