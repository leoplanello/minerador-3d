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
        chain, parts = f"[0:v]scale={W}:{H},setsar=1", captions(script, min(4, max(1, len(re.findall(r"[.!?]", script)))), 10 ** 6)
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
