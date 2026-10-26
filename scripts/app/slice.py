"""Fatia um 3MF/STL com o OrcaSlicer portátil (tools/orcaslicer) e lê tempo e gramas do G-code."""
import re
import subprocess
from pathlib import Path

from paths import TOOLS

ORCA = TOOLS / "orcaslicer" / "orca-slicer.exe"
BBL = TOOLS / "orcaslicer" / "resources" / "profiles" / "BBL"
# Bambu Lab A1, bocal 0,4, camada 0,20 mm, PLA genérico
SETTINGS = [BBL / "machine" / "Bambu Lab A1 0.4 nozzle.json", BBL / "process" / "0.20mm Standard @BBL A1.json"]
FILAMENT = BBL / "filament" / "Generic PLA @BBL A1.json"
PLA_DENSITY = 1.24  # g/cm³; o perfil genérico traz densidade 0. shortcut: só PLA, ler do perfil quando houver PETG


def parse_gcode(text):
    """('... total estimated time: 1h 2m 3s', 'filament used [cm3] = 3.23') -> (minutos, gramas)."""
    t = re.search(r"total estimated time:\s*((?:\d+d\s*)?(?:\d+h\s*)?(?:\d+m\s*)?(?:\d+s)?)", text)
    cm3 = re.search(r"filament used \[cm3\]\s*=\s*([\d.]+)", text)
    if not t or not t.group(1).strip() or not cm3:
        raise ValueError("não achei tempo ou filamento no G-code")
    unit = {"d": 1440, "h": 60, "m": 1, "s": 1 / 60}
    minutes = round(sum(int(n) * unit[u] for n, u in re.findall(r"(\d+)([dhms])", t.group(1))))
    return minutes, round(float(cm3.group(1)) * PLA_DENSITY, 1)


def slice_model(model, outdir):
    """Devolve (minutos, gramas, caminho do .gcode). Erros viram ValueError com texto para a GUI."""
    if not ORCA.exists():
        raise ValueError("OrcaSlicer não encontrado em tools/orcaslicer")
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("*.gcode"):  # evita ler o resultado de um fatiamento anterior
        old.unlink()
    cmd = [str(ORCA), "--slice", "0", "--outputdir", str(outdir), "--load-settings", ";".join(map(str, SETTINGS)),
           "--load-filaments", str(FILAMENT), str(model)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise ValueError("o fatiamento passou de 10 minutos; o modelo pode ser grande demais")
    out = next(outdir.glob("*.gcode"), None)
    if not out:
        raise ValueError(f"o OrcaSlicer não gerou G-code (código {r.returncode}); o modelo pode estar inválido ou não caber na mesa")
    return *parse_gcode(out.read_text(encoding="utf-8", errors="replace")), out
