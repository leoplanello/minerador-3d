"""Modelador a partir de um vídeo: link do Instagram ou YouTube Shorts -> vídeo e texto do post (yt-dlp), transcrição (Whisper),
troca do áudio pela sua voz gravada (ffmpeg) e busca do modelo 3D que aparece no vídeo (Printables, MakerWorld, Thingiverse).
Tudo fica em DATA/referencias/<id>. Nada é publicado; o vídeo original só serve de referência para achar o modelo."""
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

import paths
import proc
import texto
import video

PASTA = paths.DATA / "referencias"
WHISPER_MODELO = "small"  # tamanho do modelo do Whisper; o app baixa na primeira transcrição e guarda em DATA/whisper
STOPWORDS = set("a o as os de da do das dos e em no na nos nas um uma para por com que é the and of".split())


def validar_link(url):
    """Devolve 'instagram' ou 'youtube'. Só aceita Reel do Instagram e Short ou vídeo do YouTube; qualquer outro site é recusado."""
    u = urlparse((url or "").strip())
    if u.scheme != "https":
        raise ValueError("use o link completo, começando com https://")
    host, caminho = (u.hostname or "").removeprefix("www.").removeprefix("m."), u.path
    if host == "instagram.com" and re.fullmatch(r"/(reel|reels|p|tv)/[A-Za-z0-9_-]+/?", caminho):
        return "instagram"
    if host == "youtube.com" and re.fullmatch(r"/shorts/[A-Za-z0-9_-]{6,}/?", caminho):
        return "youtube"
    if host == "youtube.com" and caminho == "/watch" and re.search(r"(^|&)v=[A-Za-z0-9_-]{6,}", u.query):
        return "youtube"
    if host == "youtu.be" and re.fullmatch(r"/[A-Za-z0-9_-]{6,}", caminho):
        return "youtube"
    raise ValueError("aceito só link de Reel do Instagram ou de YouTube Shorts")


def nova_pasta(url):
    pasta = PASTA / uuid.uuid4().hex[:12]
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "link.txt").write_text(url.strip(), encoding="utf-8")
    return pasta


def baixar(url, pasta):
    """Baixa o vídeo com yt-dlp (até 1080p, um arquivo só, sem ffmpeg) e devolve título, descrição e o caminho do vídeo."""
    import yt_dlp  # importado aqui: o app abre sem ele e só falha quando alguém pede um link
    plataforma = validar_link(url)
    opts = dict(outtmpl=str(pasta / "original.%(ext)s"), format=FORMATO,
                noplaylist=True, quiet=True, no_warnings=True, max_filesize=300 * 1024 * 1024)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    arquivo = next(pasta.glob("original.*"), None)
    if arquivo is None:
        raise ValueError("o vídeo não foi baixado")
    return dict(plataforma=plataforma, titulo=info.get("title") or "", descricao=info.get("description") or "", video=str(arquivo))


FORMATO = "best[ext=mp4][height<=1080]/best[height<=1080]/best"
YTDLP_EXE = r"$env:LOCALAPPDATA\Minerador3D\tools\yt-dlp\yt-dlp.exe"


def comando_powershell(url, pasta):
    """Comando de PowerShell que baixa o vídeo e o texto do post com o yt-dlp. A tela mostra o comando e o app também o executa."""
    validar_link(url)  # a URL vai dentro do comando: só entra o que já passou na validação
    return (f'& "{YTDLP_EXE}" -f "{FORMATO}" --no-playlist --write-info-json '
            f'-o "{pasta}\\original.%(ext)s" "{url.strip()}"')


def baixar_powershell(url, pasta):
    """Roda o comando de PowerShell (o mesmo que a tela mostra) e devolve o mesmo dicionário de baixar()."""
    import json
    plataforma = validar_link(url)
    r = proc.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", comando_powershell(url, pasta)],
                 capture_output=True, text=True, timeout=1800)
    arquivo = next(pasta.glob("original.*"), None)
    if r.returncode != 0 or arquivo is None or arquivo.suffix == ".json":
        raise ValueError("o PowerShell não baixou o vídeo: " + ((r.stderr or r.stdout or "")[-300:]))
    info = next(pasta.glob("original*.info.json"), None)
    dados = json.loads(info.read_text(encoding="utf-8")) if info else {}
    return dict(plataforma=plataforma, titulo=dados.get("title") or "", descricao=dados.get("description") or "", video=str(arquivo))


def duracao(video_path):
    """Duração em segundos; 0 se o ffprobe não conseguir ler (a tela avisa)."""
    try:
        return video.duration(video_path)
    except (ValueError, OSError):
        return 0.0


def transcrever(video_path, modelo=WHISPER_MODELO):
    """Transcrição com faster-whisper (Whisper) no processador. Devolve o texto, o idioma e as falas com início e fim (segundos)."""
    from faster_whisper import WhisperModel
    m = WhisperModel(modelo, device="cpu", compute_type="int8", download_root=str(paths.DATA / "whisper"))
    segmentos, info = m.transcribe(str(video_path), vad_filter=True)
    falas = [dict(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip()) for s in segmentos if s.text.strip()]
    return dict(texto=" ".join(f["text"] for f in falas), idioma=info.language, segmentos=falas)


def traduzir(falas):
    """Traduz as falas para português do Brasil com o Claude (claude -p, como o texto do anúncio). Devolve uma tradução por fala, na mesma ordem."""
    if not falas:
        return []
    pedido = (f"Traduza para português do Brasil estas falas de um vídeo, uma por item e na mesma ordem. São legendas: frases curtas, "
              f"sem travessão (—), sem explicar nada. Responda SOMENTE com um JSON {{\"legendas\": [...]}} com exatamente {len(falas)} itens.\n\n"
              + json.dumps([f["text"] for f in falas], ensure_ascii=False))
    r = proc.run([texto._cmd(), "-p"], input=pedido, capture_output=True, text=True, timeout=300, encoding="utf-8")
    if "not logged in" in (r.stdout + r.stderr).lower() or r.returncode != 0:
        raise ValueError("o Claude não respondeu para a tradução (confira se ele está logado)")
    m = re.search(r"\{.*\}", r.stdout, re.S)
    try:
        legendas = json.loads(m.group(0))["legendas"]
    except (AttributeError, ValueError, KeyError, TypeError):
        raise ValueError("a tradução veio em formato inválido")
    if len(legendas) != len(falas):
        raise ValueError("a tradução veio com número de falas diferente do vídeo")
    return [str(x).replace("—", ",").strip() for x in legendas]


def consultas(titulo, descricao, transcricao, limite=3):
    """Termos para procurar o modelo: primeiro o título, depois as hashtags e as palavras mais repetidas da transcrição."""
    hashtags = re.findall(r"#(\w{3,})", descricao or "")
    palavras = [p for p in re.findall(r"[a-zà-ú0-9]{3,}", (transcricao or "").lower()) if p not in STOPWORDS]
    frequentes = [p for p, _ in sorted({p: palavras.count(p) for p in set(palavras)}.items(), key=lambda kv: -kv[1])][:6]
    titulo_limpo = re.sub(r"#\w+", "", titulo or "").strip()
    candidatos = [titulo_limpo, " ".join(hashtags[:3]), " ".join(frequentes[:4])]
    vistos, saida = set(), []
    for c in candidatos:
        c = re.sub(r"\s+", " ", c).strip()[:100]
        if len(c) >= 2 and c.lower() not in vistos:
            vistos.add(c.lower()); saida.append(c)
    return saida[:limite]


def achar_modelo(consultas_, busca):
    """Roda cada consulta na busca de modelos (model_search.search) e junta os resultados sem repetir o mesmo modelo."""
    achados, avisos, vistos = [], [], set()
    for q in consultas_:
        try:
            resultados, notas = busca(q)
        except ValueError as e:
            avisos.append(str(e)); continue
        avisos += notas
        for r in resultados:
            chave = (r.get("source"), r.get("id"))
            if chave not in vistos:
                vistos.add(chave); achados.append(r)
    return achados, avisos
