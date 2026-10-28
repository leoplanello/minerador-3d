import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import server  # noqa: E402  (põe scripts/mine no caminho)
import perfis  # noqa: E402

LOCAL_STATE = {"profile": {"last_used": "Profile 5", "info_cache": {
    "Default": {"name": "Seu Chrome"}, "Profile 4": {"name": "comercial", "user_name": "comercial@exemplo.com", "gaia_name": "Fulano"},
    "Profile 5": {"name": "Pessoal", "user_name": "pessoal@exemplo.com", "gaia_name": "Fulano"}}}}


def test_lista_os_perfis_do_chrome_so_pelo_local_state(tmp_path):
    (tmp_path / "Local State").write_text(json.dumps(LOCAL_STATE), encoding="utf-8")
    (tmp_path / "Profile 5").mkdir()
    (tmp_path / "Profile 5" / "Cookies").write_bytes(b"segredo")  # o app nem abre esse arquivo
    ps = perfis.system_profiles(tmp_path)
    assert [p["pasta"] for p in ps] == ["Profile 5", "Profile 4", "Default"]  # o último usado primeiro, depois por nome
    assert ps[0]["ultimo"] and ps[0]["email"] == "pessoal@exemplo.com" and ps[2]["nome"] == "Seu Chrome" and ps[2]["email"] == ""
    assert perfis.system_profiles(tmp_path / "nao-existe") == []
    (tmp_path / "Local State").write_text("{quebrado", encoding="utf-8")
    assert perfis.system_profiles(tmp_path) == []


def test_apelido_valido_e_nome_da_pasta():
    assert perfis.clean_nickname("  Loja   da Maria ") == "Loja da Maria"
    for ruim in ("", "a", "x" * 41, "../fora", "a/b", "nome:ruim"):
        with pytest.raises(ValueError):
            perfis.clean_nickname(ruim)


class FakeProc:
    def __init__(self):
        self.ev = threading.Event()

    def wait(self):
        self.ev.wait(5)


def test_adicionar_perfil_abre_o_chrome_na_pagina_de_login_e_marca_pronto_ao_fechar(tmp_path):
    chamadas, fake = [], FakeProc()
    nome = perfis.add_profile("Loja Teste", "mercadolivre", base=tmp_path, popen=lambda cmd, **kw: chamadas.append((cmd, kw)) or fake, chrome="chrome.exe")
    assert nome == "Minerador 3D - Loja Teste" and (tmp_path / nome).is_dir()
    cmd, kw = chamadas[0]
    assert cmd[0] == "chrome.exe" and f"--user-data-dir={tmp_path / nome}" in cmd and cmd[-1] == "https://www.mercadolivre.com.br/login" and "--new-window" in cmd
    assert kw["show"] is True  # a janela do Chrome precisa aparecer
    assert perfis.app_profiles(tmp_path)[0] | {} == dict(nome=nome, apelido="Loja Teste", dedicado=True, login=perfis._open[nome])
    assert perfis._open[nome]["estado"] == "aberto"
    with pytest.raises(ValueError, match="já está aberto"):
        perfis.add_profile("Loja Teste", "shopee", base=tmp_path, popen=lambda *a, **k: fake)
    fake.ev.set()  # você fechou a janela
    for _ in range(50):
        if perfis._open[nome]["estado"] == "pronto":
            break
        time.sleep(0.05)
    assert perfis._open[nome]["estado"] == "pronto"
    perfis.add_profile("Loja Teste", "shopee", base=tmp_path, popen=lambda *a, **k: FakeProc(), chrome="c")  # depois de pronto, abrir de novo vale
    with pytest.raises(ValueError, match="serviço"):
        perfis.add_profile("Outra", "facebook", base=tmp_path, popen=lambda *a, **k: fake)


def test_api_de_perfis_e_nada_do_chrome_real_e_copiado(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "t.sqlite")
    server.init()
    (tmp_path / "Local State").write_text(json.dumps(LOCAL_STATE), encoding="utf-8")
    monkeypatch.setattr(perfis, "CHROME_USER_DATA", tmp_path)
    base = tmp_path / "perfis-app"
    monkeypatch.setattr(perfis, "PROFILES_DIR", base)
    abertos = []
    monkeypatch.setattr(perfis, "proc", type("P", (), {"popen": staticmethod(lambda cmd, **kw: abertos.append(cmd) or FakeProc())}))
    monkeypatch.setattr(perfis, "chrome_path", lambda: "chrome.exe")
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    b = f"http://127.0.0.1:{srv.server_port}"
    try:
        d = json.load(urllib.request.urlopen(b + "/api/perfis", timeout=10))
        assert [p["pasta"] for p in d["chrome"]] == ["Profile 5", "Profile 4", "Default"] and d["app"] == [] and "mercadolivre" in d["servicos"]
        req = lambda body: urllib.request.Request(b + "/api/perfis/adicionar", json.dumps(body).encode())
        r = json.load(urllib.request.urlopen(req(dict(apelido="Comercial", servico="shopee")), timeout=10))
        assert r["perfil"] == "Minerador 3D - Comercial" and (base / r["perfil"]).is_dir()
        assert abertos and "shopee.com.br/buyer/login" in abertos[0][-1] and not any("User Data" in a for a in abertos[0])  # nunca aponta para a pasta do Chrome real
        try:
            urllib.request.urlopen(req(dict(apelido="..", servico="shopee")), timeout=10)
            raise AssertionError("devia recusar")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        assert [p["nome"] for p in json.load(urllib.request.urlopen(b + "/api/perfis", timeout=10))["app"]] == ["Minerador 3D - Comercial"]
    finally:
        srv.shutdown()
