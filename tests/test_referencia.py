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


def test_comando_powershell_tem_url_validada_e_pasta(tmp_path):
    url = "https://www.instagram.com/reel/C8xYz12AbCd/"
    cmd = referencia.comando_powershell(url, tmp_path)
    assert cmd.startswith('& "$env:LOCALAPPDATA\\Minerador3D\\tools\\yt-dlp\\yt-dlp.exe"')
    assert f'"{url}"' in cmd and "--write-info-json" in cmd and "--no-playlist" in cmd
    assert str(tmp_path) in cmd and "original.%(ext)s" in cmd


def test_comando_powershell_recusa_url_fora_da_lista(tmp_path):
    with pytest.raises(ValueError):
        referencia.comando_powershell('https://evil.com/x";calc', tmp_path)


def test_traduzir_devolve_uma_linha_por_fala(monkeypatch):
    import proc, texto
    monkeypatch.setattr(texto, "_cmd", lambda: "claude")
    pedidos = []

    def fake_run(cmd, input=None, **kw):
        pedidos.append(input)
        return subprocess.CompletedProcess(cmd, 0, stdout='Aqui: {"legendas": ["Oi.", "Tchau."]}', stderr="")

    monkeypatch.setattr(proc, "run", fake_run)
    falas = [dict(start=0, end=1, text="Hi."), dict(start=1, end=2, text="Bye.")]
    assert referencia.traduzir(falas) == ["Oi.", "Tchau."]
    assert "Hi." in pedidos[0] and "2 itens" in pedidos[0]


def test_traduzir_recusa_numero_de_falas_diferente(monkeypatch):
    import proc, texto
    monkeypatch.setattr(texto, "_cmd", lambda: "claude")
    monkeypatch.setattr(proc, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout='{"legendas": ["so uma"]}', stderr=""))
    with pytest.raises(ValueError):
        referencia.traduzir([dict(start=0, end=1, text="a"), dict(start=1, end=2, text="b")])


def test_transcrever_guarda_falas_com_tempo(monkeypatch):
    import types
    segs = [types.SimpleNamespace(start=0.0, end=1.2, text=" Olá "), types.SimpleNamespace(start=1.2, end=2.0, text="  ")]

    class Modelo:
        def __init__(self, *a, **kw): pass
        def transcribe(self, *a, **kw): return iter(segs), types.SimpleNamespace(language="en")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Modelo))
    r = referencia.transcrever("x.mp4")
    assert r == dict(texto="Olá", idioma="en", segmentos=[dict(start=0.0, end=1.2, text="Olá")])


def test_arquivos_da_previa_e_do_final(tmp_path, monkeypatch):
    import modelador
    monkeypatch.setattr(referencia, "PASTA", tmp_path)
    (tmp_path / "abc").mkdir()
    (tmp_path / "abc" / "previa.jpg").write_bytes(b"j")
    modelador.JOBS["abc"] = dict(id="abc", status="ok")
    assert modelador.caminho_arquivo("abc", "previa").name == "previa.jpg"
    with pytest.raises(ValueError):
        modelador.caminho_arquivo("abc", "final")  # ainda não existe
    with pytest.raises(ValueError):
        modelador.caminho_arquivo("abc", "com-sua-voz")  # rota antiga, removida
