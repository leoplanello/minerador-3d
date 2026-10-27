import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts" / "app"))
import slice as fatia


def test_parse_gcode_real():
    assert fatia.parse_gcode((HERE / "fixtures" / "orca_gcode_trecho.txt").read_text(encoding="utf-8")) == (41, 4.0)


def test_parse_gcode_dias_horas_e_erro():
    assert fatia.parse_gcode("; total estimated time: 1d 2h 3m\n; filament used [cm3] = 10.0") == (1563, 12.4)
    with pytest.raises(ValueError):
        fatia.parse_gcode("sem nada")


@pytest.mark.skipif(not fatia.SLICER.exists(), reason="Bambu Studio portátil não instalado")
def test_fatiar_cubo_real(tmp_path):
    v = [(x, y, z) for z in (0, 20) for y in (0, 20) for x in (0, 20)]
    f = [(0,2,3),(0,3,1),(4,5,7),(4,7,6),(0,1,5),(0,5,4),(2,6,7),(2,7,3),(0,4,6),(0,6,2),(1,3,7),(1,7,5)]
    stl = "solid c\n" + "".join("facet normal 0 0 0\nouter loop\n" + "".join("vertex %d %d %d\n" % v[i] for i in t) + "endloop\nendfacet\n" for t in f) + "endsolid c\n"
    (tmp_path / "cubo.stl").write_text(stl)
    minutes, grams, out = fatia.slice_model(tmp_path / "cubo.stl", tmp_path / "out")
    assert 10 < minutes < 120 and 1 < grams < 20 and out.suffix == ".gcode"


def test_parse_gcode_bambu_studio():
    txt = "; model printing time: 1h 8m 47s; total estimated time: 1h 8m 48s\n; total filament length [mm] : 2801.52\n; total filament volume [cm^3] : 6738.45\n"
    assert fatia.parse_gcode(txt) == (69, 8.4)


@pytest.mark.skipif(not fatia.SLICER.exists() and not fatia.ORCA.exists(), reason="fatiador portátil não instalado")
def test_teste_de_suporte_acha_suporte_so_onde_precisa(tmp_path):
    import struct
    def caixa(x, y, z, ox=0, oy=0, oz=0):
        v = [(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
        t = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
        return [[(v[i][0] + ox, v[i][1] + oy, v[i][2] + oz) for i in tri] for tri in t]

    def stl(path, tris):
        path.write_bytes(b"\0" * 80 + struct.pack("<I", len(tris)) + b"".join(struct.pack("<12fH", 0, 0, 0, *a, *b, *c, 0) for a, b, c in tris))
        return path
    cubo = stl(tmp_path / "cubo.stl", caixa(30, 30, 30))
    assert fatia.check_support(cubo, tmp_path / "s1")["support"] is False
    mesa = stl(tmp_path / "mesa.stl", caixa(4, 4, 28) + caixa(60, 60, 4, -28, -28, 28))  # um poste fino com um tampo largo no ar: o tampo precisa de suporte
    r = fatia.check_support(mesa, tmp_path / "s2")
    assert r["support"] is True and r["lines"] > 0 and r["minutes"] > 0
