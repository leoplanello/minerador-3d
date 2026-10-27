"""App desktop: abre a GUI numa janela própria (WebView2).
Instalado (.exe), o servidor roda numa thread deste mesmo processo. Do código, sobe o server.py se ele não estiver rodando e o encerra ao fechar a janela."""
import os
import proc as hidden
import sys
import threading
import time
import urllib.request
from pathlib import Path

import webview

import paths

URL = "http://localhost:8765"
SERVER = Path(__file__).parent / "server.py"


def up():
    try:
        urllib.request.urlopen(URL + "/api/state", timeout=2)
        return True
    except Exception:
        return False


def main():
    proc = None
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
