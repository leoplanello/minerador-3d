"""Vídeo do anúncio com ffmpeg: as imagens em sequência, legenda do roteiro, e, se houver, a voz gravada pelos sócios e uma música de fundo.
Tudo é configurável (formato, tempo por imagem, transição, zoom, legenda, fundo, música); veja VIDEO_DEFAULT."""
import os
import re
import shutil
import proc
import tempfile
import textwrap
from pathlib import Path

from paths import TOOLS


def find_ffmpeg():
    """FFMPEG_PATH, ffmpeg do PATH, tools/ffmpeg ou C:\\ffmpeg\\bin, nessa ordem. Se não achar, devolve o caminho antigo (o erro aparece ao gerar)."""
    for c in (os.environ.get("FFMPEG_PATH"), shutil.which("ffmpeg"), TOOLS / "ffmpeg" / "ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe"):
        if c and Path(c).is_file():
            return Path(c)
    return Path(r"C:\ffmpeg\bin\ffmpeg.exe")


FFMPEG = find_ffmpeg()
FFPROBE = FFMPEG.with_name("ffprobe.exe" if FFMPEG.suffix.lower() == ".exe" else "ffprobe")


def refresh():
    """Reavalia onde está o ffmpeg (depois de instalado pelo app)."""
    global FFMPEG, FFPROBE
    FFMPEG = find_ffmpeg()
    FFPROBE = FFMPEG.with_name("ffprobe.exe" if FFMPEG.suffix.lower() == ".exe" else "ffprobe")
FONT = "C\\:/Windows/Fonts/arial.ttf"  # ':' escapado para o filtro drawtext
FORMATS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}
VIDEO_DEFAULT = dict(format="9:16", seconds=4.0, transition="none", zoom=False, captions=True, caption_size=52, caption_pos="bottom",
                     caption_color="#333333", caption_box=False, background="#ffffff", music=False, music_volume=0.25, fps=30, quality="normal",
                     motion="imagens", engine="eevee", clip_seconds=10.0)  # motion="camera": câmera em movimento na sala (render no Blender)
CRF = {"rapido": 28, "normal": 23, "alta": 18}  # menor = mais nítido e maior
CHOICES = dict(format=tuple(FORMATS), transition=("none", "fade"), caption_pos=("bottom", "center", "top"), quality=tuple(CRF), motion=("imagens", "camera"), engine=("eevee", "cycles"))
SPF_DEFAULT = {"eevee": 2.5, "cycles": 55.0}  # segundos por quadro 1080 x 1920 neste notebook (i5-1135G7); a medição do app substitui


def clean_video_cfg(d):
    """Valida o que veio da tela e completa com o padrão. Levanta ValueError com o motivo."""
    cfg = VIDEO_DEFAULT | {k: v for k, v in (d or {}).items() if k in VIDEO_DEFAULT}
    for k, ok in CHOICES.items():
        if cfg[k] not in ok:
            raise ValueError(f"{k}: opção inválida")
    for k in ("caption_color", "background"):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(cfg[k])):
            raise ValueError("cor inválida")
    seconds, size, vol = float(cfg["seconds"]), int(cfg["caption_size"]), float(cfg["music_volume"])
    if not 1 <= seconds <= 10:
        raise ValueError("o tempo por imagem deve ficar entre 1 e 10 segundos")
    if not 24 <= size <= 120:
        raise ValueError("o tamanho da legenda deve ficar entre 24 e 120")
    if not 0 <= vol <= 1:
        raise ValueError("o volume da música deve ficar entre 0 e 1")
    clip = float(cfg["clip_seconds"])
    if not 4 <= clip <= 30:
        raise ValueError("a duração do vídeo com câmera deve ficar entre 4 e 30 segundos")
    fps = int(cfg["fps"])
    if fps not in (24, 30, 60):
        raise ValueError("fps deve ser 24, 30 ou 60")
    return cfg | dict(clip_seconds=clip, fps=fps, seconds=seconds, caption_size=size, music_volume=vol, zoom=bool(cfg["zoom"]), captions=bool(cfg["captions"]),
                      caption_box=bool(cfg["caption_box"]), music=bool(cfg["music"]))


def captions(script, n, width=26):
    """Divide o roteiro em n legendas por sentença."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script.strip()) if s.strip()] or [script.strip()]
    groups = [[] for _ in range(n)]
    for i, s in enumerate(sents):
        groups[min(i * n // len(sents), n - 1)].append(s)
    return [textwrap.fill(" ".join(g), width) for g in groups]


def fit_caption(text, W, max_h, fs):
    """Quebra a legenda em linhas que cabem na largura e reduz a fonte até o bloco caber em max_h px (mínimo 28). Devolve (texto, fonte)."""
    flat = " ".join(text.split())
    while True:
        wrapped = textwrap.fill(flat, max(10, int(W * 0.86 / (0.52 * fs))))
        if fs <= 28 or len(wrapped.splitlines()) * fs * 1.3 <= max_h:
            return wrapped, fs
        fs -= 2


def duration(audio):
    r = proc.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)], capture_output=True, text=True)
    return float(r.stdout.strip())


def make_video(images, script, out, voice=None, cfg=None, music=None):
    """cfg: dict de clean_video_cfg (ou None para o padrão). music: arquivo de áudio, usado se cfg['music']."""
    if not FFMPEG.exists():
        raise ValueError("ffmpeg não encontrado; instale pelo onboarding ou defina FFMPEG_PATH")
    if not images:
        raise ValueError("gere as imagens antes do vídeo")
    cfg = clean_video_cfg(cfg)
    n = len(images)
    W, H = FORMATS[cfg["format"]]
    per = duration(voice) / n if voice else cfg["seconds"]
    total = per * n
    side = 1080 if cfg["format"] == "9:16" else int(min(W, H) * 0.86)
    img_y = 260 if cfg["format"] == "9:16" else (H - side) // 2
    ty = {"bottom": "h*0.755" if cfg["format"] == "9:16" else "h*0.84", "center": "(h-text_h)/2", "top": "h*0.06"}[cfg["caption_pos"]]
    max_h = H * (0.2 if cfg["format"] == "9:16" else 0.13)  # espaço livre abaixo da imagem para a legenda
    bg = "0x" + cfg["background"][1:]
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cmd, parts = [str(FFMPEG), "-y"], []
        for i, (img, cap) in enumerate(zip(images, captions(script, n, 10 ** 6))):
            if cfg["zoom"]:
                cmd += ["-i", str(img)]
                frames = max(2, round(per * cfg["fps"]))
                base = (f"[{i}:v]scale={side * 2}:{side * 2},zoompan=z='1+0.12*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={side}x{side}:fps={cfg['fps']}")
            else:
                cmd += ["-loop", "1", "-framerate", str(cfg["fps"]), "-t", f"{per:.2f}", "-i", str(img)]
                base = f"[{i}:v]scale={side}:{side}"
            chain = f"{base},pad={W}:{H}:({W}-{side})/2:{img_y}:{bg}"
            if cfg["transition"] == "fade":
                d = min(0.4, per / 3)
                chain += f",fade=t=in:st=0:d={d:.2f}:color={bg},fade=t=out:st={per - d:.2f}:d={d:.2f}:color={bg}"
            if cfg["captions"]:
                f = Path(tmp) / f"c{i}.txt"
                cap, fs = fit_caption(cap, W, max_h, round(cfg["caption_size"] * W / 1080))
                f.write_text(cap, encoding="utf-8", newline="\n")  # CRLF vira uma linha em branco a mais no drawtext
                txt = f.as_posix().replace(":", "\\:")
                box = ":box=1:boxcolor=black@0.5:boxborderw=22" if cfg["caption_box"] else ""
                color = "white" if cfg["caption_box"] and cfg["caption_color"].lower() == "#333333" else cfg["caption_color"]  # texto escuro some na caixa escura
                chain += (f",drawtext=fontfile='{FONT}':textfile='{txt}':fontsize={fs}:fontcolor={color}:x=(w-text_w)/2:y={ty}:line_spacing=12{box}")
            parts.append(chain + f",setsar=1,trim=duration={per:.2f},setpts=PTS-STARTPTS[v{i}]")
        nxt = n
        audio = []
        if voice:
            cmd += ["-i", str(voice)]
            audio.append(f"[{nxt}:a]aresample=44100[a0]")
            nxt += 1
        if cfg["music"] and music:
            cmd += ["-stream_loop", "-1", "-i", str(music)]
            audio.append(f"[{nxt}:a]aresample=44100,volume={cfg['music_volume']}[a1]")
            nxt += 1
        graph = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
        maps = ["-map", "[v]"]
        if voice and cfg["music"] and music:
            graph += ";" + ";".join(audio) + ";[a0][a1]amix=inputs=2:duration=first:normalize=0[aout]"
            maps += ["-map", "[aout]"]
        elif audio:
            graph += ";" + audio[0].replace("[a0]", "[aout]").replace("[a1]", "[aout]")
            maps += ["-map", "[aout]"]
        cmd += ["-filter_complex", graph] + maps + (["-c:a", "aac"] if audio else [])
        cmd += ["-r", str(cfg["fps"]), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", str(CRF[cfg["quality"]]), "-t", f"{total:.2f}", str(out)]
        r = proc.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode or not out.exists():
        raise ValueError("o ffmpeg falhou: " + r.stderr[-300:])
    return out


def estimate(cfg, spf=None, voice_seconds=None):
    """Quantos quadros o vídeo com câmera tem e quanto leva para renderizar. spf: segundos por quadro medidos (senão o padrão do motor)."""
    cfg = clean_video_cfg(cfg)
    frames = max(2, round((voice_seconds or cfg["clip_seconds"]) * cfg["fps"]))
    per = spf or SPF_DEFAULT[cfg["engine"]]
    return dict(frames=frames, spf=round(per, 1), seconds=round(frames * per), text=human_time(frames * per), measured=bool(spf))


def human_time(sec):
    m = round(sec / 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{max(m, 1)} min"


def make_camera_video(frames, script, out, voice=None, cfg=None, music=None):
    """Monta o vídeo a partir dos quadros renderizados (render_1.jpg...) com legenda por trechos do roteiro, voz e música opcionais."""
    if not FFMPEG.exists():
        raise ValueError("ffmpeg não encontrado; instale pelo onboarding ou defina FFMPEG_PATH")
    cfg = clean_video_cfg(cfg)
    W, H = FORMATS[cfg["format"]]
    fps, n = cfg["fps"], len(frames)
    total = n / fps
    ty = {"bottom": "h*0.755" if cfg["format"] == "9:16" else "h*0.84", "center": "(h-text_h)/2", "top": "h*0.06"}[cfg["caption_pos"]]
    max_h = H * (0.2 if cfg["format"] == "9:16" else 0.13)
    color = "white" if cfg["caption_box"] and cfg["caption_color"].lower() == "#333333" else cfg["caption_color"]
    box = ":box=1:boxcolor=black@0.5:boxborderw=22" if cfg["caption_box"] else ""
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        chain, parts = f"[0:v]scale={W}:{H},setsar=1,vignette=PI/5,noise=alls=7:allf=t", captions(script, min(4, max(1, len(re.findall(r"[.!?]", script)))), 10 ** 6)
        if cfg["captions"]:
            for i, cap in enumerate(parts):
                cap, fs = fit_caption(cap, W, max_h, round(cfg["caption_size"] * W / 1080))
                f = Path(tmp) / f"c{i}.txt"
                f.write_text(cap, encoding="utf-8", newline="\n")
                t0, t1 = total * i / len(parts), total * (i + 1) / len(parts)
                chain += (f",drawtext=fontfile='{FONT}':textfile='{f.as_posix().replace(':', chr(92) + ':')}':fontsize={fs}:fontcolor={color}:x=(w-text_w)/2:y={ty}"
                          f":line_spacing=12{box}:enable='between(t,{t0:.2f},{t1 - 0.01:.2f})'")
        cmd = [str(FFMPEG), "-y", "-framerate", str(fps), "-i", str(frames[0].parent / "render_%d.jpg")]
        audio, nxt = [], 1
        if voice:
            cmd += ["-i", str(voice)]
            audio.append(f"[{nxt}:a]aresample=44100[a0]")
            nxt += 1
        if cfg["music"] and music:
            cmd += ["-stream_loop", "-1", "-i", str(music)]
            audio.append(f"[{nxt}:a]aresample=44100,volume={cfg['music_volume']}[a1]")
        graph, maps = chain + "[v]", ["-map", "[v]"]
        if len(audio) == 2:
            graph += ";" + ";".join(audio) + ";[a0][a1]amix=inputs=2:duration=first:normalize=0[aout]"
            maps += ["-map", "[aout]"]
        elif audio:
            graph += ";" + audio[0].replace("[a0]", "[aout]").replace("[a1]", "[aout]")
            maps += ["-map", "[aout]"]
        cmd += ["-filter_complex", graph] + maps + (["-c:a", "aac"] if audio else [])
        cmd += ["-r", str(fps), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", str(CRF[cfg["quality"]]), "-t", f"{total:.2f}", str(out)]
        r = proc.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode or not out.exists():
        raise ValueError("o ffmpeg falhou: " + r.stderr[-300:])
    return out


EDITOR_DEFAULT = dict(inicio=0.0, fim=None, formato="9:16", zoom=1.0, dx=0.0, dy=0.0, legendas=True, legenda_tamanho=52, legenda_pos="bottom",
                      legenda_cor="#ffffff", legenda_caixa=True, cobrir=False, cobrir_y=0.80, cobrir_h=0.14, cobrir_estilo="caixa",
                      cobrir_cor="#000000", som_original="silenciar", vol_original=0.3, vol_voz=1.0, qualidade="normal", momento=1.0)


def clean_editor_cfg(d, duracao):
    """Valida o editor (cortes, enquadramento, legendas, faixa sobre a legenda original e voz). Levanta ValueError com o motivo."""
    if not duracao or duracao <= 0:
        raise ValueError("não consegui ler a duração do vídeo")
    cfg = EDITOR_DEFAULT | {k: v for k, v in (d or {}).items() if k in EDITOR_DEFAULT}
    ini = float(cfg["inicio"] or 0)
    fim = min(float(cfg["fim"]) if cfg["fim"] not in (None, "") else duracao, duracao)
    if not 0 <= ini < fim - 0.9:
        raise ValueError("o corte precisa começar antes do fim e durar pelo menos 1 segundo")
    if cfg["formato"] not in FORMATS or cfg["legenda_pos"] not in ("bottom", "center", "top") or cfg["qualidade"] not in CRF:
        raise ValueError("formato, posição da legenda ou qualidade inválidos")
    if cfg["som_original"] not in ("silenciar", "manter") or cfg["cobrir_estilo"] not in ("caixa", "borrao"):
        raise ValueError("opção de som ou de faixa inválida")
    for k in ("legenda_cor", "cobrir_cor"):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(cfg[k])):
            raise ValueError("cor inválida")
    zoom, dx, dy = float(cfg["zoom"]), float(cfg["dx"]), float(cfg["dy"])
    y, h, size = float(cfg["cobrir_y"]), float(cfg["cobrir_h"]), int(cfg["legenda_tamanho"])
    vol_o, vol_v, momento = float(cfg["vol_original"]), float(cfg["vol_voz"]), float(cfg["momento"] or 0)
    if not (1 <= zoom <= 3 and -1 <= dx <= 1 and -1 <= dy <= 1):
        raise ValueError("enquadramento fora do limite (zoom de 1 a 3, deslocamento de -1 a 1)")
    if not (0 <= y and 0 < h and y + h <= 1):
        raise ValueError("faixa da legenda original fora da tela")
    if not 24 <= size <= 120:
        raise ValueError("o tamanho da legenda deve ficar entre 24 e 120")
    if not (0 <= vol_o <= 2 and 0 <= vol_v <= 2):
        raise ValueError("volume deve ficar entre 0 e 2")
    return cfg | dict(inicio=ini, fim=fim, zoom=zoom, dx=dx, dy=dy, cobrir_y=y, cobrir_h=h, legenda_tamanho=size, vol_original=vol_o,
                      vol_voz=vol_v, momento=min(max(momento, 0.0), fim - ini - 0.1), legendas=bool(cfg["legendas"]),
                      legenda_caixa=bool(cfg["legenda_caixa"]), cobrir=bool(cfg["cobrir"]))


def _tem_audio(arquivo):
    r = proc.run([str(FFPROBE), "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(arquivo)],
                 capture_output=True, text=True)
    return bool(r.stdout.strip())


def _filtro_imagem(cfg, legs, tmp):
    """Enquadra (zoom e deslocamento dentro do formato), cobre a legenda original se pedido e queima as legendas em português.
    legs: (inicio, fim, texto) em segundos do corte. Termina em [vout]."""
    W, H = FORMATS[cfg["formato"]]
    z, dx, dy = cfg["zoom"], cfg["dx"], cfg["dy"]
    partes = [f"[0:v]crop=w='min(iw,ih*{W}/{H})/{z:.3f}':h='min(ih,iw*{H}/{W})/{z:.3f}'"
              f":x='(iw-ow)/2+({dx:.3f})*(iw-ow)/2':y='(ih-oh)/2+({dy:.3f})*(ih-oh)/2',scale={W}:{H},setsar=1[base]"]
    atual = "base"
    if cfg["cobrir"]:  # shortcut: faixa fixa na parte de baixo (posição e altura ajustáveis); sem detecção automática da legenda original
        y, h = cfg["cobrir_y"], cfg["cobrir_h"]
        if cfg["cobrir_estilo"] == "borrao":
            partes.append(f"[{atual}]split[m][b];[b]crop=iw:ih*{h:.3f}:0:ih*{y:.3f},boxblur=12[bb];[m][bb]overlay=0:H*{y:.3f}[c]")
        else:
            partes.append(f"[{atual}]drawbox=x=0:y=ih*{y:.3f}:w=iw:h=ih*{h:.3f}:color=0x{cfg['cobrir_cor'][1:]}:t=fill[c]")
        atual = "c"
    txt = []
    max_h = H * (cfg["cobrir_h"] if cfg["cobrir"] else (0.2 if cfg["formato"] == "9:16" else 0.13))  # com a faixa, a legenda cabe nela
    ty = {"bottom": "h*0.755" if cfg["formato"] == "9:16" else "h*0.84", "center": "(h-text_h)/2", "top": "h*0.06"}[cfg["legenda_pos"]]
    if cfg["cobrir"] and cfg["legenda_pos"] == "bottom":  # centro da faixa: a legenda nova não cai na borda dela
        ty = f"{H * (cfg['cobrir_y'] + cfg['cobrir_h'] / 2):.0f}-text_h/2"
    box = ":box=1:boxcolor=black@0.5:boxborderw=22" if cfg["legenda_caixa"] and not cfg["cobrir"] else ""  # com a faixa, a caixa seria uma faixa a mais
    for i, (a, b, texto) in enumerate(legs):
        f = Path(tmp) / f"l{i}.txt"
        cap, fs = fit_caption(texto, W, max_h, round(cfg["legenda_tamanho"] * W / 1080))
        f.write_text(cap, encoding="utf-8", newline="\n")
        txt.append(f"drawtext=fontfile='{FONT}':textfile='{f.as_posix().replace(':', chr(92) + ':')}':fontsize={fs}:fontcolor={cfg['legenda_cor']}"
                   f":x=(w-text_w)/2:y={ty}:line_spacing=12{box}:enable='between(t,{a:.2f},{b:.2f})'")
    partes.append(f"[{atual}]" + (",".join(txt) if txt else "null") + "[vout]")
    return ";".join(partes)


def _audio(cfg, tem_original, voz):
    """Som do vídeo final em [aout]: o original (se pedido e existir), a sua voz (se gravada) ou os dois. None se não há som."""
    manter = cfg["som_original"] == "manter" and tem_original
    partes = []
    if manter:
        partes.append(f"[0:a]aresample=44100,volume={cfg['vol_original']}[oa]")
    if voz:
        partes.append(f"[1:a]aresample=44100,volume={cfg['vol_voz']}[va]")
    if manter and voz:
        partes.append("[oa][va]amix=inputs=2:duration=longest:normalize=0[aout]")
    elif manter or voz:
        partes.append(f"[{'oa' if manter else 'va'}]acopy[aout]")
    return ";".join(partes) or None


def editar(origem, out, cfg, legendas=(), voz=None, quadro=False):
    """Gera o vídeo final do editor a partir do vídeo baixado (cfg de clean_editor_cfg). Com quadro=True, grava só o JPEG do momento cfg['momento'].
    legendas: dicts start/end/text em segundos do vídeo original. voz: arquivo da sua gravação, que começa junto com o corte."""
    if not FFMPEG.exists():
        raise ValueError("ffmpeg não encontrado; instale pelo onboarding ou defina FFMPEG_PATH")
    ini, dur = cfg["inicio"], cfg["fim"] - cfg["inicio"]
    legs = [(max(0.0, s["start"] - ini), min(dur, s["end"] - ini), s["text"].strip()) for s in legendas
            if cfg["legendas"] and s["end"] > ini and s["start"] < cfg["fim"] and s["text"].strip()]
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        graph = _filtro_imagem(cfg, legs, tmp)
        cmd = [str(FFMPEG), "-y", "-v", "error", "-ss", f"{ini:.2f}", "-i", str(origem)]
        if quadro:  # a prévia usa o mesmo filtro, num quadro só (o -ss depois do -i conta a partir do corte)
            cmd += ["-ss", f"{cfg['momento']:.2f}", "-filter_complex", graph, "-map", "[vout]", "-frames:v", "1", str(out)]
        else:
            if voz:
                cmd += ["-i", str(voz)]
            audio = _audio(cfg, _tem_audio(origem), voz)
            if audio:
                graph += ";" + audio
            cmd += ["-filter_complex", graph, "-map", "[vout]"] + (["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"] if audio else [])
            cmd += ["-t", f"{dur:.2f}", "-r", "30", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", str(CRF[cfg["qualidade"]]),
                    "-movflags", "+faststart", str(out)]
        r = proc.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode or not out.exists():
        raise ValueError("o ffmpeg falhou: " + r.stderr[-300:])
    return out
