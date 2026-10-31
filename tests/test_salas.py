import hashlib
import io
import json
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import server  # noqa: E402
import render  # noqa: E402
import salas  # noqa: E402


def pacote():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("GLB/sala.glb", b"glTF" * 5000)
        z.writestr("CREDITOS.md", "creditos")
    return buf.getvalue()


class Resposta:
    def __init__(self, dados, parcial):
        self._b, self.status = io.BytesIO(dados), 206 if parcial else 200
        self.headers = {"Content-Length": str(len(dados))}

    def read(self, n):
        return self._b.read(n)


@pytest.fixture()
def sala_falsa(tmp_path, monkeypatch):
    dados = pacote()
    monkeypatch.setattr(salas.paths, "DATA", tmp_path)
    monkeypatch.setitem(salas.SALAS, "teste", dict(salas.SALAS["escritorio-secretaria"], arquivo="teste.zip", modelo="GLB/sala.glb", sha256=hashlib.sha256(dados).hexdigest(), label="Sala de teste"))
    vistos = []

    def abrir(url, extra=None):
        vistos.append((url, extra))
        inicio = int(extra["Range"][6:-1]) if extra else 0
        return Resposta(dados[inicio:], bool(extra))
    return dados, abrir, vistos


def test_baixar_confere_o_hash_e_instala_sem_tocar_nos_dados(tmp_path, sala_falsa):
    dados, abrir, vistos = sala_falsa
    for pasta in ("db", "products/1", "inbox"):  # nada disso pode mudar
        (tmp_path / pasta).mkdir(parents=True)
        (tmp_path / pasta / "dado.txt").write_text("meu dado")
    etapas = []
    salas.baixar("teste", lambda st, done, total: etapas.append((st, done, total)), abrir)
    assert salas.modelo("teste") == tmp_path / "salas" / "teste" / "GLB" / "sala.glb"
    assert vistos[0][0] == salas.RELEASE + "teste.zip" and vistos[0][1] is None
    assert [e[0] for e in etapas][-2:] == ["conferindo", "instalando"] and etapas[-1][1] == len(dados)
    assert not list((tmp_path / "salas" / "_downloads").glob("*.parte")) and not (tmp_path / "salas" / "teste.novo").exists()
    assert all((tmp_path / p / "dado.txt").read_text() == "meu dado" for p in ("db", "products/1", "inbox"))


def test_baixar_retoma_de_onde_parou(tmp_path, sala_falsa):
    dados, abrir, vistos = sala_falsa
    parte = tmp_path / "salas" / "_downloads" / "teste.zip.parte"
    parte.parent.mkdir(parents=True)
    parte.write_bytes(dados[:1000])  # a queda de rede deixou 1000 bytes
    salas.baixar("teste", abrir=abrir)
    assert vistos[0][1] == {"Range": "bytes=1000-"} and salas.modelo("teste")


def test_baixar_arquivo_errado_apaga_o_download_e_nao_instala(tmp_path, sala_falsa):
    dados, _, _ = sala_falsa
    with pytest.raises(ValueError, match="SHA-256"):
        salas.baixar("teste", abrir=lambda url, extra=None: Resposta(dados[:-1] + b"x", False))
    assert salas.modelo("teste") is None and not list((tmp_path / "salas").rglob("*.parte"))


def test_so_o_host_do_github_e_aceito_para_baixar():
    import tools_installer
    assert tools_installer._host_ok(salas.RELEASE + "x.zip") and tools_installer._host_ok("https://release-assets.githubusercontent.com/x")
    assert not tools_installer._host_ok("https://github.com.evil.com/x") and not tools_installer._host_ok("http://github.com/x")


def test_escolher_sala_nao_baixada_pede_o_download(sala_falsa):
    assert {"apartamento-3-quartos", "escritorio-secretaria"} <= set(render.CENA_CHOICES["ambiente"]) and render.clean_cena(dict(ambiente="apartamento-3-quartos"))["ambiente"] == "apartamento-3-quartos"
    with pytest.raises(ValueError, match="baixe a sala"):
        render.cena_cfg(render.clean_cena(dict(ambiente="escritorio-secretaria")))


def test_creditos_citam_os_autores_o_cgtrader_e_a_retirada():
    txt = salas.creditos_markdown()
    for m in salas.SALAS.values():
        assert m["autor"] in txt and m["pagina"] in txt and "cgtrader.com" in m["pagina"]
    assert "retirada" in txt


def test_api_de_download_das_salas(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    monkeypatch.setattr(salas.paths, "DATA", tmp_path)
    server.init()
    chamadas = []
    monkeypatch.setattr(salas, "baixar", lambda sid, progress=None, abrir=None: (chamadas.append(sid), progress("baixando", 5, 10), time.sleep(0.3)))
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    b = f"http://127.0.0.1:{srv.server_port}"

    def post(p, d):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(b + p, json.dumps(d).encode()), timeout=10))
        except urllib.error.HTTPError as e:
            return json.load(e) | {"http": e.code}
    try:
        lista = json.load(urllib.request.urlopen(b + "/api/salas", timeout=10))["salas"]
        assert {s["id"]: (s["size_mb"], s["instalada"]) for s in lista} == {"apartamento-3-quartos": (1161, False), "escritorio-secretaria": (150, False)}
        assert post("/api/salas/baixar", dict(id="../x"))["http"] == 400
        assert post("/api/salas/baixar", dict(id="escritorio-secretaria"))["ok"]
        assert post("/api/salas/baixar", dict(id="apartamento-3-quartos"))["http"] == 400  # um download por vez
        time.sleep(0.8)
        job = server.SALA_DL["escritorio-secretaria"]
        assert job["status"] == "done" and chamadas == ["escritorio-secretaria"]
    finally:
        srv.shutdown()
