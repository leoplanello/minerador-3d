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
