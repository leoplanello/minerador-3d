"""Único lugar que cria processos. O app instalado não tem console (PyInstaller console=False): sem estas opções,
cada programa de console que ele chama (Blender, ffmpeg, claude, powershell) abre uma janela preta que pisca na tela."""
import subprocess
import sys

TimeoutExpired = subprocess.TimeoutExpired
DEVNULL = subprocess.DEVNULL
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _opts(kw, show):
    """show=True é para programas com janela própria (Chrome, instalador), que não podem ser escondidos."""
    kw["creationflags"] = kw.get("creationflags", 0) | CREATE_NO_WINDOW
    if sys.platform == "win32" and not show and "startupinfo" not in kw:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kw["startupinfo"] = si
    return kw


def run(*args, show=False, **kw):
    return subprocess.run(*args, **_opts(kw, show))


def popen(*args, show=False, **kw):
    return subprocess.Popen(*args, **_opts(kw, show))


DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
