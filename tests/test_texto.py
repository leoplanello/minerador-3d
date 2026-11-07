import json
import struct
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "app"))
import texto

OK = dict(titulo_ml="Suporte de headset para mesa", titulo_shopee="Suporte de headset para mesa, impresso em 3D, PLA",
          descricao="Suporte impresso em 3D sob encomenda. " * 4, bullets=["Imprime em PLA", "Cola na mesa", "Cabe um headset"],
          uso="Encaixe na borda da mesa.", cuidados="Limpe com pano seco.", perguntas=[dict(pergunta="Serve em qual mesa?", resposta="Confira a espessura.")],
          roteiros=["Oi, esse é o suporte."], palavras_chave=["suporte", "headset"])
P = dict(title="Suporte de headset", price=39.0, material="PLA", grams=12.4, dims=(10.0, 116.9, 54.0), colors="", pecas=1, days="3", brand="",
         creditos="Modelo original: https://printables.com/x, por Autor. Licença: CC BY.")


def test_parse_reply_ok_limpa_travessao_e_texto_em_volta():
    r = texto.parse_reply("Claro!\n" + json.dumps(dict(OK, titulo_ml="Suporte — headset mesa")) + "\nPronto.")
    assert r["titulo_ml"] == "Suporte , headset mesa" and len(r["bullets"]) == 3 and r["perguntas"][0]["pergunta"] == "Serve em qual mesa?"


@pytest.mark.parametrize("bad", ["sem json", '{"titulo_ml": "x"}', json.dumps(dict(OK, titulo_ml="t" * 61)),
                                 json.dumps(dict(OK, titulo_shopee="t" * 121)), json.dumps(dict(OK, bullets=["a"])), '{"titulo_ml": "a", }'])
def test_parse_reply_recusa_titulo_fora_do_limite_e_resposta_incompleta(bad):
    with pytest.raises(ValueError):
        texto.parse_reply(bad)


def test_titulo_shopee_aceita_ate_120_e_o_do_ml_fica_em_60():
    assert texto.parse_reply(json.dumps(dict(OK, titulo_shopee="t" * 120)))["titulo_shopee"] == "t" * 120


def test_prompt_nao_leva_tempo_de_impressao_e_nao_inventa_cores():
    p = texto.build_prompt(dict(title="X", price=39, material="PLA", days="3", colors="", brand="", pecas=2))
    assert "Peças por venda: 2" in p and "não cite cores" in p and "Não cite tempo de impressão" in p
    assert "min" not in p.split("Dados do produto")[1].replace("Prazo", "")  # sem minutos nos dados


def test_compose_monta_ficha_com_dados_reais_sem_tempo_nem_travessao():
    a = texto.compose(texto.parse_reply(json.dumps(OK)), P)
    d = a["description"]
    assert a["title"] == OK["titulo_ml"] and a["titulo_shopee"] == OK["titulo_shopee"] and a["bullets"] == OK["bullets"]
    assert "Material: PLA" in d and "Dimensões: 10 x 116,9 x 54 mm" in d and "Peso aproximado: 12,4 g" in d
    assert "Acompanha: 1 peça(s) impressa(s) em 3D" in d and "Produção: 3 dias úteis, impresso depois da compra" in d
    assert "Créditos do modelo\nModelo original: https://printables.com/x, por Autor. Licença: CC BY." in d
    assert "Perguntas frequentes" in d and "Serve em qual mesa?" in d and "Como usar e montar" in d
    assert "—" not in d and "min" not in d.lower().replace("minimo", "")  # tempo de impressão não entra no anúncio
    assert "Cores:" not in d  # sem cores informadas, nenhuma linha de cor


def test_compose_mostra_cores_e_pecas_quando_informadas():
    d = texto.compose(texto.parse_reply(json.dumps(OK)), P | dict(colors="preto, branco", pecas=2, grams=24.8))["description"]
    assert "Cores: preto, branco" in d and "Acompanha: 2 peça(s)" in d and "Peso aproximado: 24,8 g" in d


def test_dimensoes_de_stl_ascii_binario_e_3mf(tmp_path):
    ascii_ = tmp_path / "a.stl"
    ascii_.write_text("solid t\nfacet normal 0 0 0\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 20 5\nendloop\nendfacet\nendsolid t\n")
    assert texto.dimensoes(ascii_) == (10.0, 20.0, 5.0)
    binario = tmp_path / "b.stl"
    tri = struct.pack("<3f", 0, 0, 0) + struct.pack("<9f", 0, 0, 0, 4, 0, 0, 0, 3, 2) + struct.pack("<H", 0)
    binario.write_bytes(b"\0" * 80 + struct.pack("<I", 1) + tri)
    assert texto.dimensoes(binario) == (4.0, 3.0, 2.0)
    mf = tmp_path / "m.3mf"
    with zipfile.ZipFile(mf, "w") as z:
        z.writestr("3D/3dmodel.model", '<model><object><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="7" y="0" z="0"/>'
                                       '<vertex x="0" y="2" z="1"/></vertices></mesh></object></model>')
    assert texto.dimensoes(mf) == (7.0, 2.0, 1.0)
    (tmp_path / "x.stl").write_bytes(b"lixo")
    assert texto.dimensoes(tmp_path / "x.stl") is None and texto.dimensoes(tmp_path / "nao-existe.stl") is None


def test_generate_usa_o_cli_e_devolve_o_anuncio(monkeypatch):
    monkeypatch.setenv("CLAUDE_CMD", "claude-falso")
    seen = {}
    monkeypatch.setattr(texto.proc, "run", lambda cmd, **kw: seen.update(cmd=cmd, prompt=kw["input"]) or SimpleNamespace(returncode=0, stdout=json.dumps(OK), stderr=""))
    r = texto.generate(P)
    assert r["title"] == OK["titulo_ml"] and "Ficha técnica" in r["description"]
    assert seen["cmd"] == ["claude-falso", "-p"] and "Responda SOMENTE com um JSON" in seen["prompt"]
