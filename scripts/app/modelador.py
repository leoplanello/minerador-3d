"""Modelador: do link de um Reel ou Short até o estúdio do modelo 3D. Cada etapa roda numa thread; o andamento fica em JOBS e
a tela consulta /api/referencia. Os arquivos vão para DATA/referencias/<id>/ e nada é publicado."""
import sys
import threading
from pathlib import Path

import estudio
import proc
import referencia
import video

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mine"))
import model_search  # noqa: E402  (busca de modelos: Printables; MakerWorld e Thingiverse precisam de perfil do Chrome)
import perfis as perfis_chrome  # noqa: E402  (perfis do seu Chrome, só para escolher o de um site que pede login)

JOBS = {}
LOCK = threading.Lock()
BLENDER = threading.Lock()  # um render de cada vez, como o resto do app
MAX_VOZ = 50 * 1024 * 1024


def _set(jid, **kw):
    with LOCK:
        JOBS[jid].update(kw)


def estado(jid):
    with LOCK:
        job = JOBS.get(jid)
        if job is None:
            raise ValueError("trabalho não encontrado: abra o link de novo")
        return dict(job)


def iniciar(url):
    """Valida o link na hora (erro na tela) e começa o download e a transcrição em segundo plano."""
    referencia.validar_link(url)
    pasta = referencia.nova_pasta(url)
    jid = pasta.name
    with LOCK:
        JOBS[jid] = dict(id=jid, status="running", etapa="baixando", msg="Baixando o vídeo…", url=url,
                         comando=referencia.comando_powershell(url, pasta))
    threading.Thread(target=_rodar_download, args=(jid, url, pasta), daemon=True).start()
    return estado(jid)


def baixar_de_novo(jid, perfil=None):
    """Tenta o download de novo; perfil = pasta do seu Chrome, quando o site pediu login."""
    job = estado(jid)
    if job.get("status") == "running" and job.get("etapa") == "baixando":
        raise ValueError("o download já está em andamento")
    _set(jid, status="running", etapa="baixando", msg="Baixando o vídeo…", perfis=[])
    threading.Thread(target=_rodar_download, args=(jid, job["url"], referencia.PASTA / jid, perfil), daemon=True).start()
    return estado(jid)


def _baixar(url, pasta, perfil):
    """Baixa; se o yt-dlp falhar por causa do site (não por link fora do ar), atualiza o yt-dlp sozinho e tenta mais uma vez."""
    try:
        return referencia.baixar(url, pasta, perfil)
    except referencia.PrecisaLogin:
        raise
    except ValueError as erro:
        if referencia.INDISPONIVEL_RE.search(str(erro)):
            raise
        try:
            referencia.atualizar_ytdlp()
        except Exception as e:  # sem internet para atualizar: mostra o erro original e o motivo
            raise ValueError(f"{erro} (não consegui atualizar o yt-dlp: {str(e)[:120]})")
        return referencia.baixar(url, pasta, perfil)


def _rodar_download(jid, url, pasta, perfil=None):
    try:
        d = _baixar(url, pasta, perfil)
    except referencia.PrecisaLogin:
        _set(jid, status="login", etapa="login", perfis=perfis_chrome.system_profiles(),
             msg="Este site pede login. Escolha o perfil do Chrome onde você já entrou nele (feche o Chrome antes) e tente de novo.")
        return
    except Exception as e:  # yt-dlp levanta erros próprios; a tela só precisa da mensagem
        _set(jid, status="error", etapa="erro", msg=f"Não consegui baixar o vídeo: {str(e)[:260]}")
        return
    _set(jid, titulo=d["titulo"], descricao=d["descricao"], plataforma=d["plataforma"], video=d["video"], duracao=referencia.duracao(d["video"]),
         etapa="transcrevendo", msg="Vídeo baixado. Transcrevendo com Whisper…")
    try:
        t = referencia.transcrever(d["video"])
        consultas = referencia.consultas(d["titulo"], d["descricao"], t["texto"])
        legendas = [dict(start=f["start"], end=f["end"], text=f["text"], original=f["text"]) for f in t["segmentos"]]
        aviso = ""
        if legendas and t["idioma"] != "pt":
            _set(jid, etapa="traduzindo", msg="Traduzindo as legendas para português…")
            try:
                for f, pt in zip(legendas, referencia.traduzir(t["segmentos"])):
                    f["text"] = pt
            except Exception as e:  # sem tradução (Claude fora, tempo esgotado), as legendas ficam no idioma original para você editar
                aviso = f" Não consegui traduzir ({str(e)[:120]}): as legendas estão no idioma original."
        _set(jid, status="ok", etapa="pronto", transcricao=t["texto"], idioma=t["idioma"], consultas=consultas, legendas=legendas,
             msg="Pronto: confira o texto, edite as legendas e monte o vídeo." + aviso)
    except Exception as e:  # faster-whisper ausente ou modelo não baixou: o vídeo continua utilizável
        _set(jid, status="ok", etapa="pronto", transcricao="", idioma="", legendas=[], consultas=referencia.consultas(d["titulo"], d["descricao"], ""),
             msg=f"Vídeo pronto, mas a transcrição falhou: {str(e)[:200]}")


def gravar_voz(jid, dados):
    """Guarda a gravação da sua voz (o navegador manda webm, ogg ou mp4). Ainda não mexe no vídeo."""
    estado(jid)
    if not dados or len(dados) > MAX_VOZ:
        raise ValueError("gravação vazia ou maior que 50 MB")
    destino = referencia.PASTA / jid / "voz.webm"
    destino.write_bytes(dados)
    _set(jid, voz=str(destino), msg="Voz salva. Escolha como ela entra no vídeo e gere o vídeo final.")
    return estado(jid)


def _editor(job, cfg, legendas):
    """Valida o que veio da tela (corte, enquadramento, legendas) contra o vídeo baixado."""
    if not job.get("video"):
        raise ValueError("baixe um vídeo antes de editar")
    ed = video.clean_editor_cfg(cfg, job.get("duracao") or 0)
    legs = [dict(start=float(s["start"]), end=float(s["end"]), text=str(s["text"])[:400]) for s in legendas]
    return ed, legs


def editar(jid, cfg, legendas):
    """Gera o vídeo final em segundo plano: corte, enquadramento, legendas em português, faixa sobre a original e sua voz."""
    job = estado(jid)
    if job.get("status") == "running" and job.get("etapa") == "editando":
        raise ValueError("o vídeo já está sendo gerado")
    ed, legs = _editor(job, cfg, legendas)
    _set(jid, status="running", etapa="editando", msg="Gerando o vídeo final…")
    threading.Thread(target=_rodar_editor, args=(jid, ed, legs), daemon=True).start()
    return estado(jid)


def _rodar_editor(jid, ed, legs):
    job = estado(jid)
    saida = referencia.PASTA / jid / "final.mp4"
    try:
        video.editar(job["video"], saida, ed, legs, voz=job.get("voz"))
        _set(jid, status="ok", etapa="final_pronto", final=str(saida), msg="Vídeo final pronto: baixe ou abra a pasta.")
    except Exception as e:  # ffmpeg falhou: a tela continua com o editor para você ajustar e tentar de novo
        _set(jid, status="error", etapa="pronto", msg=f"Não consegui gerar o vídeo: {str(e)[:300]}")


def quadro(jid, cfg, legendas):
    """Prévia rápida: um quadro (cfg['momento'], em segundos do corte) com o mesmo enquadramento, legendas e faixa do vídeo final."""
    ed, legs = _editor(estado(jid), cfg, legendas)
    video.editar(estado(jid)["video"], referencia.PASTA / jid / "previa.jpg", ed, legs, quadro=True)
    return estado(jid)


def abrir_pasta(jid):
    """Abre no Explorer a pasta do trabalho (vídeo original, sua voz, vídeo final e estúdio)."""
    estado(jid)
    if sys.platform == "win32":
        proc.popen(["explorer.exe", str(referencia.PASTA / jid)])  # o Explorer é janela própria, não é escondido
    return estado(jid)


def buscar(jid):
    """Procura o modelo do vídeo com as consultas (título, hashtags, palavras da fala) e junta os resultados."""
    job = estado(jid)
    consultas = job.get("consultas") or []
    if not consultas:
        raise ValueError("não encontrei termos para buscar: escreva o que procurar")
    _set(jid, etapa="buscando", msg="Procurando o modelo nas plataformas…")
    threading.Thread(target=_rodar_busca, args=(jid, consultas), daemon=True).start()
    return estado(jid)


def _rodar_busca(jid, consultas):
    achados, avisos = referencia.achar_modelo(consultas, lambda q: model_search.search(q))
    _set(jid, status="ok", etapa="modelos", modelos=achados[:20], avisos=avisos,
         msg=f"{len(achados)} modelo(s) encontrado(s)." if achados else "Nenhum modelo encontrado. Envie o arquivo do modelo.")


def gravar_modelo(jid, nome, dados):
    """Modelo enviado por você (.stl ou .3mf), caso a busca não ache o certo."""
    estado(jid)
    if Path(nome).suffix.lower() not in (".stl", ".3mf") or not dados or len(dados) > MAX_VOZ:
        raise ValueError("envie um .stl ou .3mf de até 50 MB")
    pasta = referencia.PASTA / jid
    destino = pasta / ("modelo" + Path(nome).suffix.lower())
    destino.write_bytes(dados)
    _set(jid, modelo=str(destino), modelo_origem="enviado por você")
    return estudio_do_modelo(jid)  # enviado o arquivo, o estúdio começa sozinho


def estudio_do_modelo(jid, indice=0, cor=estudio.COR_PADRAO):
    """Baixa o modelo escolhido da busca (Printables) ou usa o enviado, e gera o estúdio em segundo plano."""
    job = estado(jid)
    pasta = referencia.PASTA / jid
    if not job.get("modelo"):
        lista = job.get("modelos") or []
        escolhido = lista[indice] if 0 <= indice < len(lista) else None
        if escolhido is None or escolhido.get("source") != "printables":
            raise ValueError("escolha um modelo do Printables na lista, ou envie o arquivo do modelo")
        arquivos = model_search.printables_files(escolhido["id"])
        if not arquivos:
            raise ValueError("o Printables não tem arquivo .stl para esse modelo")
        nome, dados = model_search.printables_download(escolhido["id"], arquivos[0]["id"])
        destino = pasta / ("modelo" + Path(nome).suffix.lower())
        destino.write_bytes(dados)
        _set(jid, modelo=str(destino), modelo_origem=escolhido.get("url", ""))
    _set(jid, etapa="estudio", msg="Montando o estúdio no Blender…")
    threading.Thread(target=_rodar_estudio, args=(jid, Path(estado(jid)["modelo"]), pasta / "estudio", cor), daemon=True).start()
    return estado(jid)


def _rodar_estudio(jid, modelo, saida, cor):
    try:
        with BLENDER:
            r = estudio.gerar(modelo, saida, cor=cor)
        _set(jid, status="ok", etapa="estudio_pronto", estudio=r, msg="Estúdio pronto: fotos 1:1, medidas e giro 9:16.")
    except Exception as e:
        _set(jid, status="error", etapa="erro", msg=f"Falha no estúdio: {str(e)[:300]}")


def caminho_arquivo(jid, nome):
    """Arquivo do trabalho para a tela: original, sua voz, prévia, vídeo final ou as fotos do estúdio. Nunca sai da pasta do trabalho."""
    estado(jid)
    pasta = (referencia.PASTA / jid).resolve()
    if nome == "original":
        alvo = next(pasta.glob("original.*"), None)
    elif nome == "voz":
        alvo = pasta / "voz.webm"
    elif nome == "previa":
        alvo = pasta / "previa.jpg"
    elif nome == "final":
        alvo = pasta / "final.mp4"
    elif nome.startswith("estudio/") and ".." not in nome:
        alvo = pasta / nome
    else:
        raise ValueError("arquivo desconhecido")
    if alvo is None or not alvo.is_file():
        raise ValueError("arquivo ainda não existe")
    alvo = alvo.resolve()
    if pasta not in alvo.parents:
        raise ValueError("arquivo fora do trabalho")
    return alvo


def rota(path, data):
    """Despacha as rotas JSON /api/referencia/*."""
    if path == "/api/referencia":
        return iniciar(str(data["url"]))
    if path == "/api/referencia/baixar-de-novo":
        return baixar_de_novo(str(data["id"]), str(data.get("perfil") or "") or None)
    if path == "/api/referencia/editar":
        return editar(str(data["id"]), data.get("cfg") or {}, data.get("legendas") or [])
    if path == "/api/referencia/quadro":
        return quadro(str(data["id"]), data.get("cfg") or {}, data.get("legendas") or [])
    if path == "/api/referencia/abrir-pasta":
        return abrir_pasta(str(data["id"]))
    if path == "/api/referencia/buscar":
        return buscar(str(data["id"]))
    if path == "/api/referencia/estudio":
        return estudio_do_modelo(str(data["id"]), int(data.get("indice", 0)), str(data.get("cor") or estudio.COR_PADRAO))
    raise ValueError("rota desconhecida")
