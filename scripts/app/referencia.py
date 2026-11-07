"""Modelador a partir de um vídeo: link do Instagram ou YouTube Shorts -> vídeo e texto do post (yt-dlp), transcrição (Whisper),
troca do áudio pela sua voz gravada (ffmpeg) e busca do modelo 3D que aparece no vídeo (Printables, MakerWorld, Thingiverse).
Tudo fica em DATA/referencias/<id>. Nada é publicado; o vídeo original só serve de referência para achar o modelo."""
import json
import re
import shutil
import sys
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


# YouTube separa vídeo e som: com o ffmpeg a gente junta; sem ffmpeg, pega um arquivo só (nem sempre o YouTube tem um).
FORMATO_JUNTADO = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b"
FORMATO_UNICO = "b[height<=1080]/b"
YTDLP_EXE = paths.TOOLS / "yt-dlp" / "yt-dlp.exe"  # executável oficial, baixado e atualizado pelo app
YTDLP_RELEASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
LOGIN_RE = re.compile(r"login|sign in|cookies|rate.?limit", re.I)  # o site quer conta: a tela pede o perfil do Chrome
INDISPONIVEL_RE = re.compile(r"unavailable|private|removed|not available in your country", re.I)  # não adianta atualizar


class PrecisaLogin(ValueError):
    pass


def _ytdlp_cmd():
    """O executável baixado pelo app; no código-fonte, o yt-dlp instalado pelo pip (requirements.txt)."""
    if YTDLP_EXE.is_file():
        return [str(YTDLP_EXE)]
    if not paths.FROZEN:
        return [sys.executable, "-m", "yt_dlp"]
    raise ValueError("o yt-dlp ainda não foi baixado: clique em Tentar de novo")


def versao_ytdlp():
    r = proc.run(_ytdlp_cmd() + ["--version"], capture_output=True, text=True, timeout=60)
    return r.stdout.strip() or "desconhecida"


def atualizar_ytdlp():
    """Baixa o yt-dlp mais novo (executável oficial do GitHub) para tools/yt-dlp, conferindo o SHA-256 publicado na mesma release."""
    import hashlib
    import urllib.request

    def ler(nome):
        req = urllib.request.Request(YTDLP_RELEASE + nome, headers={"User-Agent": "Minerador3D"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    dados = ler("yt-dlp.exe")
    sumas = ler("SHA2-256SUMS").decode("utf-8", "replace")
    esperado = next((l.split()[0] for l in sumas.splitlines() if l.split() and l.split()[-1].lstrip("*") == "yt-dlp.exe"), "")
    if not esperado or hashlib.sha256(dados).hexdigest() != esperado:
        raise ValueError("o yt-dlp baixado não confere com o SHA-256 da release: não instalei")
    YTDLP_EXE.parent.mkdir(parents=True, exist_ok=True)
    novo = YTDLP_EXE.with_suffix(".novo")
    novo.write_bytes(dados)
    novo.replace(YTDLP_EXE)
    return versao_ytdlp()


def nova_pasta(url):
    pasta = PASTA / uuid.uuid4().hex[:12]
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "link.txt").write_text(url.strip(), encoding="utf-8")
    return pasta


def baixar(url, pasta, perfil=None):
    """Baixa o vídeo com o yt-dlp (até 1080p) e devolve título, descrição e o caminho do vídeo.
    perfil: pasta do seu Chrome (ex.: 'Default', 'Profile 1') cujos cookies o site pede (Instagram). Só é usado se você escolher."""
    plataforma = validar_link(url)
    ffmpeg = video.FFMPEG if video.FFMPEG.is_file() else None
    args = ["--no-playlist", "--no-warnings", "--write-info-json", "--max-filesize", "300M", "-o", str(pasta / "original.%(ext)s"),
            "-f", FORMATO_JUNTADO if ffmpeg else FORMATO_UNICO]
    if ffmpeg:
        args += ["--merge-output-format", "mp4", "--ffmpeg-location", str(ffmpeg)]
    if perfil:
        args += ["--cookies-from-browser", f"chrome:{perfil}"]
    if shutil.which("node"):
        args += ["--js-runtimes", "node"]  # ajuda o yt-dlp a resolver os desafios do YouTube
    r = proc.run(_ytdlp_cmd() + args + ["--", url.strip()], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    arquivo = next((f for f in pasta.glob("original.*") if f.suffix not in (".json", ".part", ".ytdl")), None)
    if r.returncode != 0 or arquivo is None:
        erro = " ".join(l for l in (r.stderr or r.stdout or "").splitlines() if l.startswith("ERROR"))[-400:] or "sem detalhes"
        if LOGIN_RE.search(erro):
            raise PrecisaLogin("o site pede login")
        raise ValueError(erro)
    info = pasta / "original.info.json"
    dados = json.loads(info.read_text(encoding="utf-8")) if info.is_file() else {}
    return dict(plataforma=plataforma, titulo=dados.get("title") or "", descricao=dados.get("description") or "", video=str(arquivo))


def comando_powershell(url, pasta):
    """Comando de PowerShell que baixa o vídeo com o mesmo yt-dlp do app. A tela mostra o comando para você rodar se quiser."""
    validar_link(url)  # a URL vai dentro do comando: só entra o que já passou na validação
    exe = f'"{YTDLP_EXE}"' if YTDLP_EXE.is_file() else "yt-dlp"
    return (f'& {exe} -f "{FORMATO_JUNTADO}" --merge-output-format mp4 --no-playlist --write-info-json '
            f'-o "{pasta}\original.%(ext)s" "{url.strip()}"')


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
