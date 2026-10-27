import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import polyhaven as ph

FILES = {
    "hdri": {"1k": {"hdr": {"url": "https://x/h_1k.hdr", "md5": "m1"}}},
    **{k: {"1k": {"jpg": {"url": f"https://x/{k}.jpg", "md5": f"m_{k}"}}} for k in ph.TEXTURE_MAPS},
    "gltf": {"1k": {"gltf": {"url": "https://x/m.gltf", "md5": "mg", "include": {"m.bin": {"url": "https://x/m.bin", "md5": "mb"}, "textures/d.jpg": {"url": "https://x/d.jpg", "md5": "md"}}}}},
}


def fake_get(url):
    return json.dumps({"name": "N", "authors": {"Fulano": "All"}} if "/info/" in url else FILES).encode()


def test_lista_de_arquivos_por_tipo():
    assert ph.file_list("a", "hdri", FILES) == [("https://x/h_1k.hdr", "m1", "h_1k.hdr")]
    assert [p for _, _, p in ph.file_list("a", "texture", FILES)] == ["diff.jpg", "nor.jpg", "rough.jpg"]
    assert [p for _, _, p in ph.file_list("sofa", "model", FILES)] == ["sofa.gltf", "m.bin", "textures/d.jpg"]


def test_baixa_registra_origem_e_nao_repete(tmp_path):
    baixados = []
    fetch = lambda url, md5, dst: (baixados.append(url), dst.parent.mkdir(parents=True, exist_ok=True), dst.write_bytes(b"x"))
    reg = ph.ensure(tmp_path, get=fake_get, fetch=fetch)
    assert set(reg) == set(ph.ASSETS) and ph.available(tmp_path)
    r = reg["Sofa_01"]
    assert r["license"] == "CC0 1.0" and r["authors"] == ["Fulano"] and r["page"] == "https://polyhaven.com/a/Sofa_01" and r["files"][0]["url"].startswith("https://x/")
    n = len(baixados)
    ph.ensure(tmp_path, get=fake_get, fetch=fetch)
    assert len(baixados) == n  # tudo em disco: não baixa de novo
    texto = ph.credits_markdown(reg)
    assert "CC0" in texto and "https://polyhaven.com/a/Sofa_01" in texto and "md5 mg" in texto


def test_md5_errado_nao_grava(tmp_path, monkeypatch):
    monkeypatch.setattr(ph, "_get", lambda url: b"conteudo")
    with pytest.raises(ValueError, match="MD5"):
        ph._fetch("https://x/a.jpg", "0" * 32, tmp_path / "a.jpg")
    assert not (tmp_path / "a.jpg").exists()
    ph._fetch("https://x/a.jpg", hashlib.md5(b"conteudo").hexdigest(), tmp_path / "a.jpg")
    assert (tmp_path / "a.jpg").read_bytes() == b"conteudo"


def test_sem_registro_nao_esta_disponivel(tmp_path):
    assert not ph.available(tmp_path)
