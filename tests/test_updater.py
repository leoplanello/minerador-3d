import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import paths
import tools_installer as ti
import updater


class Resp(io.BytesIO):
    def __init__(self, data, url="https://github.com/x", headers=None):
        super().__init__(data)
        self.headers = headers or {"Content-Length": str(len(data))}
        self._url = url

    def geturl(self):
        return self._url


def test_versoes():
    assert updater.parse_version("v1.2.3") == (1, 2, 3) and updater.parse_version("0.0.0-dev") == (0, 0, 0) and updater.parse_version("lixo") == (0,)
    assert updater.is_newer("1.10.0", "1.9.9") and updater.is_newer("2.0", "1.9.9") and updater.is_newer("1.0.1", "1.0")
    assert not updater.is_newer("1.0.0", "1.0") and not updater.is_newer("1.0.0", "1.0.1") and not updater.is_newer("", "1.0.0")


def _release(tag="v1.1.0", com_sha=True):
    assets = [dict(name=f"Minerador3D-Setup-{tag[1:]}.exe", browser_download_url=f"https://github.com/o/r/releases/download/{tag}/Minerador3D-Setup-{tag[1:]}.exe", size=5)]
    if com_sha:
        assets.append(dict(name=f"Minerador3D-Setup-{tag[1:]}.exe.sha256", browser_download_url=f"https://github.com/o/r/releases/download/{tag}/Minerador3D-Setup-{tag[1:]}.exe.sha256"))
    return dict(tag_name=tag, html_url="https://github.com/o/r/releases/tag/" + tag, body="Novidades\n- tal coisa", assets=assets)


def test_check_acha_versao_nova_e_o_instalador(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout=0: Resp(json.dumps(_release()).encode()))
    r = updater.check("1.0.0")
    assert r["newer"] and r["latest"] == "1.1.0" and r["asset_name"] == "Minerador3D-Setup-1.1.0.exe" and r["sha_url"].endswith(".sha256") and "Novidades" in r["notes"]
    assert not updater.check("1.1.0")["newer"]
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout=0: Resp(json.dumps(_release(com_sha=False)).encode()))
    assert "asset_url" not in updater.check("1.0.0")  # sem .sha256 na release não há instalador seguro para baixar


def test_check_sem_rede_devolve_erro_sem_quebrar(monkeypatch):
    def boom(req, timeout=0):
        raise OSError("sem rede")
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    r = updater.check("1.0.0")
    assert "sem rede" in r["error"] and not r.get("newer")


def _info(corpo, hash_certo=True):
    sha = hashlib.sha256(corpo).hexdigest() if hash_certo else "0" * 64
    return dict(asset_url="https://github.com/o/r/a.exe", sha_url="https://github.com/o/r/a.exe.sha256", asset_name="Minerador3D-Setup-1.1.0.exe", size=len(corpo)), sha


def test_download_confere_sha256(monkeypatch, tmp_path):
    corpo = b"instalador" * 1000
    info, sha = _info(corpo)
    monkeypatch.setattr(updater, "_fetch", lambda url, limit: Resp(f"{sha}  a.exe\n".encode()) if url.endswith(".sha256") else Resp(corpo))
    feito = []
    p = updater.download(info, progress=lambda d, t: feito.append((d, t)), dest_dir=tmp_path)
    assert p.read_bytes() == corpo and feito[-1] == (len(corpo), len(corpo))
    info, sha = _info(corpo, hash_certo=False)
    monkeypatch.setattr(updater, "_fetch", lambda url, limit: Resp(f"{sha}  a.exe\n".encode()) if url.endswith(".sha256") else Resp(corpo))
    with pytest.raises(ValueError, match="SHA-256"):
        updater.download(info, dest_dir=tmp_path)
    assert not (tmp_path / "Minerador3D-Setup-1.1.0.exe").exists()  # o que não confere é apagado


def test_download_so_de_hosts_do_github_e_sha_valido(monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        updater._fetch("https://evil.example.com/a.exe", None)
    with pytest.raises(ValueError):
        updater._fetch("http://github.com/a.exe", None)
    monkeypatch.setattr(updater, "_fetch", lambda url, limit: Resp(b"nao e um hash"))
    with pytest.raises(ValueError, match="inválido"):
        updater.download(dict(asset_url="https://github.com/a", sha_url="https://github.com/b", asset_name="Minerador3D-Setup-1.exe"), dest_dir=tmp_path)
    with pytest.raises(ValueError):
        updater.download(dict(asset_url="https://github.com/a"), dest_dir=tmp_path)


def test_instalar_so_no_app_empacotado(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "FROZEN", False)
    with pytest.raises(ValueError, match="instalado"):
        updater.launch_installer(tmp_path / "x.exe")
    chamadas = []
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **kw: chamadas.append(cmd))
    updater.launch_installer(tmp_path / "x.exe")
    assert "/VERYSILENT" in chamadas[0] and "/RELAUNCH=1" in chamadas[0]


# ---------------- instalador de ferramentas
def _zip(arquivos):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in arquivos.items():
            z.writestr(n, d)
    return b.getvalue()


def test_extracao_nos_tres_modos(tmp_path):
    z = tmp_path / "t.zip"
    z.write_bytes(_zip({"OrcaSlicer/orca-slicer.exe": b"o", "OrcaSlicer/resources/a.json": b"j", "LEIAME.txt": b"x"}))
    ti.extract(z, tmp_path / "orca", dict(mode="strip", exe="orca-slicer.exe"))
    assert (tmp_path / "orca" / "orca-slicer.exe").read_bytes() == b"o" and (tmp_path / "orca" / "resources" / "a.json").exists() and not (tmp_path / "orca" / "LEIAME.txt").exists()
    z.write_bytes(_zip({"blender-4.2.3/blender.exe": b"b", "blender-4.2.3/4.2/x.py": b"p"}))
    ti.extract(z, tmp_path / "bl", dict(mode="keep", exe="blender.exe"))
    assert (tmp_path / "bl" / "blender-4.2.3" / "blender.exe").exists()
    z.write_bytes(_zip({"ffmpeg-9/bin/ffmpeg.exe": b"f", "ffmpeg-9/bin/ffprobe.exe": b"p", "ffmpeg-9/doc/x.html": b"h"}))
    ti.extract(z, tmp_path / "ff", dict(mode="files", files=("ffmpeg.exe", "ffprobe.exe")))
    assert sorted(p.name for p in (tmp_path / "ff").iterdir()) == ["ffmpeg.exe", "ffprobe.exe"]


def test_extracao_barra_caminho_fora_da_pasta(tmp_path):
    z = tmp_path / "t.zip"
    z.write_bytes(_zip({"pasta/orca-slicer.exe": b"o", "pasta/../../fora.txt": b"x"}))
    with pytest.raises(ValueError, match="inválido"):
        ti.extract(z, tmp_path / "d", dict(mode="strip", exe="orca-slicer.exe"))
    assert not (tmp_path / "fora.txt").exists()
    with pytest.raises(ValueError):
        ti.extract(z, tmp_path / "e", dict(mode="files", files=("nao-existe.exe",)))


def test_sha_do_fornecedor_em_dois_formatos(monkeypatch):
    blender = "\n".join([f"{'a' * 64}  blender-4.2.3-linux-x64.tar.xz", f"{'b' * 64}  blender-4.2.3-windows-x64.zip"]).encode()
    monkeypatch.setattr(ti, "_open", lambda url: Resp(blender))
    assert ti.expected_sha(ti.MANIFEST["blender"]["sources"][0]) == "b" * 64
    monkeypatch.setattr(ti, "_open", lambda url: Resp(("c" * 64).encode()))
    assert ti.expected_sha(ti.MANIFEST["ffmpeg"]["sources"][0]) == "c" * 64
    assert ti.expected_sha(ti.MANIFEST["orcaslicer"]["sources"][0]) == ti.MANIFEST["orcaslicer"]["sources"][0]["sha256"]
    monkeypatch.setattr(ti, "_open", lambda url: Resp(b"sem hash aqui"))
    with pytest.raises(ValueError):
        ti.expected_sha(ti.MANIFEST["ffmpeg"]["sources"][0])


def test_instalar_ferramenta_confere_e_instala(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "TOOLS", tmp_path / "tools")
    corpo = _zip({"ffmpeg-9/bin/ffmpeg.exe": b"f", "ffmpeg-9/bin/ffprobe.exe": b"p"})
    sha = hashlib.sha256(corpo).hexdigest()
    monkeypatch.setattr(ti, "_open", lambda url: Resp(("0" * 64 if "mudado" in url else sha).encode()) if url.endswith(".sha256") else Resp(corpo))
    assert not ti.installed("ffmpeg")
    etapas = []
    ti.install("ffmpeg", lambda stage, d, t: etapas.append(stage))
    assert ti.installed("ffmpeg") and (paths.TOOLS / "ffmpeg" / "ffprobe.exe").exists()
    assert etapas[0] == "baixando" and "conferindo" in etapas and etapas[-1] == "instalando"
    assert not list((paths.TOOLS / "_downloads").glob("*.zip")) and not (paths.TOOLS / "ffmpeg.novo").exists()
    # download adulterado: não instala
    monkeypatch.setattr(ti, "_open", lambda url: Resp(sha.encode()) if url.endswith(".sha256") else Resp(corpo + b"x"))
    import shutil
    shutil.rmtree(paths.TOOLS / "ffmpeg")
    with pytest.raises(ValueError, match="SHA-256"):
        ti.install("ffmpeg")
    assert not ti.installed("ffmpeg")
    with pytest.raises(ValueError):
        ti.install("desconhecida")


def test_espelho_quando_a_primeira_fonte_cai(monkeypatch, tmp_path):
    import urllib.error
    monkeypatch.setattr(paths, "TOOLS", tmp_path / "tools")
    monkeypatch.setattr("time.sleep", lambda s: None)
    corpo = _zip({"ffmpeg-9/bin/ffmpeg.exe": b"f", "ffmpeg-9/bin/ffprobe.exe": b"p"})
    sha = hashlib.sha256(corpo).hexdigest()
    visitados = []

    def abrir(url):
        visitados.append(url)
        if "gyan.dev" in url:
            raise urllib.error.HTTPError(url, 503, "indisponível", {}, None)
        return Resp(f"{sha}  ffmpeg-master-latest-win64-gpl.zip".encode()) if url.endswith("checksums.sha256") else Resp(corpo)
    monkeypatch.setattr(ti, "_open", abrir)
    ti.install("ffmpeg")
    assert ti.installed("ffmpeg") and sum("gyan.dev" in u for u in visitados) == 3  # 3 tentativas na primeira fonte antes do espelho
    # todas as fontes caem: o erro lista cada uma
    monkeypatch.setattr(ti, "_open", lambda url: (_ for _ in ()).throw(urllib.error.HTTPError(url, 503, "x", {}, None)))
    import shutil
    shutil.rmtree(paths.TOOLS / "ffmpeg")
    with pytest.raises(ValueError, match="gyan.dev.*github.com"):
        ti.install("ffmpeg")


def test_hosts_permitidos_nas_ferramentas():
    for ok in ("https://download.blender.org/a.zip", "https://github.com/a", "https://release-assets.githubusercontent.com/x", "https://www.gyan.dev/a.zip"):
        assert ti._host_ok(ok)
    for bad in ("http://github.com/a", "https://github.com.evil.com/a", "https://evil.com/github.com"):
        assert not ti._host_ok(bad)
