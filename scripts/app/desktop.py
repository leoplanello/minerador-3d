"""App desktop: abre a GUI numa janela própria (WebView2).
Instalado (.exe), o servidor roda numa thread deste mesmo processo. Do código, sobe o server.py se ele não estiver rodando e o encerra ao fechar a janela."""
import json
import os
import proc as hidden
import sys
import threading
import time
import urllib.request
from pathlib import Path

import webview

import paths

URL = f"http://localhost:{paths.PORT}"
SERVER = Path(__file__).parent / "server.py"


def up():
    try:
        urllib.request.urlopen(URL + "/api/state", timeout=2)
        return True
    except Exception:
        return False


def stale_server():
    """Servidor de outra versão na nossa porta (app antigo que não fechou, ou .bat antigo): a janela nova abriria nele e mostraria a versão velha."""
    try:
        v = json.load(urllib.request.urlopen(URL + "/api/version", timeout=2))["version"]
        return v != paths.version()
    except Exception:
        return True  # versões antigas nem têm /api/version


def free_port():
    """Encerra o processo do Minerador (ou do python do .bat) que escuta na porta. Só esses; qualquer outro programa fica em paz."""
    out = hidden.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        cols = line.split()
        if len(cols) >= 5 and cols[1].endswith(f":{paths.PORT}") and cols[3] == "LISTENING":
            img = hidden.run(["tasklist", "/FI", f"PID eq {cols[4]}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout.lower()
            if any(n in img for n in ("minerador3d.exe", "pythonw.exe", "python.exe")) and cols[4] != str(os.getpid()):
                hidden.run(["taskkill", "/PID", cols[4], "/F"], capture_output=True)
    for _ in range(10):
        if not up():
            return
        time.sleep(0.5)


def main():
    proc = None
    if paths.FROZEN and up() and stale_server():
        free_port()
    if not up():
        if paths.FROZEN:
            import server  # noqa: E402  (empacotado junto; abre o banco em %LOCALAPPDATA%)
            httpd = server.make_server()
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
        else:
            proc = hidden.popen([sys.executable, str(SERVER)])
    for _ in range(60):
        if up():
            break
        time.sleep(1)
    if os.environ.get("MINERADOR_SEM_JANELA"):  # testes do build: só o servidor, sem abrir janela
        threading.Event().wait()
    webview.create_window("Minerador 3D", URL, width=1360, height=860, min_size=(1000, 640))
    webview.start()
    if proc:  # só derruba o servidor que esta janela iniciou; leituras em curso param junto
        proc.terminate()


if __name__ == "__main__":
    main()
