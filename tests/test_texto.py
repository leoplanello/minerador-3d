import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import texto

OK = dict(title="Suporte de headset para mesa", description="Suporte impresso em 3D sob encomenda. " * 4,
          bullets=["Imprime em PLA", "Cola na mesa", "Cabe um headset"], scripts=["Oi, esse é o suporte."], keywords=["suporte", "headset"])


def test_parse_reply_ok_limpa_travessao_e_texto_em_volta():
    r = texto.parse_reply("Claro!\n" + json.dumps(dict(OK, title="Suporte — headset mesa")) + "\nPronto.")
    assert r["title"] == "Suporte , headset mesa" and len(r["bullets"]) == 3


@pytest.mark.parametrize("bad", ["sem json", '{"title": "x"}', json.dumps(dict(OK, title="t" * 61)), json.dumps(dict(OK, bullets=["a"])), '{"title": "a", }'])
def test_parse_reply_recusa(bad):
    with pytest.raises(ValueError):
        texto.parse_reply(bad)


def test_prompt_nao_inventa_o_que_falta():
    p = texto.build_prompt(dict(title="X", price=39, material="", minutes=90, grams=12.5, brand="", colors="", sizes="", days="3"))
    assert "1 h 30 min" in p and "não cite cores" in p and "não cite medidas" in p and "R$ 39.00" in p


def test_generate_usa_o_cli(monkeypatch):
    monkeypatch.setenv("CLAUDE_CMD", "claude-falso")
    seen = {}
    monkeypatch.setattr(texto.proc, "run", lambda cmd, **kw: seen.update(cmd=cmd, prompt=kw["input"]) or SimpleNamespace(returncode=0, stdout=json.dumps(OK), stderr=""))
    assert texto.generate(dict(title="X", price=39, material="PLA", minutes=60, grams=10, brand="", colors="", sizes="", days="3"))["title"] == OK["title"]
    assert seen["cmd"] == ["claude-falso", "-p"] and "Responda SOMENTE com um JSON" in seen["prompt"]
