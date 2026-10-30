import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import referencia  # noqa: E402
import video  # noqa: E402


@pytest.mark.parametrize("url, esperado", [
    ("https://www.instagram.com/reel/C8xYz12AbCd/", "instagram"),
    ("https://instagram.com/p/XYZ_abc-9/", "instagram"),
    ("https://www.youtube.com/shorts/abcdefghijk", "youtube"),
    ("https://youtu.be/abcdefghijk", "youtube"),
    ("https://www.youtube.com/watch?v=abcdefghijk&t=3", "youtube"),
])
def test_aceita_reel_e_short(url, esperado):
    assert referencia.validar_link(url) == esperado


@pytest.mark.parametrize("url", [
    "http://www.instagram.com/reel/C8xYz12AbCd/",     # sem https
    "https://www.instagram.com/leoplanello/",          # perfil, não é vídeo
    "https://www.youtube.com/@canal",                  # canal
    "https://www.youtube.com/watch?list=PL123",        # sem vídeo
    "https://evil.com/shorts/abcdefghijk",             # outro site
    "https://instagram.com.evil.com/reel/C8xYz12AbCd/",
    "",
])
def test_recusa_outros_links(url):
    with pytest.raises(ValueError):
        referencia.validar_link(url)


def test_consultas_tiram_hashtag_e_repeticao():
    titulo = "Suporte de parede #impressao3d"
    descricao = "Peça de impressão 3D #suporte #roteador #impressao3d"
    transcricao = "suporte suporte roteador parede o a de"
    cs = referencia.consultas(titulo, descricao, transcricao)
    assert cs[0] == "Suporte de parede"
    assert "suporte roteador impressao3d" in cs[1] or "suporte roteador" in cs[1]
    assert len(cs) <= 3
    assert len({c.lower() for c in cs}) == len(cs)
    assert all("#" not in c for c in cs)


def test_consultas_sem_nada_util_devolve_lista_vazia():
    assert referencia.consultas("", "", "") == []


def test_achar_modelo_junta_sem_repetir_e_guarda_avisos():
    respostas = {
        "a": ([dict(source="printables", id="1", title="A"), dict(source="printables", id="2", title="B")], []),
        "b": ([dict(source="printables", id="2", title="B"), dict(source="makerworld", id="9", title="C")], ["sem perfil"]),
    }

    def busca(q):
        if q == "c":
            raise ValueError("Printables fora do ar")
        return respostas[q]

    achados, avisos = referencia.achar_modelo(["a", "b", "c"], busca)
    assert [(r["source"], r["id"]) for r in achados] == [("printables", "1"), ("printables", "2"), ("makerworld", "9")]
    assert avisos == ["sem perfil", "Printables fora do ar"]


@pytest.mark.skipif(not Path(video.FFMPEG or "").exists(), reason="ffmpeg não instalado")
def test_troca_o_audio_pela_gravacao(tmp_path):
    original, voz, saida = tmp_path / "o.mp4", tmp_path / "voz.wav", tmp_path / "novo.mp4"
    subprocess.run([str(video.FFMPEG), "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x284:rate=10:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(original)], check=True)
    subprocess.run([str(video.FFMPEG), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=1", str(voz)], check=True)
    assert referencia.trocar_audio(original, voz, saida) == saida
    assert saida.stat().st_size > 1000


def test_trocar_audio_sem_arquivo_de_entrada_falha(tmp_path):
    if not Path(video.FFMPEG or "").exists():
        pytest.skip("ffmpeg não instalado")
    with pytest.raises(ValueError):
        referencia.trocar_audio(tmp_path / "nao-existe.mp4", tmp_path / "nao-existe.wav", tmp_path / "saida.mp4")


def test_baixar_recusa_link_ruim_antes_de_qualquer_download(tmp_path):
    pytest.importorskip("yt_dlp")
    with pytest.raises(ValueError):
        referencia.baixar("https://evil.com/video", tmp_path)
    assert not list(tmp_path.glob("original.*"))


def test_arquivo_do_trabalho_nao_sai_da_pasta(tmp_path, monkeypatch):
    import modelador
    monkeypatch.setattr(referencia, "PASTA", tmp_path)
    pasta = tmp_path / "abc123"
    (pasta / "estudio").mkdir(parents=True)
    (pasta / "original.mp4").write_bytes(b"v")
    (pasta / "estudio" / "medidas.png").write_bytes(b"p")
    (pasta / "link.txt").write_text("x")
    (tmp_path / "segredo.txt").write_text("fora")
    modelador.JOBS["abc123"] = dict(id="abc123", status="ok")
    assert modelador.caminho_arquivo("abc123", "original").name == "original.mp4"
    assert modelador.caminho_arquivo("abc123", "estudio/medidas.png").name == "medidas.png"
    for ruim in ("../segredo.txt", "estudio/../../segredo.txt", "link.txt", "voz"):
        with pytest.raises(ValueError):
            modelador.caminho_arquivo("abc123", ruim)
    with pytest.raises(ValueError):
        modelador.caminho_arquivo("nao-existe", "original")
