import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import identity


def img(path, cor=(200, 30, 30)):
    Image.new("RGB", (900, 700), cor).save(path)
    return path


def resposta(*notas):
    return json.dumps({"candidatos": [{"id": f"C{i}", "nota": n, "motivo": f"motivo {i}"} for i, n in enumerate(notas, 1)]})


def run(tmp_path, monkeypatch, notas, results):
    monkeypatch.setattr(identity, "download", lambda url, dst: img(dst))
    ad = img(tmp_path / "ad.png")
    seen = {}
    ask = lambda prompt, wd: seen.update(prompt=prompt) or resposta(*notas)
    return identity.score_candidates("Porta chaves de parede", [ad], results, ask=ask), seen


def cand(i, **kw):
    return dict(id=str(i), title=f"modelo {i}", thumb=f"https://x/{i}.jpg", commercial=kw.get("commercial"))


def test_aceita_so_acima_do_limiar(tmp_path, monkeypatch):
    res = [cand(1), cand(2), cand(3)]
    (best, v), seen = run(tmp_path, monkeypatch, [40, 92, 85], res)
    assert (best, v) == (1, "identico") and res[1]["identity"] == dict(score=92, reason="motivo 2")
    assert "C3" in seen["prompt"] and "A1" in seen["prompt"] and "modelo 2" in seen["prompt"]


def test_parecido_nao_basta(tmp_path, monkeypatch):
    (best, v), _ = run(tmp_path, monkeypatch, [70, 84], [cand(1), cand(2)])
    assert (best, v) == (1, "sem_identico")  # o melhor é mostrado, mas não é aceito sozinho


def test_licenca_que_proibe_comercial_nunca_e_aceita_sozinha():
    res = [dict(cand(1, commercial=False), identity=dict(score=99, reason="")), dict(cand(2), identity=dict(score=88, reason=""))]
    assert identity.verdict(res) == (1, "identico")
    res.pop()
    assert identity.verdict(res) == (None, "sem_identico")


def test_resposta_ruim():
    assert identity.parse_reply('texto {"candidatos": [{"id": "C9", "nota": 90}, {"id": "C1", "nota": "alta"}, {"id": "C2", "nota": 250}]} fim', 2) == {1: dict(score=100, reason="")}
    for ruim in ("sem json", '{"candidatos": 3}', "{quebrado"):
        with pytest.raises(ValueError):
            identity.parse_reply(ruim, 2)


def test_sem_foto_ou_sem_previa_levanta_erro(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "download", lambda url, dst: img(dst))
    with pytest.raises(ValueError, match="faltam fotos"):
        identity.score_candidates("x", [img(tmp_path / "a.png")], [dict(id="1", title="t", thumb="")], ask=lambda p, w: "")


def test_termos_pela_foto(tmp_path):
    foto = img(tmp_path / "a.png")
    saida = json.dumps({"descricao": "suporte preto com duas garras", "termos": ["router wall mount", " router  wall mount ", "modem bracket", ""]})
    d = identity.visual_terms("Suporte roteador", foto, ask=lambda prompt, wd: saida)
    assert d == dict(descricao="suporte preto com duas garras", termos=["router wall mount", "modem bracket"])  # sem repetidos nem vazios
    with pytest.raises(ValueError):
        identity.visual_terms("x", foto, ask=lambda p, w: "sem json")
