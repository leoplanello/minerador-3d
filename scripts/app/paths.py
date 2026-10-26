"""Onde ficam as coisas. Rodando do código (python scripts/app/desktop.py) tudo fica na pasta do projeto, como sempre.
Instalado (.exe), o programa fica em Program Files/AppData e os dados do usuário e as ferramentas em %LOCALAPPDATA%\\Minerador3D,
para sobreviverem às atualizações."""
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
SOURCE_ROOT = Path(__file__).resolve().parent.parent.parent
# RESOURCES: arquivos que vêm com o programa (static/, db/schema.sql, blender_scene.py, VERSION), somente leitura
RESOURCES = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)) if FROZEN else SOURCE_ROOT
HOME = Path(os.environ.get("MINERADOR_HOME") or (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Minerador3D"))
# DATA: banco (db/), produtos (products/) e caixa de entrada (inbox/). TOOLS: OrcaSlicer, Blender e ffmpeg.
DATA = Path(os.environ.get("MINERADOR_DATA") or (HOME / "data" if FROZEN else SOURCE_ROOT))
TOOLS = Path(os.environ.get("MINERADOR_TOOLS") or (HOME / "tools" if FROZEN else SOURCE_ROOT / "tools"))
UPDATES = HOME / "updates"


def version():
    """Versão do programa (arquivo VERSION, escrito pelo build). Rodando do código sem o arquivo, '0.0.0-dev'."""
    try:
        return (RESOURCES / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0-dev"
    except OSError:
        return "0.0.0-dev"
