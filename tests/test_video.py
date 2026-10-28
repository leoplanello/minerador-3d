import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import video


def test_legendas_dividem_por_sentenca():
    caps = video.captions("Primeira frase. Segunda frase! Terceira? Quarta.", 2)
    assert len(caps) == 2 and "Primeira" in caps[0] and "Quarta" in caps[1] and all(caps)


@pytest.mark.skipif(not video.FFMPEG.exists(), reason="ffmpeg ausente")
def test_video_real_9x16_com_e_sem_voz(tmp_path):
    from PIL import Image
    imgs = []
    for i in range(2):
        Image.new("RGB", (400, 400), (200, 80 * i, 50)).save(tmp_path / f"r{i}.jpg")
        imgs.append(tmp_path / f"r{i}.jpg")
    out = video.make_video(imgs, "Oi, este é o suporte. Ele prende na mesa.", tmp_path / "v.mp4")
    info = subprocess.run([str(video.FFPROBE), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert info == "1080,1920" and 7 < video.duration(out) < 9
    voz = tmp_path / "voz.wav"  # 6 s de silêncio como voz de teste
    subprocess.run([str(video.FFMPEG), "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", "6", str(voz)], capture_output=True)
    out2 = video.make_video(imgs, "Oi. Tchau.", tmp_path / "v2.mp4", voz)
    assert 5.5 < video.duration(out2) < 6.8


def test_config_do_video_valida_e_completa():
    assert video.clean_video_cfg({})["format"] == "9:16"
    cfg = video.clean_video_cfg({"format": "1:1", "seconds": "2.5", "caption_size": "60", "zoom": 1})
    assert (cfg["format"], cfg["seconds"], cfg["caption_size"], cfg["zoom"]) == ("1:1", 2.5, 60, True)
    for bad in ({"format": "4:3"}, {"seconds": 99}, {"caption_color": "red"}, {"music_volume": 3}, {"caption_size": 5}):
        with pytest.raises(ValueError):
            video.clean_video_cfg(bad)


@pytest.mark.skipif(not video.FFMPEG.exists(), reason="ffmpeg ausente")
@pytest.mark.parametrize("cfg,size", [
    (dict(format="1:1", seconds=2, transition="fade", caption_pos="center", caption_box=True), "1080,1080"),
    (dict(format="16:9", seconds=2, zoom=True, caption_pos="top", background="#202020", caption_color="#ffffff"), "1920,1080"),
    (dict(seconds=2, captions=False), "1080,1920"),
])
def test_video_real_com_opcoes(tmp_path, cfg, size):
    from PIL import Image
    imgs = []
    for i in range(2):
        Image.new("RGB", (400, 400), (200, 80 * i, 50)).save(tmp_path / f"r{i}.jpg")
        imgs.append(tmp_path / f"r{i}.jpg")
    out = video.make_video(imgs, "Oi. Tchau.", tmp_path / "v.mp4", cfg=cfg)
    info = subprocess.run([str(video.FFPROBE), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert info == size and 3.5 < video.duration(out) < 4.6


@pytest.mark.skipif(not video.FFMPEG.exists(), reason="ffmpeg ausente")
def test_video_real_com_voz_e_musica(tmp_path):
    from PIL import Image
    imgs = []
    for i in range(2):
        Image.new("RGB", (400, 400), (10, 80 * i, 50)).save(tmp_path / f"r{i}.jpg")
        imgs.append(tmp_path / f"r{i}.jpg")
    voz, mus = tmp_path / "voz.wav", tmp_path / "musica.wav"
    for f, t in ((voz, 4), (mus, 2)):  # música mais curta que o vídeo: precisa repetir
        subprocess.run([str(video.FFMPEG), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % t, str(f)], capture_output=True)
    out = video.make_video(imgs, "Oi. Tchau.", tmp_path / "v.mp4", voz, cfg=dict(music=True, music_volume=0.3), music=mus)
    assert 3.6 < video.duration(out) < 4.6
    solo = video.make_video(imgs, "Oi.", tmp_path / "m.mp4", None, cfg=dict(music=True, seconds=3), music=mus)  # só música, sem voz
    assert 5.5 < video.duration(solo) < 6.6


def test_fps_e_qualidade():
    cfg = video.clean_video_cfg({"fps": "24", "quality": "alta"})
    assert cfg["fps"] == 24 and cfg["quality"] == "alta" and video.clean_video_cfg({})["fps"] == 30
    for bad in ({"fps": 25}, {"quality": "x"}):
        with pytest.raises(ValueError):
            video.clean_video_cfg(bad)

def test_legenda_longa_cabe_no_espaco_abaixo_da_imagem():
    longa = "Olha esse suporte de parede para roteador e modem. Ele deixa o aparelho em pé, preso na parede, sem ocupar a mesa. " * 2
    texto, fs = video.fit_caption(longa, 1080, 1920 * 0.2, 60)
    assert len(texto.splitlines()) * fs * 1.3 <= 1920 * 0.2 and fs < 60 and max(map(len, texto.splitlines())) * 0.52 * fs <= 1080 * 0.9
    assert chr(13) not in texto


def test_estimativa_do_video_com_camera():
    e = video.estimate(dict(engine="cycles", clip_seconds=10, fps=24))
    assert e["frames"] == 240 and e["seconds"] == round(240 * video.SPF_DEFAULT["cycles"]) and "h" in e["text"] and not e["measured"]
    m = video.estimate(dict(engine="eevee", clip_seconds=10, fps=30), spf=2.0)
    assert m["frames"] == 300 and m["seconds"] == 600 and m["text"] == "10 min" and m["measured"]
    assert video.estimate(dict(clip_seconds=10, fps=24), voice_seconds=20)["frames"] == 480  # com voz, a duração é a da voz
    for bad in ({"clip_seconds": 2}, {"clip_seconds": 99}, {"engine": "unreal"}, {"motion": "x"}):
        with pytest.raises(ValueError):
            video.clean_video_cfg(bad)
    assert video.human_time(6000) == "1 h 40 min"


@pytest.mark.skipif(not video.FFMPEG.exists(), reason="ffmpeg ausente")
def test_video_com_camera_monta_dos_quadros(tmp_path):
    from PIL import Image
    frames = []
    for i in range(1, 13):
        Image.new("RGB", (1080, 1920), (20 * i, 80, 120)).save(tmp_path / f"render_{i}.jpg")
        frames.append(tmp_path / f"render_{i}.jpg")
    out = video.make_camera_video(frames, "Primeira frase do roteiro. Segunda frase do roteiro.", tmp_path / "v.mp4", cfg=dict(fps=24, clip_seconds=4))
    info = subprocess.run([str(video.FFPROBE), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,nb_frames", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert info.startswith("1080,1920,12")
